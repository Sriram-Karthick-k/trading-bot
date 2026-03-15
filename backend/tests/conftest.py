"""
Shared test fixtures and configuration.
"""

from __future__ import annotations

import pytest
from datetime import datetime

from app.core.clock import VirtualClock, RealClock
from app.core.config_manager import ConfigManager
from app.core.risk_manager import RiskManager, RiskLimits
from app.providers.mock.provider import MockProvider
from app.providers.mock.engine import MockEngine
from app.providers.mock.time_controller import TimeController
from app.providers.types import (
    Exchange,
    OrderType,
    ProductType,
    TransactionType,
    Variety,
    Validity,
    OrderRequest,
    TickData,
    TickMode,
)


# ── Clock fixtures ──────────────────────────────────────────

@pytest.fixture
def virtual_clock():
    clock = VirtualClock()
    clock.set_time(datetime(2025, 1, 15, 10, 0, 0))
    return clock


@pytest.fixture
def real_clock():
    return RealClock()


# ── Provider fixtures ───────────────────────────────────────

@pytest.fixture
def mock_engine(virtual_clock):
    return MockEngine(clock=virtual_clock)


@pytest.fixture
def time_controller(virtual_clock):
    return TimeController(clock=virtual_clock)


@pytest.fixture
def mock_provider():
    return MockProvider(clock=VirtualClock())


# ── Risk fixtures ───────────────────────────────────────────

@pytest.fixture
def risk_limits():
    return RiskLimits(
        max_order_value=500_000,
        max_daily_loss=50_000,
        max_open_orders=20,
        max_open_positions=10,
        max_quantity_per_order=5000,
        max_orders_per_minute=30,
    )


@pytest.fixture
def risk_manager(risk_limits):
    # Use a VirtualClock set to market hours so time-dependent checks pass
    from app.core.clock import VirtualClock
    clock = VirtualClock(initial_time=datetime(2025, 1, 15, 10, 0, 0))
    return RiskManager(limits=risk_limits, clock=clock)


# ── Config fixtures ─────────────────────────────────────────

@pytest.fixture
def config_manager():
    return ConfigManager()


# ── Order fixtures ──────────────────────────────────────────

@pytest.fixture
def sample_order_request():
    return OrderRequest(
        exchange=Exchange.NSE,
        tradingsymbol="RELIANCE",
        transaction_type=TransactionType.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        product=ProductType.CNC,
        variety=Variety.REGULAR,
        validity=Validity.DAY,
    )


@pytest.fixture
def sample_limit_order():
    return OrderRequest(
        exchange=Exchange.NSE,
        tradingsymbol="INFY",
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=5,
        product=ProductType.MIS,
        price=1500.0,
        variety=Variety.REGULAR,
        validity=Validity.DAY,
    )


# ── Tick fixtures ───────────────────────────────────────────

@pytest.fixture
def sample_tick():
    return TickData(
        instrument_token=256265,
        last_price=22450.50,
        last_quantity=100,
        average_price=22400.0,
        volume=1000000,
        buy_quantity=50000,
        sell_quantity=45000,
        ohlc_open=22300.0,
        ohlc_high=22500.0,
        ohlc_low=22250.0,
        ohlc_close=22350.0,
        timestamp=datetime(2025, 1, 15, 10, 30, 0),
        mode=TickMode.FULL,
    )


def make_tick(token: int, price: float, ts: datetime | None = None) -> TickData:
    """Helper to create a tick with minimal params."""
    return TickData(
        instrument_token=token,
        last_price=price,
        timestamp=ts or datetime(2025, 1, 15, 10, 0, 0),
        mode=TickMode.LTP,
    )
