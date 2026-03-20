"""
Paper Trading Provider — hybrid provider using real market data with simulated order fills.

Delegates all market data and authentication calls to the underlying real provider
(e.g., Zerodha), but intercepts order operations and simulates fills in-memory.

This allows the trader to test strategies against live market data without risking capital.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.providers.base import BrokerProvider, OrderError
from app.providers.types import (
    Candle,
    CandleInterval,
    Credentials,
    Exchange,
    HealthStatus,
    Holding,
    Instrument,
    LTPQuote,
    MarginsData,
    MarginSegment,
    OHLCQuote,
    Order,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    OrderType,
    OrderUpdate,
    Position,
    PositionsData,
    ProductType,
    ProviderInfo,
    Quote,
    Session,
    TickerConnection,
    Trade,
    TransactionType,
    Validity,
)

logger = logging.getLogger(__name__)


# ── Paper Order Book ─────────────────────────────────────────────────────────


@dataclass
class PaperPosition:
    """Tracked paper position."""
    tradingsymbol: str
    exchange: Exchange
    instrument_token: int
    product: ProductType
    quantity: int = 0
    average_price: float = 0.0
    buy_quantity: int = 0
    buy_value: float = 0.0
    sell_quantity: int = 0
    sell_value: float = 0.0
    realized_pnl: float = 0.0


class PaperOrderBook:
    """
    In-memory order book that simulates order fills.

    For MARKET orders, fills immediately at current LTP + slippage.
    For LIMIT orders, fills at limit price (simplified — real exchanges have
    more complex matching, but for paper trading this is sufficient).

    Tracks positions and P&L based on simulated fills.
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        slippage_pct: float = 0.05,
        brokerage_per_order: float = 20.0,
    ):
        self.initial_capital = initial_capital
        self.available_capital = initial_capital
        self.slippage_pct = slippage_pct
        self.brokerage_per_order = brokerage_per_order

        self._orders: dict[str, Order] = {}
        self._order_history: dict[str, list[OrderUpdate]] = {}
        self._trades: dict[str, Trade] = {}
        self._positions: dict[str, PaperPosition] = {}  # key: "EXCHANGE:SYMBOL"

        # Callbacks for order updates (wired by PaperTradingProvider)
        self._on_order_update: Any = None

        # Daily tracking
        self._daily_pnl: float = 0.0
        self._total_brokerage: float = 0.0

    def place_order(self, request: OrderRequest, ltp: float) -> OrderResponse:
        """
        Place a paper order. For MARKET orders, fills immediately at LTP + slippage.
        For LIMIT/SL, fills at the requested price (simplified simulation).
        """
        order_id = f"paper_{uuid.uuid4().hex[:12]}"
        now = datetime.now()

        # Determine fill price
        if request.order_type in (OrderType.MARKET, OrderType.STOPLOSS_MARKET):
            slippage = ltp * (self.slippage_pct / 100)
            if request.transaction_type == TransactionType.BUY:
                fill_price = ltp + slippage
            else:
                fill_price = ltp - slippage
        else:
            # LIMIT or SL: fill at the requested price
            fill_price = request.price if request.price > 0 else ltp

        # Check capital for buys
        order_value = fill_price * request.quantity
        total_cost = order_value + self.brokerage_per_order
        if request.transaction_type == TransactionType.BUY:
            if total_cost > self.available_capital:
                # Create rejected order
                order = Order(
                    order_id=order_id,
                    tradingsymbol=request.tradingsymbol,
                    exchange=request.exchange,
                    transaction_type=request.transaction_type,
                    order_type=request.order_type,
                    product=request.product,
                    variety=request.variety,
                    status=OrderStatus.REJECTED,
                    quantity=request.quantity,
                    price=request.price,
                    trigger_price=request.trigger_price,
                    average_price=0.0,
                    filled_quantity=0,
                    pending_quantity=request.quantity,
                    cancelled_quantity=0,
                    disclosed_quantity=request.disclosed_quantity,
                    validity=request.validity,
                    status_message="Paper: Insufficient simulated capital",
                    order_timestamp=now,
                    meta={"paper": True},
                )
                self._orders[order_id] = order
                self._record_history(order_id, order, now)
                return OrderResponse(
                    order_id=order_id,
                    status="rejected",
                    message="Insufficient simulated capital",
                )

        # Create filled order
        order = Order(
            order_id=order_id,
            tradingsymbol=request.tradingsymbol,
            exchange=request.exchange,
            transaction_type=request.transaction_type,
            order_type=request.order_type,
            product=request.product,
            variety=request.variety,
            status=OrderStatus.COMPLETE,
            quantity=request.quantity,
            price=request.price,
            trigger_price=request.trigger_price,
            average_price=fill_price,
            filled_quantity=request.quantity,
            pending_quantity=0,
            cancelled_quantity=0,
            disclosed_quantity=request.disclosed_quantity,
            validity=request.validity,
            order_timestamp=now,
            exchange_timestamp=now,
            meta={"paper": True, "slippage_applied": self.slippage_pct},
        )
        self._orders[order_id] = order

        # Record order history
        self._record_history(order_id, order, now)

        # Create trade (fill) record
        trade_id = f"paper_trade_{uuid.uuid4().hex[:12]}"
        trade = Trade(
            trade_id=trade_id,
            order_id=order_id,
            tradingsymbol=request.tradingsymbol,
            exchange=request.exchange,
            instrument_token=0,
            transaction_type=request.transaction_type,
            product=request.product,
            average_price=fill_price,
            quantity=request.quantity,
            fill_timestamp=now,
            order_timestamp=now,
            exchange_timestamp=now,
        )
        self._trades[trade_id] = trade

        # Update position and capital
        self._update_position(request, fill_price)

        # Deduct brokerage
        self.available_capital -= self.brokerage_per_order
        self._total_brokerage += self.brokerage_per_order

        logger.info(
            "Paper order filled: id=%s %s %s %d @ %.2f (LTP=%.2f, slippage=%.2f%%)",
            order_id, request.transaction_type.value, request.tradingsymbol,
            request.quantity, fill_price, ltp, self.slippage_pct,
        )

        # Fire order update callback
        if self._on_order_update:
            try:
                self._on_order_update(order)
            except Exception:
                pass

        return OrderResponse(
            order_id=order_id,
            status="success",
            message=f"Paper order filled at {fill_price:.2f}",
        )

    def modify_order(self, order_id: str, request: OrderRequest) -> OrderResponse:
        """Modify is a no-op for paper (order already filled instantly)."""
        order = self._orders.get(order_id)
        if not order:
            raise OrderError(f"Paper order {order_id} not found")
        if order.status == OrderStatus.COMPLETE:
            raise OrderError(f"Paper order {order_id} already filled, cannot modify")
        return OrderResponse(order_id=order_id, status="success", message="Paper: modified (no-op)")

    def cancel_order(self, order_id: str) -> OrderResponse:
        """Cancel is a no-op for paper (orders fill instantly)."""
        order = self._orders.get(order_id)
        if not order:
            raise OrderError(f"Paper order {order_id} not found")
        if order.status == OrderStatus.COMPLETE:
            raise OrderError(f"Paper order {order_id} already filled, cannot cancel")
        order.status = OrderStatus.CANCELLED
        now = datetime.now()
        self._record_history(order_id, order, now)
        return OrderResponse(order_id=order_id, status="success", message="Paper: cancelled")

    def get_orders(self) -> list[Order]:
        """Return all paper orders for the day."""
        return list(self._orders.values())

    def get_order_history(self, order_id: str) -> list[OrderUpdate]:
        """Return order state transitions."""
        return self._order_history.get(order_id, [])

    def get_trades(self) -> list[Trade]:
        """Return all paper trades."""
        return list(self._trades.values())

    def get_order_trades(self, order_id: str) -> list[Trade]:
        """Return trades for a specific order."""
        return [t for t in self._trades.values() if t.order_id == order_id]

    def get_positions(self, ltp_map: dict[str, float] | None = None) -> PositionsData:
        """Return current paper positions with live P&L if LTP available."""
        positions: list[Position] = []
        for key, pp in self._positions.items():
            if pp.quantity == 0 and pp.realized_pnl == 0.0:
                continue
            last_price = 0.0
            if ltp_map:
                last_price = ltp_map.get(f"{pp.exchange.value}:{pp.tradingsymbol}", 0.0)

            # Calculate unrealized P&L
            unrealised = 0.0
            if pp.quantity != 0 and last_price > 0:
                if pp.quantity > 0:
                    unrealised = (last_price - pp.average_price) * pp.quantity
                else:
                    unrealised = (pp.average_price - last_price) * abs(pp.quantity)

            total_pnl = pp.realized_pnl + unrealised

            positions.append(Position(
                tradingsymbol=pp.tradingsymbol,
                exchange=pp.exchange,
                instrument_token=pp.instrument_token,
                product=pp.product,
                quantity=pp.quantity,
                overnight_quantity=0,
                multiplier=1,
                average_price=pp.average_price,
                close_price=0.0,
                last_price=last_price,
                value=abs(pp.quantity) * pp.average_price,
                pnl=total_pnl,
                m2m=unrealised,
                unrealised=unrealised,
                realised=pp.realized_pnl,
                buy_quantity=pp.buy_quantity,
                buy_price=pp.buy_value / pp.buy_quantity if pp.buy_quantity > 0 else 0.0,
                buy_value=pp.buy_value,
                sell_quantity=pp.sell_quantity,
                sell_price=pp.sell_value / pp.sell_quantity if pp.sell_quantity > 0 else 0.0,
                sell_value=pp.sell_value,
            ))

        return PositionsData(net=positions, day=positions)

    def get_margins(self) -> MarginsData:
        """Return simulated margin data."""
        used = self.initial_capital - self.available_capital
        return MarginsData(
            equity=MarginSegment(
                enabled=True,
                net=self.available_capital,
                available_cash=self.available_capital,
                opening_balance=self.initial_capital,
                live_balance=self.available_capital,
                intraday_payin=0.0,
                adhoc_margin=0.0,
                collateral=0.0,
                utilised_debits=used,
                utilised_exposure=0.0,
                utilised_span=0.0,
                utilised_option_premium=0.0,
                utilised_holding_sales=0.0,
                utilised_turnover=0.0,
                utilised_m2m_realised=0.0,
                utilised_m2m_unrealised=0.0,
                utilised_payout=0.0,
                utilised_liquid_collateral=0.0,
                utilised_stock_collateral=0.0,
                utilised_delivery=0.0,
            ),
            commodity=None,
        )

    def get_status(self) -> dict[str, Any]:
        """Return paper trading session status."""
        total_realized = sum(p.realized_pnl for p in self._positions.values())
        open_positions = sum(1 for p in self._positions.values() if p.quantity != 0)
        return {
            "mode": "paper",
            "initial_capital": self.initial_capital,
            "available_capital": self.available_capital,
            "total_orders": len(self._orders),
            "total_trades": len(self._trades),
            "open_positions": open_positions,
            "realized_pnl": total_realized,
            "total_brokerage": self._total_brokerage,
            "slippage_pct": self.slippage_pct,
        }

    def reset(self) -> None:
        """Reset the paper trading session (clear all orders/positions/trades)."""
        self._orders.clear()
        self._order_history.clear()
        self._trades.clear()
        self._positions.clear()
        self.available_capital = self.initial_capital
        self._daily_pnl = 0.0
        self._total_brokerage = 0.0
        logger.info("Paper trading session reset. Capital: %.2f", self.initial_capital)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _update_position(self, request: OrderRequest, fill_price: float) -> None:
        """Update position tracking after a fill."""
        key = f"{request.exchange.value}:{request.tradingsymbol}"
        pos = self._positions.get(key)
        if pos is None:
            pos = PaperPosition(
                tradingsymbol=request.tradingsymbol,
                exchange=request.exchange,
                instrument_token=0,
                product=request.product,
            )
            self._positions[key] = pos

        qty = request.quantity
        value = fill_price * qty

        if request.transaction_type == TransactionType.BUY:
            # Check if this closes a short position
            if pos.quantity < 0:
                close_qty = min(qty, abs(pos.quantity))
                pnl = (pos.average_price - fill_price) * close_qty
                pos.realized_pnl += pnl
                self._daily_pnl += pnl
                self.available_capital += pnl
            # Update average price for new/increased long
            old_value = pos.average_price * max(pos.quantity, 0)
            new_qty = pos.quantity + qty
            if new_qty > 0:
                pos.average_price = (old_value + value) / new_qty
            pos.quantity = new_qty
            pos.buy_quantity += qty
            pos.buy_value += value
            self.available_capital -= value
        else:  # SELL
            # Check if this closes a long position
            if pos.quantity > 0:
                close_qty = min(qty, pos.quantity)
                pnl = (fill_price - pos.average_price) * close_qty
                pos.realized_pnl += pnl
                self._daily_pnl += pnl
                self.available_capital += pnl
            # Update average price for new/increased short
            old_value = pos.average_price * max(-pos.quantity, 0)
            new_qty = pos.quantity - qty
            if new_qty < 0:
                pos.average_price = (old_value + value) / abs(new_qty)
            pos.quantity = new_qty
            pos.sell_quantity += qty
            pos.sell_value += value
            self.available_capital += value

    def _record_history(self, order_id: str, order: Order, timestamp: datetime) -> None:
        """Record an order state transition."""
        update = OrderUpdate(
            order_id=order_id,
            status=order.status,
            timestamp=timestamp,
            filled_quantity=order.filled_quantity,
            pending_quantity=order.pending_quantity,
            price=order.price,
            trigger_price=order.trigger_price,
            average_price=order.average_price,
        )
        if order_id not in self._order_history:
            self._order_history[order_id] = []
        self._order_history[order_id].append(update)


