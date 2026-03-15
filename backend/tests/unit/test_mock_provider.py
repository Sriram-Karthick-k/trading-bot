"""
Tests for MockProvider.
"""

import pytest

from app.core.clock import VirtualClock
from app.providers.mock.provider import MockProvider
from app.providers.types import (
    Exchange, OrderType, ProductType, TransactionType,
    OrderRequest, OrderStatus, Credentials,
)
from tests.conftest import make_tick


def _creds():
    return Credentials(api_key="mock", api_secret="mock")


def _order(symbol="NIFTY", otype=OrderType.MARKET, qty=10, price=0.0):
    return OrderRequest(
        exchange=Exchange.NSE,
        tradingsymbol=symbol,
        transaction_type=TransactionType.BUY,
        order_type=otype,
        quantity=qty,
        product=ProductType.MIS,
        price=price,
    )


@pytest.fixture
def mock_prov():
    """A fresh mock provider with instrument mapping."""
    clock = VirtualClock()
    mp = MockProvider(clock=clock, capital=1_000_000)
    mp.engine.register_instrument("NSE", "NIFTY", 256265)
    return mp


class TestMockProvider:
    @pytest.mark.asyncio
    async def test_authenticate(self, mock_prov):
        session = await mock_prov.authenticate(_creds(), "mock_token")
        assert session.user_id == "MOCK001"
        assert session.broker == "MOCK"

    @pytest.mark.asyncio
    async def test_place_and_get_orders(self, mock_prov):
        await mock_prov.authenticate(_creds(), "token")
        mock_prov.engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        resp = await mock_prov.place_order(_order())
        assert resp.order_id.startswith("MOCK")
        orders = await mock_prov.get_orders()
        assert len(orders) == 1
        assert orders[0].status == OrderStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_get_positions(self, mock_prov):
        await mock_prov.authenticate(_creds(), "token")
        mock_prov.engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        await mock_prov.place_order(_order())
        positions = await mock_prov.get_positions()
        assert len(positions.net) > 0

    @pytest.mark.asyncio
    async def test_health_check(self, mock_prov):
        health = await mock_prov.health_check()
        assert health.healthy is True

    @pytest.mark.asyncio
    async def test_provider_info(self, mock_prov):
        info = mock_prov.get_provider_info()
        assert info.name == "mock"

    @pytest.mark.asyncio
    async def test_cancel_order(self, mock_prov):
        await mock_prov.authenticate(_creds(), "token")
        mock_prov.engine.update_prices_from_ticks([make_tick(256265, 22000.0)])
        resp = await mock_prov.place_order(_order(otype=OrderType.LIMIT, price=20000.0))
        result = await mock_prov.cancel_order(variety="regular", order_id=resp.order_id)
        assert result is not None
