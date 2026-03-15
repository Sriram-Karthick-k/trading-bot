"""
Risk Manager – pre-trade and position-level risk checks.

All limits are configurable via ConfigManager.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.providers.types import OrderRequest
from app.core.clock import Clock, RealClock

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """All configurable risk limits."""
    max_order_value: float = 500_000.0
    max_position_value: float = 1_000_000.0
    max_loss_per_trade: float = 10_000.0
    max_daily_loss: float = 50_000.0
    max_open_orders: int = 20
    max_open_positions: int = 10
    max_quantity_per_order: int = 5000
    max_orders_per_minute: int = 30
    allowed_exchanges: list[str] = field(default_factory=lambda: ["NSE", "BSE", "NFO", "MCX", "CDS", "BFO"])
    trading_start_hour: int = 9
    trading_start_minute: int = 15
    trading_end_hour: int = 15
    trading_end_minute: int = 30
    kill_switch_active: bool = False


@dataclass
class RiskCheckResult:
    passed: bool
    reason: str = ""
    rule: str = ""


class RiskManager:
    """
    Evaluates risk checks before orders are placed.

    Tracks daily P&L, order rate, and position exposure.
    """

    def __init__(self, limits: RiskLimits | None = None, clock: Clock | None = None):
        self.limits = limits or RiskLimits()
        self._clock = clock or RealClock()
        self._daily_pnl: float = 0.0
        self._daily_loss: float = 0.0
        self._today: date = date.today()
        self._order_timestamps: list[datetime] = []
        self._open_order_count: int = 0
        self._open_position_count: int = 0

    def update_limits(self, limits: RiskLimits) -> None:
        self.limits = limits

    def check_order(
        self,
        request: OrderRequest,
        price: float,
        open_orders: int = 0,
        open_positions: int = 0,
    ) -> RiskCheckResult:
        """Run all pre-trade risk checks on an order request."""
        self._open_order_count = open_orders
        self._open_position_count = open_positions
        self._reset_daily_if_needed()

        checks = [
            self._check_kill_switch,
            lambda r, p: self._check_exchange(r),
            lambda r, p: self._check_market_hours(),
            self._check_order_value,
            self._check_quantity,
            lambda r, p: self._check_open_orders(),
            lambda r, p: self._check_open_positions(),
            lambda r, p: self._check_daily_loss(),
            lambda r, p: self._check_order_rate(),
        ]

        for check_fn in checks:
            result = check_fn(request, price)
            if not result.passed:
                logger.warning("Risk check FAILED: rule=%s reason=%s", result.rule, result.reason)
                return result

        return RiskCheckResult(passed=True)

    def record_trade_pnl(self, pnl: float) -> None:
        self._reset_daily_if_needed()
        self._daily_pnl += pnl
        if pnl < 0:
            self._daily_loss += abs(pnl)

    def record_order_placed(self) -> None:
        self._order_timestamps.append(datetime.now())

    def activate_kill_switch(self) -> None:
        self.limits.kill_switch_active = True
        logger.critical("KILL SWITCH ACTIVATED - all orders will be rejected")

    def deactivate_kill_switch(self) -> None:
        self.limits.kill_switch_active = False
        logger.info("Kill switch deactivated")

    def get_daily_pnl(self) -> float:
        self._reset_daily_if_needed()
        return self._daily_pnl

    def get_status(self) -> dict[str, Any]:
        self._reset_daily_if_needed()
        return {
            "kill_switch_active": self.limits.kill_switch_active,
            "daily_pnl": self._daily_pnl,
            "daily_loss": self._daily_loss,
            "daily_loss_limit": self.limits.max_daily_loss,
            "daily_loss_remaining": max(0, self.limits.max_daily_loss - self._daily_loss),
            "orders_last_minute": self._count_recent_orders(),
            "order_rate_limit": self.limits.max_orders_per_minute,
        }

    def reset_daily(self) -> None:
        self._daily_pnl = 0.0
        self._daily_loss = 0.0
        self._order_timestamps.clear()
        self._today = date.today()

    # ── Private checks ──────────────────────────────────────

    def _reset_daily_if_needed(self) -> None:
        today = date.today()
        if today != self._today:
            self.reset_daily()

    def _check_kill_switch(self, request: OrderRequest, price: float) -> RiskCheckResult:
        if self.limits.kill_switch_active:
            return RiskCheckResult(False, "Kill switch is active", "kill_switch")
        return RiskCheckResult(True)

    def _check_exchange(self, request: OrderRequest) -> RiskCheckResult:
        if request.exchange.value not in self.limits.allowed_exchanges:
            return RiskCheckResult(
                False,
                f"Exchange {request.exchange.value} not in allowed list",
                "exchange_filter",
            )
        return RiskCheckResult(True)

    def _check_market_hours(self) -> RiskCheckResult:
        now = self._clock.now().replace(tzinfo=None)
        market_open = now.replace(
            hour=self.limits.trading_start_hour,
            minute=self.limits.trading_start_minute,
            second=0,
        )
        market_close = now.replace(
            hour=self.limits.trading_end_hour,
            minute=self.limits.trading_end_minute,
            second=0,
        )
        if not (market_open <= now <= market_close):
            return RiskCheckResult(False, "Outside market hours", "market_hours")
        return RiskCheckResult(True)

    def _check_order_value(self, request: OrderRequest, price: float) -> RiskCheckResult:
        value = request.quantity * price
        if value > self.limits.max_order_value:
            return RiskCheckResult(
                False,
                f"Order value {value:.2f} exceeds limit {self.limits.max_order_value:.2f}",
                "max_order_value",
            )
        return RiskCheckResult(True)

    def _check_quantity(self, request: OrderRequest, price: float) -> RiskCheckResult:
        if request.quantity > self.limits.max_quantity_per_order:
            return RiskCheckResult(
                False,
                f"Quantity {request.quantity} exceeds limit {self.limits.max_quantity_per_order}",
                "max_quantity",
            )
        return RiskCheckResult(True)

    def _check_open_orders(self) -> RiskCheckResult:
        if self._open_order_count >= self.limits.max_open_orders:
            return RiskCheckResult(
                False,
                f"Open orders {self._open_order_count} >= limit {self.limits.max_open_orders}",
                "max_open_orders",
            )
        return RiskCheckResult(True)

    def _check_open_positions(self) -> RiskCheckResult:
        if self._open_position_count >= self.limits.max_open_positions:
            return RiskCheckResult(
                False,
                f"Open positions {self._open_position_count} >= limit {self.limits.max_open_positions}",
                "max_open_positions",
            )
        return RiskCheckResult(True)

    def _check_daily_loss(self) -> RiskCheckResult:
        if self._daily_loss >= self.limits.max_daily_loss:
            return RiskCheckResult(
                False,
                f"Daily loss {self._daily_loss:.2f} >= limit {self.limits.max_daily_loss:.2f}",
                "max_daily_loss",
            )
        return RiskCheckResult(True)

    def _check_order_rate(self) -> RiskCheckResult:
        recent = self._count_recent_orders()
        if recent >= self.limits.max_orders_per_minute:
            return RiskCheckResult(
                False,
                f"Order rate {recent}/min >= limit {self.limits.max_orders_per_minute}/min",
                "order_rate",
            )
        return RiskCheckResult(True)

    def _count_recent_orders(self) -> int:
        cutoff = datetime.now().timestamp() - 60
        return sum(1 for ts in self._order_timestamps if ts.timestamp() > cutoff)
