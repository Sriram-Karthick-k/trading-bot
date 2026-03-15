"""
Strategy base class and parameter schema system.

All trading strategies derive from this ABC.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.providers.types import (
    Candle,
    Order,
    OrderRequest,
    TickData,
)

logger = logging.getLogger(__name__)


class StrategyState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class ParamType(str, Enum):
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    BOOL = "bool"
    ENUM = "enum"


@dataclass
class ParamDef:
    """Definition of a strategy parameter."""
    name: str
    param_type: ParamType
    default: Any
    label: str = ""
    description: str = ""
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None
    required: bool = True


@dataclass
class StrategySignal:
    """A trading signal produced by a strategy."""
    instrument_token: int
    trading_symbol: str
    action: str  # "BUY", "SELL", "EXIT"
    order_request: OrderRequest | None = None
    reason: str = ""
    confidence: float = 1.0
    timestamp: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyMetrics:
    """Runtime metrics for a strategy."""
    total_signals: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    last_signal_time: datetime | None = None


class Strategy(ABC):
    """
    Abstract base class for all trading strategies.

    Lifecycle:
        1. __init__() with params
        2. initialize() - setup indicators, subscribe instruments
        3. on_tick() / on_candle() - process market data
        4. generate signals via _emit_signal()
        5. shutdown() - cleanup
    """

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        self.strategy_id = strategy_id
        self.params = params or {}
        self.state = StrategyState.IDLE
        self.metrics = StrategyMetrics()
        self._signals: list[StrategySignal] = []
        self._subscribed_instruments: list[int] = []

    # ── Abstract interface ──────────────────────────────────

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """Unique identifier name for this strategy type."""
        ...

    @classmethod
    @abstractmethod
    def description(cls) -> str:
        """Human-readable description."""
        ...

    @classmethod
    @abstractmethod
    def get_params_schema(cls) -> list[ParamDef]:
        """Return parameter definitions for UI configuration."""
        ...

    @abstractmethod
    def get_instruments(self) -> list[int]:
        """Return instrument tokens this strategy needs."""
        ...

    @abstractmethod
    async def on_tick(self, tick: TickData) -> None:
        """Process a live tick."""
        ...

    @abstractmethod
    async def on_candle(self, instrument_token: int, candle: Candle) -> None:
        """Process a completed candle."""
        ...

    # ── Optional overrides ──────────────────────────────────

    async def initialize(self) -> None:
        """Called once before the strategy starts receiving data."""
        pass

    async def on_order_update(self, order: Order) -> None:
        """Called when an order placed by this strategy is updated."""
        pass

    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    # ── Lifecycle management ────────────────────────────────

    async def start(self) -> None:
        self.state = StrategyState.RUNNING
        self._subscribed_instruments = self.get_instruments()
        await self.initialize()
        logger.info("Strategy started: %s (id=%s)", self.name(), self.strategy_id)

    async def stop(self) -> None:
        self.state = StrategyState.STOPPED
        await self.shutdown()
        logger.info("Strategy stopped: %s (id=%s)", self.name(), self.strategy_id)

    def pause(self) -> None:
        self.state = StrategyState.PAUSED

    def resume(self) -> None:
        self.state = StrategyState.RUNNING

    # ── Signal management ───────────────────────────────────

    def _emit_signal(self, signal: StrategySignal) -> None:
        """Called by subclasses to emit a trading signal."""
        if signal.timestamp is None:
            signal.timestamp = datetime.now()
        self._signals.append(signal)
        self.metrics.total_signals += 1
        self.metrics.last_signal_time = signal.timestamp
        logger.info(
            "Signal: strategy=%s action=%s symbol=%s reason=%s",
            self.strategy_id, signal.action, signal.trading_symbol, signal.reason,
        )

    def consume_signals(self) -> list[StrategySignal]:
        """Drain pending signals (for order manager to pick up)."""
        signals = list(self._signals)
        self._signals.clear()
        return signals

    def record_trade_result(self, pnl: float) -> None:
        self.metrics.total_trades += 1
        self.metrics.total_pnl += pnl
        if pnl >= 0:
            self.metrics.winning_trades += 1
        else:
            self.metrics.losing_trades += 1

    # ── Helpers ─────────────────────────────────────────────

    def get_param(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)

    def validate_params(self) -> list[str]:
        """Validate current params against schema. Returns list of errors."""
        errors: list[str] = []
        schema = self.get_params_schema()
        for pdef in schema:
            val = self.params.get(pdef.name)
            if val is None:
                if pdef.required:
                    errors.append(f"Missing required parameter: {pdef.name}")
                continue
            if pdef.param_type == ParamType.INT and not isinstance(val, int):
                errors.append(f"{pdef.name}: expected int, got {type(val).__name__}")
            if pdef.param_type == ParamType.FLOAT and not isinstance(val, (int, float)):
                errors.append(f"{pdef.name}: expected float, got {type(val).__name__}")
            if pdef.min_value is not None and isinstance(val, (int, float)) and val < pdef.min_value:
                errors.append(f"{pdef.name}: value {val} < min {pdef.min_value}")
            if pdef.max_value is not None and isinstance(val, (int, float)) and val > pdef.max_value:
                errors.append(f"{pdef.name}: value {val} > max {pdef.max_value}")
            if pdef.param_type == ParamType.ENUM and pdef.enum_values and val not in pdef.enum_values:
                errors.append(f"{pdef.name}: '{val}' not in {pdef.enum_values}")
        return errors

    def get_state_snapshot(self) -> dict[str, Any]:
        """Return full state for UI rendering."""
        return {
            "strategy_id": self.strategy_id,
            "name": self.name(),
            "state": self.state.value,
            "params": self.params,
            "metrics": {
                "total_signals": self.metrics.total_signals,
                "total_trades": self.metrics.total_trades,
                "winning_trades": self.metrics.winning_trades,
                "losing_trades": self.metrics.losing_trades,
                "total_pnl": self.metrics.total_pnl,
                "max_drawdown": self.metrics.max_drawdown,
                "sharpe_ratio": self.metrics.sharpe_ratio,
            },
            "subscribed_instruments": self._subscribed_instruments,
            "pending_signals": len(self._signals),
        }
