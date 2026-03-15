"""
Tests for MockEngine – order matching, positions, P&L.
"""

from datetime import datetime
import pytest

from app.core.clock import VirtualClock
from app.providers.mock.engine import MockEngine
from app.providers.types import (
    Exchange, OrderType, ProductType, TransactionType,
    OrderRequest, OrderStatus,
)
from tests.conftest import make_tick


@pytest.fixture
def engine():
    clock = VirtualClock()
    clock.set_time(datetime(2025, 1, 15, 10, 0, 0))
    eng = MockEngine(clock=clock, capital=1_000_000.0)
    eng.register_instrument("NSE", "NIFTY", 256265)
    return eng


def _order(symbol="NIFTY", tx=TransactionType.BUY, otype=OrderType.MARKET,
           qty=10, product=ProductType.MIS, price=0.0):
    return OrderRequest(
        exchange=Exchange.NSE,
        tradingsymbol=symbol,
        transaction_type=tx,
        order_type=otype,
        quantity=qty,
        product=product,
        price=price,
    )


class TestMockEngine:
    def test_place_market_order(self, engine):
        engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        order_id = engine.place_order(_order())
        assert order_id.startswith("MOCK")
        orders = engine.get_orders()
        assert len(orders) == 1
        assert orders[0].status == OrderStatus.COMPLETE

    def test_place_limit_order_pending(self, engine):
        engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        engine.place_order(_order(otype=OrderType.LIMIT, price=21800.0))
        orders = engine.get_orders()
        assert orders[0].status in (OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING)

    def test_limit_order_fills_on_price_cross(self, engine):
        engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        engine.place_order(_order(otype=OrderType.LIMIT, price=21800.0))
        engine.update_prices_from_ticks([make_tick(256265, 21750.0)])
        filled = [o for o in engine.get_orders() if o.status == OrderStatus.COMPLETE]
        assert len(filled) == 1

    def test_position_tracking(self, engine):
        engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        engine.place_order(_order())
        positions = engine.get_positions()
        assert len(positions.net) > 0

    def test_cancel_pending_order(self, engine):
        engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        order_id = engine.place_order(_order(otype=OrderType.LIMIT, price=21000.0))
        engine.cancel_order(order_id)
        assert engine.get_orders()[0].status == OrderStatus.CANCELLED

    def test_reset_clears_state(self, engine):
        engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        engine.place_order(_order())
        engine.reset()
        assert len(engine.get_orders()) == 0
        assert len(engine.get_positions().net) == 0

    def test_sell_order_creates_short_position(self, engine):
        engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        engine.place_order(_order(tx=TransactionType.SELL))
        positions = engine.get_positions().net
        assert any(p.quantity < 0 for p in positions)
