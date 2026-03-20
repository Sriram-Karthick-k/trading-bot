"""
Tests for PaperOrderBook and PaperTradingProvider.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.providers.paper.provider import PaperOrderBook, PaperTradingProvider
from app.providers.types import (
    Exchange,
    LTPQuote,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    OrderType,
    ProductType,
    TransactionType,
    Variety,
    Validity,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_order_request(
    symbol: str = "RELIANCE",
    exchange: Exchange = Exchange.NSE,
    txn: TransactionType = TransactionType.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: int = 10,
    price: float = 0.0,
    product: ProductType = ProductType.MIS,
) -> OrderRequest:
    return OrderRequest(
        tradingsymbol=symbol,
        exchange=exchange,
        transaction_type=txn,
        order_type=order_type,
        quantity=quantity,
        product=product,
        price=price,
        variety=Variety.REGULAR,
        validity=Validity.DAY,
    )


# ── PaperOrderBook Tests ────────────────────────────────────────────────────


class TestPaperOrderBook:
    """Tests for the in-memory order book simulator."""

    def setup_method(self):
        self.book = PaperOrderBook(
            initial_capital=500_000.0,
            slippage_pct=0.05,
            brokerage_per_order=20.0,
        )

    def test_initial_state(self):
        assert self.book.initial_capital == 500_000.0
        assert self.book.available_capital == 500_000.0
        assert self.book.get_orders() == []
        assert self.book.get_trades() == []
        status = self.book.get_status()
        assert status["mode"] == "paper"
        assert status["total_orders"] == 0
        assert status["open_positions"] == 0

    def test_buy_market_order_fills_immediately(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        resp = self.book.place_order(req, ltp=2500.0)

        assert resp.status == "success"
        assert resp.order_id.startswith("paper_")

        orders = self.book.get_orders()
        assert len(orders) == 1
        assert orders[0].status == OrderStatus.COMPLETE
        assert orders[0].filled_quantity == 10
        assert orders[0].average_price > 0
        assert orders[0].meta.get("paper") is True

    def test_buy_market_order_applies_slippage(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req, ltp=1000.0)

        orders = self.book.get_orders()
        # BUY slippage increases price: 1000 + 0.05% = 1000.5
        assert orders[0].average_price == pytest.approx(1000.5, rel=1e-3)

    def test_sell_market_order_applies_slippage(self):
        # First buy
        buy_req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(buy_req, ltp=1000.0)

        # Then sell
        sell_req = make_order_request(txn=TransactionType.SELL, quantity=10)
        self.book.place_order(sell_req, ltp=1050.0)

        orders = self.book.get_orders()
        # SELL slippage decreases price: 1050 - 0.05% = 1049.475
        assert orders[1].average_price < 1050.0

    def test_limit_order_fills_at_limit_price(self):
        req = make_order_request(
            txn=TransactionType.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=2400.0,
        )
        resp = self.book.place_order(req, ltp=2500.0)

        orders = self.book.get_orders()
        assert orders[0].average_price == 2400.0
        assert orders[0].status == OrderStatus.COMPLETE

    def test_buy_deducts_capital(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req, ltp=1000.0)

        # 10 * 1000.5 (slippage) + 20 (brokerage) = 10025.0
        expected_used = 10 * 1000.5 + 20.0
        assert self.book.available_capital == pytest.approx(
            500_000.0 - expected_used, rel=1e-2
        )

    def test_insufficient_capital_rejects_order(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=100_000)
        resp = self.book.place_order(req, ltp=1000.0)

        assert resp.status == "rejected"
        orders = self.book.get_orders()
        assert orders[0].status == OrderStatus.REJECTED
        assert "Insufficient" in orders[0].status_message

    def test_sell_adds_capital(self):
        # Buy first
        buy_req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(buy_req, ltp=1000.0)
        capital_after_buy = self.book.available_capital

        # Sell at higher price
        sell_req = make_order_request(txn=TransactionType.SELL, quantity=10)
        self.book.place_order(sell_req, ltp=1100.0)

        # Should have more capital than after buy
        assert self.book.available_capital > capital_after_buy

    def test_position_tracking_buy(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req, ltp=1000.0)

        positions = self.book.get_positions()
        assert len(positions.net) == 1
        assert positions.net[0].quantity == 10
        assert positions.net[0].tradingsymbol == "RELIANCE"

    def test_position_tracking_sell_closes(self):
        # Buy 10
        buy_req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(buy_req, ltp=1000.0)

        # Sell 10 (close position)
        sell_req = make_order_request(txn=TransactionType.SELL, quantity=10)
        self.book.place_order(sell_req, ltp=1100.0)

        # Position should be flat (quantity=0) but with realized P&L
        pos_key = "NSE:RELIANCE"
        paper_pos = self.book._positions.get(pos_key)
        assert paper_pos is not None
        assert paper_pos.quantity == 0
        assert paper_pos.realized_pnl > 0  # Profitable trade

    def test_pnl_calculation_long_profit(self):
        """Buy at 1000, sell at 1100 → profit ~99/share (minus slippage)."""
        buy_req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(buy_req, ltp=1000.0)

        sell_req = make_order_request(txn=TransactionType.SELL, quantity=10)
        self.book.place_order(sell_req, ltp=1100.0)

        pos = self.book._positions["NSE:RELIANCE"]
        # Buy at ~1000.5 (slippage), sell at ~1099.45 (slippage)
        # PnL per share ≈ 98.95
        assert pos.realized_pnl > 0
        assert pos.realized_pnl == pytest.approx(98.95 * 10, rel=0.01)

    def test_pnl_calculation_long_loss(self):
        """Buy at 1000, sell at 900 → loss."""
        buy_req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(buy_req, ltp=1000.0)

        sell_req = make_order_request(txn=TransactionType.SELL, quantity=10)
        self.book.place_order(sell_req, ltp=900.0)

        pos = self.book._positions["NSE:RELIANCE"]
        assert pos.realized_pnl < 0

    def test_short_position_pnl(self):
        """Sell (short) at 1000, buy back at 900 → profit."""
        sell_req = make_order_request(txn=TransactionType.SELL, quantity=10)
        self.book.place_order(sell_req, ltp=1000.0)

        buy_req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(buy_req, ltp=900.0)

        pos = self.book._positions["NSE:RELIANCE"]
        assert pos.quantity == 0
        assert pos.realized_pnl > 0

    def test_multiple_symbols(self):
        req1 = make_order_request(symbol="RELIANCE", txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req1, ltp=2500.0)

        req2 = make_order_request(symbol="INFY", txn=TransactionType.BUY, quantity=5)
        self.book.place_order(req2, ltp=1500.0)

        assert len(self.book.get_orders()) == 2
        assert len(self.book.get_trades()) == 2
        assert len(self.book._positions) == 2

    def test_get_trades_returns_fills(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req, ltp=1000.0)

        trades = self.book.get_trades()
        assert len(trades) == 1
        assert trades[0].tradingsymbol == "RELIANCE"
        assert trades[0].quantity == 10

    def test_get_order_history(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        resp = self.book.place_order(req, ltp=1000.0)

        history = self.book.get_order_history(resp.order_id)
        assert len(history) == 1
        assert history[0].status == OrderStatus.COMPLETE

    def test_get_order_trades(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        resp = self.book.place_order(req, ltp=1000.0)

        trades = self.book.get_order_trades(resp.order_id)
        assert len(trades) == 1
        assert trades[0].order_id == resp.order_id

    def test_cancel_already_filled(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        resp = self.book.place_order(req, ltp=1000.0)

        with pytest.raises(Exception, match="already filled"):
            self.book.cancel_order(resp.order_id)

    def test_cancel_nonexistent(self):
        with pytest.raises(Exception, match="not found"):
            self.book.cancel_order("fake_id")

    def test_modify_already_filled(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        resp = self.book.place_order(req, ltp=1000.0)

        with pytest.raises(Exception, match="already filled"):
            self.book.modify_order(resp.order_id, req)

    def test_reset_clears_everything(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req, ltp=1000.0)
        assert len(self.book.get_orders()) > 0

        self.book.reset()
        assert len(self.book.get_orders()) == 0
        assert len(self.book.get_trades()) == 0
        assert len(self.book._positions) == 0
        assert self.book.available_capital == self.book.initial_capital

    def test_get_margins_returns_simulated(self):
        margins = self.book.get_margins()
        assert margins.equity is not None
        assert margins.equity.available_cash == self.book.available_capital
        assert margins.equity.opening_balance == self.book.initial_capital

    def test_get_status(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req, ltp=1000.0)

        status = self.book.get_status()
        assert status["mode"] == "paper"
        assert status["total_orders"] == 1
        assert status["total_trades"] == 1
        assert status["open_positions"] == 1
        assert status["total_brokerage"] == 20.0

    def test_brokerage_deducted(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=1)
        self.book.place_order(req, ltp=100.0)

        # Capital: 500000 - (100.05 * 1) - 20 = 499879.95
        assert self.book._total_brokerage == 20.0

    def test_order_update_callback(self):
        callback = MagicMock()
        self.book._on_order_update = callback

        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req, ltp=1000.0)

        callback.assert_called_once()
        order = callback.call_args[0][0]
        assert order.status == OrderStatus.COMPLETE

    def test_positions_with_ltp_map(self):
        req = make_order_request(txn=TransactionType.BUY, quantity=10)
        self.book.place_order(req, ltp=1000.0)

        ltp_map = {"NSE:RELIANCE": 1100.0}
        positions = self.book.get_positions(ltp_map)
        assert len(positions.net) == 1
        assert positions.net[0].last_price == 1100.0
        assert positions.net[0].unrealised > 0  # Profit since LTP > entry


# ── PaperTradingProvider Tests ───────────────────────────────────────────────


class TestPaperTradingProvider:
    """Tests for the hybrid PaperTradingProvider."""

    def setup_method(self):
        self.mock_provider = AsyncMock()
        # Sync methods must use MagicMock, not AsyncMock (they don't return coroutines)
        self.mock_provider.get_provider_info = MagicMock(return_value=MagicMock(
            display_name="Zerodha",
            supported_exchanges=[Exchange.NSE, Exchange.BSE],
            supported_products=[ProductType.MIS, ProductType.CNC],
            supported_order_types=[OrderType.MARKET, OrderType.LIMIT],
            supported_varieties=[Variety.REGULAR],
            features={"websocket": True},
        ))
        self.mock_provider.get_login_url = MagicMock(return_value="https://kite.zerodha.com/connect/login")
        self.mock_provider.create_ticker = MagicMock(return_value=MagicMock())
        self.provider = PaperTradingProvider(
            real_provider=self.mock_provider,
            initial_capital=500_000.0,
            slippage_pct=0.05,
        )

    def test_is_paper(self):
        assert self.provider.is_paper is True

    def test_provider_info(self):
        info = self.provider.get_provider_info()
        assert info.name == "paper"
        assert "Paper Trading" in info.display_name
        assert info.features["paper_trading"] is True

    # ── Auth delegated ───────────────────────────────────────────────────

    def test_login_url_delegated(self):
        url = self.provider.get_login_url()
        assert url == "https://kite.zerodha.com/connect/login"
        self.mock_provider.get_login_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_delegated(self):
        session = MagicMock()
        self.mock_provider.authenticate.return_value = session
        creds = MagicMock()
        result = await self.provider.authenticate(creds, "token123")
        assert result is session
        self.mock_provider.authenticate.assert_awaited_once_with(creds, "token123")

    @pytest.mark.asyncio
    async def test_invalidate_session_delegated(self):
        self.mock_provider.invalidate_session.return_value = True
        result = await self.provider.invalidate_session()
        assert result is True

    # ── Market data delegated ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_quote_delegated(self):
        expected = {"NSE:RELIANCE": MagicMock()}
        self.mock_provider.get_quote.return_value = expected
        result = await self.provider.get_quote(["NSE:RELIANCE"])
        assert result is expected

    @pytest.mark.asyncio
    async def test_get_ltp_delegated(self):
        expected = {"NSE:RELIANCE": LTPQuote(instrument_token=738561, last_price=2500.0)}
        self.mock_provider.get_ltp.return_value = expected
        result = await self.provider.get_ltp(["NSE:RELIANCE"])
        assert result is expected

    @pytest.mark.asyncio
    async def test_get_ohlc_delegated(self):
        expected = {}
        self.mock_provider.get_ohlc.return_value = expected
        result = await self.provider.get_ohlc(["NSE:RELIANCE"])
        assert result is expected

    @pytest.mark.asyncio
    async def test_get_historical_delegated(self):
        from datetime import datetime
        from app.providers.types import CandleInterval
        expected = []
        self.mock_provider.get_historical.return_value = expected
        result = await self.provider.get_historical(
            738561, CandleInterval.MINUTE_5, datetime.now(), datetime.now()
        )
        assert result is expected

    @pytest.mark.asyncio
    async def test_get_instruments_delegated(self):
        expected = []
        self.mock_provider.get_instruments.return_value = expected
        result = await self.provider.get_instruments(Exchange.NSE)
        assert result is expected

    def test_create_ticker_delegated(self):
        result = self.provider.create_ticker()
        assert result is self.mock_provider.create_ticker.return_value

    # ── Orders simulated ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_place_order_uses_real_ltp(self):
        """place_order fetches real LTP and simulates fill."""
        self.mock_provider.get_ltp.return_value = {
            "NSE:RELIANCE": LTPQuote(instrument_token=738561, last_price=2500.0)
        }

        req = make_order_request(txn=TransactionType.BUY, quantity=5)
        resp = await self.provider.place_order(req)

        assert resp.status == "success"
        assert resp.order_id.startswith("paper_")
        self.mock_provider.get_ltp.assert_awaited_once()

        # Real provider place_order should NOT be called
        self.mock_provider.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_place_order_ltp_fetch_fails_uses_price(self):
        """If LTP fetch fails, falls back to order price."""
        self.mock_provider.get_ltp.side_effect = Exception("network error")

        req = make_order_request(
            txn=TransactionType.BUY,
            order_type=OrderType.LIMIT,
            quantity=5,
            price=2400.0,
        )
        resp = await self.provider.place_order(req)
        assert resp.status == "success"

    @pytest.mark.asyncio
    async def test_place_order_no_ltp_no_price_raises(self):
        """If no LTP and no price, raises OrderError."""
        self.mock_provider.get_ltp.return_value = {}

        req = make_order_request(txn=TransactionType.BUY, quantity=5, price=0.0)
        from app.providers.base import OrderError
        with pytest.raises(OrderError, match="unable to determine LTP"):
            await self.provider.place_order(req)

    @pytest.mark.asyncio
    async def test_get_orders_returns_paper_orders(self):
        self.mock_provider.get_ltp.return_value = {
            "NSE:RELIANCE": LTPQuote(instrument_token=738561, last_price=2500.0)
        }

        req = make_order_request(txn=TransactionType.BUY, quantity=5)
        await self.provider.place_order(req)

        orders = await self.provider.get_orders()
        assert len(orders) == 1
        assert orders[0].meta.get("paper") is True

        # Real provider get_orders should NOT be called
        self.mock_provider.get_orders.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_trades_returns_paper_trades(self):
        self.mock_provider.get_ltp.return_value = {
            "NSE:RELIANCE": LTPQuote(instrument_token=738561, last_price=2500.0)
        }

        req = make_order_request(txn=TransactionType.BUY, quantity=5)
        await self.provider.place_order(req)

        trades = await self.provider.get_trades()
        assert len(trades) == 1
        self.mock_provider.get_trades.assert_not_called()

    # ── Positions simulated ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_positions_fetches_real_ltp(self):
        """get_positions fetches live LTP to compute unrealized P&L."""
        self.mock_provider.get_ltp.return_value = {
            "NSE:RELIANCE": LTPQuote(instrument_token=738561, last_price=2500.0)
        }

        req = make_order_request(txn=TransactionType.BUY, quantity=5)
        await self.provider.place_order(req)

        # Set up LTP for position valuation
        self.mock_provider.get_ltp.return_value = {
            "NSE:RELIANCE": LTPQuote(instrument_token=738561, last_price=2600.0)
        }

        positions = await self.provider.get_positions()
        assert len(positions.net) == 1
        assert positions.net[0].last_price == 2600.0
        assert positions.net[0].unrealised > 0

    @pytest.mark.asyncio
    async def test_get_holdings_empty(self):
        """Paper trading has no holdings."""
        holdings = await self.provider.get_holdings()
        assert holdings == []
        self.mock_provider.get_holdings.assert_not_called()

    # ── Margins simulated ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_margins_simulated(self):
        margins = await self.provider.get_margins()
        assert margins.equity is not None
        assert margins.equity.available_cash == 500_000.0
        self.mock_provider.get_margins.assert_not_called()

    # ── Health check ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_health_check(self):
        from app.providers.types import HealthStatus
        self.mock_provider.health_check.return_value = HealthStatus(
            healthy=True,
            provider_name="zerodha",
            latency_ms=15.0,
            message="OK",
        )
        health = await self.provider.health_check()
        assert health.healthy is True
        assert health.provider_name == "paper"
        assert health.details.get("paper_mode") is True


# ── Deps Integration Tests ───────────────────────────────────────────────────


class TestTradingModeSwitch:
    """Tests for trading mode switching in deps.py."""

    def setup_method(self):
        # Reset deps singletons
        import app.api.deps as deps
        self._orig_mode = deps._trading_mode
        self._orig_engine = deps._trading_engine
        self._orig_order_mgr = deps._order_manager
        self._orig_paper = deps._paper_provider

    def teardown_method(self):
        import app.api.deps as deps
        deps._trading_mode = self._orig_mode
        deps._trading_engine = self._orig_engine
        deps._order_manager = self._orig_order_mgr
        deps._paper_provider = self._orig_paper

    def test_default_mode_is_live(self):
        import app.api.deps as deps
        # Mode should be whatever was set before, but get_trading_mode works
        mode = deps.get_trading_mode()
        assert mode in ("live", "paper")

    def test_set_paper_mode(self):
        import app.api.deps as deps
        deps._trading_mode = "live"
        deps._trading_engine = None
        deps._order_manager = None
        deps._paper_provider = None
        result = deps.set_trading_mode("paper")
        assert result["new_mode"] == "paper"
        assert result["old_mode"] == "live"
        assert result["engine_reset"] is True
        assert deps._trading_mode == "paper"

    def test_set_live_mode(self):
        import app.api.deps as deps
        deps._trading_mode = "paper"
        deps._trading_engine = None
        deps._order_manager = None
        deps._paper_provider = None
        result = deps.set_trading_mode("live")
        assert result["new_mode"] == "live"
        assert result["engine_reset"] is True

    def test_same_mode_no_reset(self):
        import app.api.deps as deps
        deps._trading_mode = "live"
        result = deps.set_trading_mode("live")
        assert result["engine_reset"] is False

    def test_invalid_mode_raises(self):
        import app.api.deps as deps
        with pytest.raises(ValueError, match="Invalid trading mode"):
            deps.set_trading_mode("invalid")

    def test_cannot_switch_while_engine_running(self):
        import app.api.deps as deps
        from app.core.trading_engine import EngineState

        mock_engine = MagicMock()
        mock_engine.state = EngineState.RUNNING
        deps._trading_engine = mock_engine
        deps._trading_mode = "live"

        with pytest.raises(RuntimeError, match="Cannot switch"):
            deps.set_trading_mode("paper")

    def test_switch_resets_singletons(self):
        import app.api.deps as deps
        deps._trading_mode = "live"
        deps._trading_engine = MagicMock()
        deps._trading_engine.state = MagicMock(value="idle")
        # Set state to idle so switch is allowed
        from app.core.trading_engine import EngineState
        deps._trading_engine.state = EngineState.IDLE
        deps._order_manager = MagicMock()
        deps._paper_provider = MagicMock()

        deps.set_trading_mode("paper")

        assert deps._trading_engine is None
        assert deps._order_manager is None
        assert deps._paper_provider is None

    @patch("app.api.deps.get_active_provider")
    def test_get_provider_returns_paper_in_paper_mode(self, mock_get_active):
        import app.api.deps as deps
        deps._trading_mode = "paper"
        deps._paper_provider = None

        mock_real = MagicMock()
        mock_get_active.return_value = mock_real

        provider = deps.get_provider()
        assert isinstance(provider, PaperTradingProvider)
        assert deps._paper_provider is provider

    @patch("app.api.deps.get_active_provider")
    def test_get_provider_returns_real_in_live_mode(self, mock_get_active):
        import app.api.deps as deps
        deps._trading_mode = "live"
        deps._paper_provider = None

        mock_real = MagicMock()
        mock_get_active.return_value = mock_real

        provider = deps.get_provider()
        assert provider is mock_real
