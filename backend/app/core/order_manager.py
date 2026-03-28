"""
Order Manager – bridges strategies to the broker provider.

Handles signal → risk check → order placement → tracking lifecycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.risk_manager import RiskManager
from app.providers.base import BrokerProvider, OrderError
from app.providers.types import Order, OrderRequest, OrderResponse, OrderStatus
from app.services.decision_log import decision_log
from app.strategies.base import Strategy, StrategySignal

logger = logging.getLogger(__name__)


@dataclass
class ManagedOrder:
    """An order tracked by the order manager."""
    order_id: str
    strategy_id: str
    signal: StrategySignal
    request: OrderRequest
    status: OrderStatus = OrderStatus.PUT_ORDER_REQ_RECEIVED
    placed_at: datetime = field(default_factory=datetime.now)
    filled_price: float = 0.0
    filled_quantity: int = 0
    error_message: str = ""


class OrderManager:
    """
    Processes strategy signals through risk checks and places orders.

    Flow:
        Strategy emits signal → OrderManager picks up →
        RiskManager validates → BrokerProvider places order →
        Track fill/rejection → Report back to strategy
    """

    def __init__(self, provider: BrokerProvider, risk_manager: RiskManager):
        self._provider = provider
        self._risk = risk_manager
        self._orders: dict[str, ManagedOrder] = {}
        self._strategy_orders: dict[str, list[str]] = {}  # strategy_id → [order_ids]

    async def process_signals(self, strategy: Strategy) -> list[ManagedOrder]:
        """Drain signals from a strategy and attempt to place orders."""
        signals = strategy.consume_signals()
        results: list[ManagedOrder] = []

        for signal in signals:
            if signal.order_request is None:
                logger.warning("Signal without order_request, skipping: %s", signal)
                continue

            managed = await self._process_single_signal(strategy.strategy_id, signal)
            results.append(managed)

        return results

    async def _process_single_signal(
        self, strategy_id: str, signal: StrategySignal
    ) -> ManagedOrder:
        request = signal.order_request
        assert request is not None

        decision_log.log("order_manager", "info", "Processing signal", {
            "strategy_id": strategy_id,
            "action": signal.action,
            "symbol": signal.trading_symbol,
            "reason": signal.reason,
        })

        # Get current price for risk check
        # Use "EXCHANGE:SYMBOL" format for get_ltp() — matches provider expectations
        try:
            ltp_key = f"{request.exchange.value}:{request.tradingsymbol}"
            ltp_data = await self._provider.get_ltp([ltp_key])
            ltp_value = ltp_data.get(ltp_key)
            if ltp_value is not None:
                # get_ltp may return LTPQuote objects or raw floats
                price = float(ltp_value.last_price if hasattr(ltp_value, "last_price") else ltp_value)
            else:
                price = 0.0
            if request.price and request.price > 0:
                price = request.price

            decision_log.log("order_manager", "debug", "LTP fetched", {
                "ltp_key": ltp_key, "price": price,
            })
        except Exception as e:
            price = request.price or 0.0
            decision_log.log("order_manager", "warn", "LTP fetch failed, using fallback", {
                "error": str(e), "fallback_price": price,
            })

        # Risk check
        open_orders = sum(
            1 for o in self._orders.values()
            if o.status in (OrderStatus.PUT_ORDER_REQ_RECEIVED, OrderStatus.OPEN)
        )
        open_positions = len(set(
            o.signal.instrument_token for o in self._orders.values()
            if o.status == OrderStatus.COMPLETE
        ))

        risk_result = self._risk.check_order(request, price, open_orders, open_positions)

        if not risk_result.passed:
            decision_log.log("order_manager", "warn", "Risk check FAILED", {
                "strategy_id": strategy_id,
                "symbol": signal.trading_symbol,
                "reason": risk_result.reason,
                "price": price,
                "open_orders": open_orders,
                "open_positions": open_positions,
            })
            managed = ManagedOrder(
                order_id="",
                strategy_id=strategy_id,
                signal=signal,
                request=request,
                status=OrderStatus.REJECTED,
                error_message=f"Risk check failed: {risk_result.reason}",
            )
            logger.warning(
                "Order rejected by risk manager: strategy=%s reason=%s",
                strategy_id, risk_result.reason,
            )
            return managed

        # Place order
        try:
            response = await self._provider.place_order(request)
            # place_order returns OrderResponse — extract the order_id string
            order_id = response.order_id if isinstance(response, OrderResponse) else str(response)
            self._risk.record_order_placed()

            managed = ManagedOrder(
                order_id=order_id,
                strategy_id=strategy_id,
                signal=signal,
                request=request,
                status=OrderStatus.PUT_ORDER_REQ_RECEIVED,
            )
            self._orders[order_id] = managed
            self._strategy_orders.setdefault(strategy_id, []).append(order_id)

            decision_log.log("order_manager", "info", "Order placed successfully", {
                "order_id": order_id,
                "strategy_id": strategy_id,
                "symbol": signal.trading_symbol,
                "action": signal.action,
                "quantity": request.quantity,
                "price": price,
            })
            logger.info(
                "Order placed: id=%s strategy=%s symbol=%s action=%s qty=%d",
                order_id, strategy_id, signal.trading_symbol,
                signal.action, request.quantity,
            )
            return managed

        except OrderError as e:
            decision_log.log("order_manager", "error", "Order placement failed", {
                "strategy_id": strategy_id,
                "symbol": signal.trading_symbol,
                "error": str(e),
            })
            managed = ManagedOrder(
                order_id="",
                strategy_id=strategy_id,
                signal=signal,
                request=request,
                status=OrderStatus.REJECTED,
                error_message=str(e),
            )
            logger.error("Order placement failed: %s", e)
            return managed

    async def on_order_update(self, order: Order) -> None:
        """Handle order status updates from the provider."""
        managed = self._orders.get(order.order_id)
        if not managed:
            return

        managed.status = order.status
        managed.filled_price = order.average_price
        managed.filled_quantity = order.filled_quantity

        if order.status == OrderStatus.REJECTED:
            managed.error_message = order.status_message or "Rejected by exchange"

        logger.info(
            "Order update: id=%s status=%s filled=%d/%d price=%.2f",
            order.order_id, order.status.value,
            order.filled_quantity, order.quantity, order.average_price,
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a managed order."""
        managed = self._orders.get(order_id)
        if not managed:
            return False

        try:
            await self._provider.cancel_order(
                variety=managed.request.variety,
                order_id=order_id,
            )
            managed.status = OrderStatus.CANCELLED
            return True
        except OrderError as e:
            logger.error("Cancel failed for %s: %s", order_id, e)
            return False

    async def cancel_strategy_orders(self, strategy_id: str) -> int:
        """Cancel all open orders for a strategy."""
        order_ids = self._strategy_orders.get(strategy_id, [])
        cancelled = 0
        for oid in order_ids:
            managed = self._orders.get(oid)
            if managed and managed.status in (OrderStatus.PUT_ORDER_REQ_RECEIVED, OrderStatus.OPEN):
                if await self.cancel_order(oid):
                    cancelled += 1
        return cancelled

    def get_order(self, order_id: str) -> ManagedOrder | None:
        return self._orders.get(order_id)

    def get_strategy_orders(self, strategy_id: str) -> list[ManagedOrder]:
        order_ids = self._strategy_orders.get(strategy_id, [])
        return [self._orders[oid] for oid in order_ids if oid in self._orders]

    def get_open_orders(self) -> list[ManagedOrder]:
        return [
            o for o in self._orders.values()
            if o.status in (OrderStatus.PUT_ORDER_REQ_RECEIVED, OrderStatus.OPEN)
        ]

    def get_all_orders(self) -> list[ManagedOrder]:
        return list(self._orders.values())

    def get_status(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for o in self._orders.values():
            statuses[o.status.value] = statuses.get(o.status.value, 0) + 1
        return {
            "total_orders": len(self._orders),
            "by_status": statuses,
            "strategies_active": len(self._strategy_orders),
        }
