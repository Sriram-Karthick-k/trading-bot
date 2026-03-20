"""
Dependency injection for FastAPI routes.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends

from app.core.clock import Clock, RealClock
from app.core.config_manager import ConfigManager
from app.core.order_manager import OrderManager
from app.core.risk_manager import RiskManager
from app.core.trading_engine import TradingEngine
from app.providers.base import BrokerProvider
from app.providers.registry import get_active_provider
from app.services.trade_journal import TradeJournal
from app.api.routes.ws import manager as ws_manager

logger = logging.getLogger(__name__)

# ── Singletons ──────────────────────────────────────────────

_config_manager: ConfigManager | None = None
_risk_manager: RiskManager | None = None
_order_manager: OrderManager | None = None
_trading_engine: TradingEngine | None = None
_clock: Clock | None = None
_strategies: dict = {}  # strategy_id → Strategy instance
_journal: TradeJournal | None = None

# Current trading mode ("live" or "paper")
_trading_mode: str = "live"
_paper_provider: BrokerProvider | None = None


def get_config_manager() -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_clock() -> Clock:
    global _clock
    if _clock is None:
        _clock = RealClock()
    return _clock


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock


def get_trading_mode() -> str:
    """Return the current trading mode ('live' or 'paper')."""
    return _trading_mode


def set_trading_mode(mode: str) -> dict:
    """
    Switch between 'live' and 'paper' trading modes.

    When switching, the trading engine and order manager singletons are reset.
    The engine must be stopped and picks reloaded after a mode switch.

    Returns status dict with old_mode, new_mode, and whether engine was reset.
    """
    global _trading_mode, _order_manager, _trading_engine, _paper_provider

    if mode not in ("live", "paper"):
        raise ValueError(f"Invalid trading mode: {mode!r}. Must be 'live' or 'paper'.")

    old_mode = _trading_mode
    if mode == old_mode:
        return {"old_mode": old_mode, "new_mode": mode, "engine_reset": False}

    # Validate: engine must be stopped/idle before switching
    if _trading_engine is not None:
        from app.core.trading_engine import EngineState
        if _trading_engine.state not in (EngineState.IDLE, EngineState.STOPPED):
            raise RuntimeError(
                f"Cannot switch trading mode while engine is in state '{_trading_engine.state.value}'. "
                "Stop the engine first."
            )

    # Reset singletons so they get recreated with the new provider
    _trading_engine = None
    _order_manager = None
    _paper_provider = None
    _trading_mode = mode

    # Persist to config manager
    config = get_config_manager()
    config.set_db_override("trading.mode", mode)

    logger.info("Trading mode switched: %s → %s", old_mode, mode)
    return {"old_mode": old_mode, "new_mode": mode, "engine_reset": True}


def get_provider() -> BrokerProvider:
    """
    Get the effective provider based on trading mode.

    - live mode: returns the real active provider (e.g., Zerodha)
    - paper mode: wraps the real provider in PaperTradingProvider
    """
    global _paper_provider

    real_provider = get_active_provider()

    if _trading_mode == "paper":
        if _paper_provider is None:
            from app.providers.paper.provider import PaperTradingProvider
            config = get_config_manager()
            capital = config.get("mock.default_capital", float, default=1_000_000.0)
            slippage = config.get("mock.default_slippage_pct", float, default=0.05)
            brokerage = config.get("mock.brokerage_per_order", float, default=20.0)
            _paper_provider = PaperTradingProvider(
                real_provider=real_provider,
                initial_capital=capital,
                slippage_pct=slippage,
                brokerage_per_order=brokerage,
            )
            logger.info(
                "Created PaperTradingProvider (capital=%.0f, slippage=%.2f%%, brokerage=%.0f)",
                capital, slippage, brokerage,
            )
        return _paper_provider

    return real_provider


def get_risk_manager() -> RiskManager:
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager


def get_order_manager() -> OrderManager:
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager(
            provider=get_provider(),
            risk_manager=get_risk_manager(),
        )
    return _order_manager


def get_strategies() -> dict:
    return _strategies


def get_journal() -> TradeJournal:
    """Get or create the singleton trade journal."""
    global _journal
    if _journal is None:
        _journal = TradeJournal()
    return _journal


def get_trading_engine() -> TradingEngine:
    global _trading_engine
    if _trading_engine is None:
        _trading_engine = TradingEngine(
            provider=get_provider(),
            risk_manager=get_risk_manager(),
            order_manager=get_order_manager(),
            journal=get_journal(),
        )
        # Wire WebSocket broadcast callbacks so engine events/ticks
        # are pushed to connected frontend clients in real-time
        _trading_engine._on_event_cb = ws_manager.broadcast_engine_event
        _trading_engine._on_tick_cb = ws_manager.broadcast_tick
        _trading_engine._on_status_cb = ws_manager.broadcast_engine_status
        _trading_engine._on_data_cb = ws_manager.broadcast_data
    return _trading_engine


# ── Type aliases for injection ──────────────────────────────

ConfigDep = Annotated[ConfigManager, Depends(get_config_manager)]
ProviderDep = Annotated[BrokerProvider, Depends(get_provider)]
RiskDep = Annotated[RiskManager, Depends(get_risk_manager)]
OrderDep = Annotated[OrderManager, Depends(get_order_manager)]
ClockDep = Annotated[Clock, Depends(get_clock)]
EngineDep = Annotated[TradingEngine, Depends(get_trading_engine)]
JournalDep = Annotated[TradeJournal, Depends(get_journal)]