# ── Paper Trading Provider ───────────────────────────────────────────────────


class PaperTradingProvider(BrokerProvider):
    """
    Hybrid provider: real market data from Zerodha + simulated order fills.

    All market data calls (quotes, LTP, OHLC, historical, instruments, ticker)
    are delegated to the underlying real provider. All order operations
    (place, modify, cancel, get_orders, get_positions) are handled by
    the internal PaperOrderBook.
    """

    def __init__(
        self,
        real_provider: BrokerProvider,
        initial_capital: float = 1_000_000.0,
        slippage_pct: float = 0.05,
        brokerage_per_order: float = 20.0,
    ):
        self._real = real_provider
        self.order_book = PaperOrderBook(
            initial_capital=initial_capital,
            slippage_pct=slippage_pct,
            brokerage_per_order=brokerage_per_order,
        )

    @property
    def is_paper(self) -> bool:
        return True

    # ── Authentication (delegated) ───────────────────────────────────────

    def get_login_url(self) -> str:
        return self._real.get_login_url()

    async def authenticate(self, credentials: Credentials, request_token: str) -> Session:
        return await self._real.authenticate(credentials, request_token)

    async def invalidate_session(self) -> bool:
        return await self._real.invalidate_session()

    # ── Orders (simulated) ───────────────────────────────────────────────

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place a paper order: get real LTP, simulate fill."""
        try:
            ltp_key = f"{order.exchange.value}:{order.tradingsymbol}"
            ltp_data = await self._real.get_ltp([ltp_key])
            ltp_value = ltp_data.get(ltp_key)
            if ltp_value is not None:
                ltp = float(ltp_value.last_price if hasattr(ltp_value, "last_price") else ltp_value)
            else:
                ltp = order.price if order.price > 0 else 0.0
        except Exception:
            ltp = order.price if order.price > 0 else 0.0

        if ltp <= 0:
            raise OrderError("Cannot place paper order: unable to determine LTP")

        return self.order_book.place_order(order, ltp)

    async def modify_order(self, order_id: str, order: OrderRequest) -> OrderResponse:
        return self.order_book.modify_order(order_id, order)

    async def cancel_order(self, variety: str, order_id: str) -> OrderResponse:
        return self.order_book.cancel_order(order_id)

    async def get_orders(self) -> list[Order]:
        return self.order_book.get_orders()

    async def get_order_history(self, order_id: str) -> list[OrderUpdate]:
        return self.order_book.get_order_history(order_id)

    async def get_trades(self) -> list[Trade]:
        return self.order_book.get_trades()

    async def get_order_trades(self, order_id: str) -> list[Trade]:
        return self.order_book.get_order_trades(order_id)

    # ── Portfolio (simulated positions, real holdings) ────────────────────

    async def get_positions(self) -> PositionsData:
        """Return paper positions with live LTP for P&L calculation."""
        # Collect all symbols that have positions
        symbols = [
            f"{p.exchange.value}:{p.tradingsymbol}"
            for p in self.order_book._positions.values()
            if p.quantity != 0
        ]

        ltp_map: dict[str, float] = {}
        if symbols:
            try:
                ltp_data = await self._real.get_ltp(symbols)
                for key, val in ltp_data.items():
                    if hasattr(val, "last_price"):
                        ltp_map[key] = float(val.last_price)
                    else:
                        ltp_map[key] = float(val)
            except Exception:
                pass

        return self.order_book.get_positions(ltp_map)

    async def get_holdings(self) -> list[Holding]:
        """Paper trading has no holdings."""
        return []

    # ── Market Data (all delegated to real provider) ─────────────────────

    async def get_quote(self, instruments: list[str]) -> dict[str, Quote]:
        return await self._real.get_quote(instruments)

    async def get_ltp(self, instruments: list[str]) -> dict[str, LTPQuote]:
        return await self._real.get_ltp(instruments)

    async def get_ohlc(self, instruments: list[str]) -> dict[str, OHLCQuote]:
        return await self._real.get_ohlc(instruments)

    async def get_historical(
        self,
        instrument_token: int,
        interval: CandleInterval,
        from_dt: datetime,
        to_dt: datetime,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[Candle]:
        return await self._real.get_historical(
            instrument_token, interval, from_dt, to_dt, continuous, oi
        )

    async def get_instruments(self, exchange: Exchange | None = None) -> list[Instrument]:
        return await self._real.get_instruments(exchange)

    # ── Margins (simulated) ──────────────────────────────────────────────

    async def get_margins(self, segment: str | None = None) -> MarginsData:
        return self.order_book.get_margins()

    # ── Ticker (delegated to real provider for live data) ────────────────

    def create_ticker(self) -> TickerConnection:
        return self._real.create_ticker()

    # ── Provider Info ────────────────────────────────────────────────────

    def get_provider_info(self) -> ProviderInfo:
        real_info = self._real.get_provider_info()
        return ProviderInfo(
            name="paper",
            display_name=f"Paper Trading ({real_info.display_name})",
            supported_exchanges=real_info.supported_exchanges,
            supported_products=real_info.supported_products,
            supported_order_types=real_info.supported_order_types,
            supported_varieties=real_info.supported_varieties,
            features={**real_info.features, "paper_trading": True},
        )

    async def health_check(self) -> HealthStatus:
        real_health = await self._real.health_check()
        return HealthStatus(
            healthy=real_health.healthy,
            provider_name="paper",
            latency_ms=real_health.latency_ms,
            message=f"Paper mode ({real_health.message})",
            details={
                **real_health.details,
                "paper_mode": True,
                "paper_status": self.order_book.get_status(),
            },
        )
