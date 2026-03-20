"""
Dependency injection for FastAPI routes.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.clock import Clock, RealClock
from app.core.config_manager import ConfigManager
from app.core.order_manager import OrderManager
from app.core.risk_manager import RiskManager
from app.core.trading_engine import TradingEngine
from app.providers.base import BrokerProvider
from app.providers.registry import get_active_provider
from app.api.routes.ws import manager as ws_manager

# ── Singletons ──────────────────────────────────────────────

_config_manager: ConfigManager | None = None
_risk_manager: RiskManager | None = None
_order_manager: OrderManager | None = None
_trading_engine: TradingEngine | None = None
_clock: Clock | None = None
_strategies: dict = {}  # strategy_id → Strategy instance


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


def get_provider() -> BrokerProvider:
    provider = get_active_provider()
    if provider is None:
        raise RuntimeError("No active provider configured. Call /api/providers/activate first.")
    return provider


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


def get_trading_engine() -> TradingEngine:
    global _trading_engine
    if _trading_engine is None:
        _trading_engine = TradingEngine(
            provider=get_provider(),
            risk_manager=get_risk_manager(),
            order_manager=get_order_manager(),
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
