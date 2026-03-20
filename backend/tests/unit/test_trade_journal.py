"""
Tests for Trade Journal service and API routes.
"""

from __future__ import annotations

import pytest
from datetime import date, datetime, timedelta
from fastapi.testclient import TestClient

from app.services.trade_journal import TradeJournal, TradeEntry, DailyPnL
from app.main import app
from app.api import deps
from app.api.routes import journal as journal_routes
from app.core.clock import VirtualClock
from app.providers.mock.provider import MockProvider
from app.providers import registry


# ── Trade Journal Unit Tests ────────────────────────────────


class TestTradeJournalBasics:
    @pytest.fixture
    def journal(self):
        return TradeJournal()

    def test_initial_state(self, journal):
        assert journal.get_trade_count() == 0
        assert journal.get_open_trade_count() == 0
        assert journal.get_trades() == []

    def test_record_entry(self, journal):
        trade = journal.record_entry(
            trade_id="T001",
            order_id="O001",
            strategy_id="cpr_RELIANCE",
            trading_symbol="RELIANCE",
            exchange="NSE",
            direction="LONG",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2480.0,
            target=2540.0,
        )
        assert trade.trade_id == "T001"
        assert trade.trading_symbol == "RELIANCE"
        assert trade.direction == "LONG"
        assert trade.entry_price == 2500.0
        assert trade.quantity == 10
        assert not trade.is_closed
        assert journal.get_trade_count() == 1
        assert journal.get_open_trade_count() == 1

    def test_record_exit_computes_pnl(self, journal):
        journal.record_entry(
            trade_id="T001",
            order_id="O001",
            strategy_id="cpr_RELIANCE",
            trading_symbol="RELIANCE",
            exchange="NSE",
            direction="LONG",
            entry_price=2500.0,
            quantity=10,
            stop_loss=2480.0,
            target=2540.0,
        )
        trade = journal.record_exit("T001", exit_price=2540.0, exit_reason="target")
        assert trade is not None
        assert trade.is_closed
        assert trade.pnl == 400.0  # (2540 - 2500) * 10
        assert trade.exit_reason == "target"
        assert journal.get_open_trade_count() == 0

    def test_record_exit_short_pnl(self, journal):
        journal.record_entry(
            trade_id="T002",
            order_id="O002",
            strategy_id="cpr_INFY",
            trading_symbol="INFY",
            exchange="NSE",
            direction="SHORT",
            entry_price=1500.0,
            quantity=5,
        )
        trade = journal.record_exit("T002", exit_price=1480.0, exit_reason="target")
        assert trade is not None
        assert trade.pnl == 100.0  # (1500 - 1480) * 5

    def test_record_exit_loss(self, journal):
        journal.record_entry(
            trade_id="T003",
            order_id="O003",
            strategy_id="cpr_TCS",
            trading_symbol="TCS",
            exchange="NSE",
            direction="LONG",
            entry_price=3500.0,
            quantity=2,
            stop_loss=3480.0,
        )
        trade = journal.record_exit("T003", exit_price=3480.0, exit_reason="stop_loss")
        assert trade is not None
        assert trade.pnl == -40.0  # (3480 - 3500) * 2

    def test_record_exit_nonexistent(self, journal):
        result = journal.record_exit("NONE", exit_price=100.0)
        assert result is None

    def test_pnl_pct_calculation(self, journal):
        journal.record_entry(
            trade_id="T004",
            order_id="O004",
            strategy_id="cpr_HDFC",
            trading_symbol="HDFC",
            exchange="NSE",
            direction="LONG",
            entry_price=1000.0,
            quantity=10,
        )
        trade = journal.record_exit("T004", exit_price=1050.0)
        assert trade is not None
        assert trade.pnl_pct == pytest.approx(5.0)  # 50 / (1000 * 10) * 100 = 0.5%... wait
        # pnl = (1050-1000)*10 = 500, pnl_pct = 500 / (1000*10) * 100 = 5%
        assert trade.pnl == 500.0
        assert trade.pnl_pct == pytest.approx(5.0)

    def test_duration_minutes(self, journal):
        journal.record_entry(
            trade_id="T005",
            order_id="O005",
            strategy_id="cpr_SBIN",
            trading_symbol="SBIN",
            exchange="NSE",
            direction="LONG",
            entry_price=500.0,
            quantity=20,
        )
        trade = journal._trades["T005"]
        trade.entry_time = datetime(2025, 1, 15, 10, 0, 0)

        journal.record_exit("T005", exit_price=510.0)
        # Exit time will be datetime.now(), but we can manually set for testing
        trade.exit_time = datetime(2025, 1, 15, 10, 45, 0)
        assert trade.duration_minutes == 45.0

    def test_reset(self, journal):
        journal.record_entry(
            trade_id="T006", order_id="O006", strategy_id="test",
            trading_symbol="TEST", exchange="NSE", direction="LONG",
            entry_price=100, quantity=1,
        )
        journal.record_exit("T006", exit_price=110)
        assert journal.get_trade_count() == 1

        journal.reset()
        assert journal.get_trade_count() == 0
        assert journal.get_open_trade_count() == 0
        assert journal.get_daily_pnl() == []


class TestTradeJournalQueries:
    @pytest.fixture
    def journal_with_trades(self):
        journal = TradeJournal()
        # Create several trades
        for i, (symbol, direction, entry, exit_p, reason) in enumerate([
            ("RELIANCE", "LONG", 2500.0, 2540.0, "target"),
            ("INFY", "SHORT", 1500.0, 1480.0, "target"),
            ("TCS", "LONG", 3500.0, 3480.0, "stop_loss"),
            ("HDFC", "LONG", 1600.0, None, ""),  # Open trade
        ]):
            journal.record_entry(
                trade_id=f"T{i:03d}",
                order_id=f"O{i:03d}",
                strategy_id=f"cpr_{symbol}",
                trading_symbol=symbol,
                exchange="NSE",
                direction=direction,
                entry_price=entry,
                quantity=10,
                stop_loss=entry * 0.99,
                target=entry * 1.01,
            )
            if exit_p:
                journal.record_exit(f"T{i:03d}", exit_price=exit_p, exit_reason=reason)
        return journal

    def test_get_all_trades(self, journal_with_trades):
        trades = journal_with_trades.get_trades()
        assert len(trades) == 4

    def test_filter_by_symbol(self, journal_with_trades):
        trades = journal_with_trades.get_trades(trading_symbol="RELIANCE")
        assert len(trades) == 1
        assert trades[0].trading_symbol == "RELIANCE"

    def test_filter_closed_only(self, journal_with_trades):
        trades = journal_with_trades.get_trades(only_closed=True)
        assert len(trades) == 3

    def test_filter_by_strategy(self, journal_with_trades):
        trades = journal_with_trades.get_trades(strategy_id="cpr_INFY")
        assert len(trades) == 1

    def test_trade_count(self, journal_with_trades):
        assert journal_with_trades.get_trade_count() == 4
        assert journal_with_trades.get_open_trade_count() == 1


class TestDailyPnL:
    @pytest.fixture
    def journal(self):
        j = TradeJournal()
        # Record 3 closed trades
        for i, (pnl_direction, entry, exit_p) in enumerate([
            ("LONG", 100.0, 110.0),   # +100
            ("LONG", 200.0, 195.0),   # -50
            ("SHORT", 300.0, 290.0),  # +100
        ]):
            j.record_entry(
                trade_id=f"T{i}",
                order_id=f"O{i}",
                strategy_id="test",
                trading_symbol="TEST",
                exchange="NSE",
                direction=pnl_direction,
                entry_price=entry,
                quantity=10,
            )
            j.record_exit(f"T{i}", exit_price=exit_p)
        return j

    def test_today_pnl(self, journal):
        today = journal.get_today_pnl()
        assert today.total_trades == 3
        assert today.winning_trades == 2
        assert today.losing_trades == 1
        assert today.realized_pnl == pytest.approx(150.0)
        # Win rate: 2/3 = 66.7%
        assert today.win_rate == pytest.approx(66.7, abs=0.1)

    def test_daily_pnl_list(self, journal):
        daily = journal.get_daily_pnl()
        assert len(daily) == 1
        assert daily[0].date == date.today()

    def test_largest_win_loss(self, journal):
        today = journal.get_today_pnl()
        assert today.largest_win == 100.0
        assert today.largest_loss == -50.0


class TestPerformanceSummary:
    @pytest.fixture
    def journal(self):
        j = TradeJournal()
        # Record 5 trades: 3 wins, 2 losses
        trades = [
            ("LONG", 100.0, 110.0),    # +100
            ("LONG", 200.0, 195.0),    # -50
            ("SHORT", 300.0, 290.0),   # +100
            ("LONG", 150.0, 160.0),    # +100
            ("SHORT", 250.0, 260.0),   # -100
        ]
        for i, (direction, entry, exit_p) in enumerate(trades):
            j.record_entry(
                trade_id=f"T{i}",
                order_id=f"O{i}",
                strategy_id="test",
                trading_symbol="TEST",
                exchange="NSE",
                direction=direction,
                entry_price=entry,
                quantity=10,
            )
            j.record_exit(f"T{i}", exit_price=exit_p)
        return j

    def test_performance_totals(self, journal):
        perf = journal.get_performance_summary()
        assert perf.total_trades == 5
        assert perf.winning_trades == 3
        assert perf.losing_trades == 2
        assert perf.total_pnl == pytest.approx(150.0)

    def test_win_rate(self, journal):
        perf = journal.get_performance_summary()
        assert perf.win_rate == pytest.approx(60.0)

    def test_profit_factor(self, journal):
        perf = journal.get_performance_summary()
        # Gross profit = 300, gross loss = 150
        assert perf.profit_factor == pytest.approx(2.0)

    def test_avg_trade_pnl(self, journal):
        perf = journal.get_performance_summary()
        assert perf.avg_trade_pnl == pytest.approx(30.0)

    def test_max_drawdown(self, journal):
        perf = journal.get_performance_summary()
        assert perf.max_drawdown >= 0

    def test_empty_journal_performance(self):
        j = TradeJournal()
        perf = j.get_performance_summary()
        assert perf.total_trades == 0
        assert perf.win_rate == 0.0
        assert perf.total_pnl == 0.0


class TestRiskRewardActual:
    def test_positive_rr(self):
        t = TradeEntry(
            trade_id="T1", order_id="O1", strategy_id="s1",
            trading_symbol="TEST", exchange="NSE", direction="LONG",
            entry_price=100.0, exit_price=110.0, quantity=10,
            stop_loss=95.0, pnl=100.0,
        )
        # risk = 5, reward = 10, R:R = 2.0
        assert t.risk_reward_actual == pytest.approx(2.0)

    def test_negative_rr_on_loss(self):
        t = TradeEntry(
            trade_id="T2", order_id="O2", strategy_id="s2",
            trading_symbol="TEST", exchange="NSE", direction="LONG",
            entry_price=100.0, exit_price=95.0, quantity=10,
            stop_loss=95.0, pnl=-50.0,
        )
        # risk = 5, reward = 5, R:R = -1.0
        assert t.risk_reward_actual == pytest.approx(-1.0)

    def test_no_sl_returns_none(self):
        t = TradeEntry(
            trade_id="T3", order_id="O3", strategy_id="s3",
            trading_symbol="TEST", exchange="NSE", direction="LONG",
            entry_price=100.0, exit_price=110.0, quantity=10,
        )
        assert t.risk_reward_actual is None


# ── API Route Tests ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_registry():
    registry.clear_registry()
    yield
    registry.clear_registry()


@pytest.fixture
def mock_provider():
    clock = VirtualClock()
    mp = MockProvider(capital=1_000_000, clock=clock)
    mp.engine.register_instrument("NSE", "RELIANCE", 256265)
    return mp


@pytest.fixture
def client(mock_provider, risk_manager, config_manager):
    app.dependency_overrides[deps.get_provider] = lambda: mock_provider
    app.dependency_overrides[deps.get_risk_manager] = lambda: risk_manager
    app.dependency_overrides[deps.get_config_manager] = lambda: config_manager

    # Reset journal singleton in deps.py
    deps._journal = TradeJournal()

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    deps._journal = None


class TestJournalTradesRoute:
    def test_get_trades_empty(self, client):
        resp = client.get("/api/journal/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trades"] == []
        assert data["total"] == 0

    def test_get_trades_after_recording(self, client):
        # Record a trade via the journal singleton
        journal = journal_routes.get_journal()
        journal.record_entry(
            trade_id="T001", order_id="O001", strategy_id="cpr_REL",
            trading_symbol="RELIANCE", exchange="NSE", direction="LONG",
            entry_price=2500.0, quantity=10, stop_loss=2480.0, target=2540.0,
        )
        resp = client.get("/api/journal/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["trades"][0]["trading_symbol"] == "RELIANCE"
        assert data["trades"][0]["is_open"] is True

    def test_get_trades_filter_symbol(self, client):
        journal = journal_routes.get_journal()
        journal.record_entry(
            trade_id="T001", order_id="O001", strategy_id="cpr_REL",
            trading_symbol="RELIANCE", exchange="NSE", direction="LONG",
            entry_price=2500.0, quantity=10,
        )
        journal.record_entry(
            trade_id="T002", order_id="O002", strategy_id="cpr_INFY",
            trading_symbol="INFY", exchange="NSE", direction="SHORT",
            entry_price=1500.0, quantity=5,
        )
        resp = client.get("/api/journal/trades?symbol=RELIANCE")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_trades_filter_closed(self, client):
        journal = journal_routes.get_journal()
        journal.record_entry(
            trade_id="T001", order_id="O001", strategy_id="cpr_REL",
            trading_symbol="RELIANCE", exchange="NSE", direction="LONG",
            entry_price=2500.0, quantity=10,
        )
        journal.record_exit("T001", exit_price=2540.0, exit_reason="target")

        journal.record_entry(
            trade_id="T002", order_id="O002", strategy_id="cpr_INFY",
            trading_symbol="INFY", exchange="NSE", direction="SHORT",
            entry_price=1500.0, quantity=5,
        )

        resp = client.get("/api/journal/trades?closed_only=true")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["trades"][0]["exit_reason"] == "target"

    def test_get_trades_limit(self, client):
        journal = journal_routes.get_journal()
        for i in range(10):
            journal.record_entry(
                trade_id=f"T{i:03d}", order_id=f"O{i:03d}", strategy_id="test",
                trading_symbol="TEST", exchange="NSE", direction="LONG",
                entry_price=100.0, quantity=1,
            )
        resp = client.get("/api/journal/trades?limit=3")
        assert resp.status_code == 200
        assert resp.json()["returned"] == 3
        assert resp.json()["total"] == 10


class TestJournalSingleTrade:
    def test_get_trade_by_id(self, client):
        journal = journal_routes.get_journal()
        journal.record_entry(
            trade_id="T001", order_id="O001", strategy_id="cpr_REL",
            trading_symbol="RELIANCE", exchange="NSE", direction="LONG",
            entry_price=2500.0, quantity=10,
        )
        resp = client.get("/api/journal/trades/T001")
        assert resp.status_code == 200
        assert resp.json()["trade_id"] == "T001"

    def test_get_trade_not_found(self, client):
        resp = client.get("/api/journal/trades/NONEXISTENT")
        assert resp.status_code == 404


class TestDailyPnLRoute:
    def test_daily_pnl_empty(self, client):
        resp = client.get("/api/journal/daily-pnl")
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily_pnl"] == []
        assert data["cumulative_pnl"] == 0.0

    def test_daily_pnl_after_trades(self, client):
        journal = journal_routes.get_journal()
        journal.record_entry(
            trade_id="T001", order_id="O001", strategy_id="test",
            trading_symbol="RELIANCE", exchange="NSE", direction="LONG",
            entry_price=2500.0, quantity=10,
        )
        journal.record_exit("T001", exit_price=2540.0, exit_reason="target")

        resp = client.get("/api/journal/daily-pnl")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_days"] == 1
        assert data["cumulative_pnl"] == 400.0

    def test_today_pnl(self, client):
        journal = journal_routes.get_journal()
        journal.record_entry(
            trade_id="T001", order_id="O001", strategy_id="test",
            trading_symbol="TEST", exchange="NSE", direction="LONG",
            entry_price=100.0, quantity=10,
        )
        journal.record_exit("T001", exit_price=110.0)

        resp = client.get("/api/journal/daily-pnl/today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 1
        assert data["realized_pnl"] == 100.0


class TestPerformanceRoute:
    def test_performance_empty(self, client):
        resp = client.get("/api/journal/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0

    def test_performance_after_trades(self, client):
        journal = journal_routes.get_journal()
        # 2 wins, 1 loss
        for i, (entry, exit_p) in enumerate([(100, 110), (200, 195), (150, 160)]):
            journal.record_entry(
                trade_id=f"T{i}", order_id=f"O{i}", strategy_id="test",
                trading_symbol="TEST", exchange="NSE", direction="LONG",
                entry_price=float(entry), quantity=10,
            )
            journal.record_exit(f"T{i}", exit_price=float(exit_p))

        resp = client.get("/api/journal/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 3
        assert data["winning_trades"] == 2
        assert data["losing_trades"] == 1


class TestSessionRoute:
    def test_session_summary(self, client):
        resp = client.get("/api/journal/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data
        assert "is_paper" in data
        assert "engine_state" in data
        assert "total_trades" in data
        assert "today_pnl" in data
        assert "performance" in data


class TestResetRoute:
    def test_reset_journal(self, client):
        journal = journal_routes.get_journal()
        journal.record_entry(
            trade_id="T001", order_id="O001", strategy_id="test",
            trading_symbol="TEST", exchange="NSE", direction="LONG",
            entry_price=100.0, quantity=10,
        )
        assert journal.get_trade_count() == 1

        resp = client.post("/api/journal/reset")
        assert resp.status_code == 200
        assert resp.json()["trades"] == 0

        # Verify journal is empty
        resp = client.get("/api/journal/trades")
        assert resp.json()["total"] == 0


# ── Engine-Journal Integration Tests ─────────────────────────


class TestEngineJournalIntegration:
    """Tests that the trading engine correctly records entries and exits in the journal."""

    @pytest.fixture
    def journal(self):
        return TradeJournal()

    @pytest.fixture
    def mock_prov(self):
        clock = VirtualClock()
        mp = MockProvider(capital=1_000_000, clock=clock)
        mp.engine.register_instrument("NSE", "RELIANCE", 256265)
        mp.engine.register_instrument("NSE", "INFY", 408065)
        return mp

    @pytest.fixture
    def engine(self, mock_prov, journal):
        from unittest.mock import patch
        from app.core.risk_manager import RiskManager, RiskCheckResult
        from app.core.order_manager import OrderManager
        from app.core.trading_engine import TradingEngine

        risk = RiskManager()
        # Always approve orders so tests work outside market hours
        risk.check_order = lambda request, price, open_orders=0, open_positions=0: RiskCheckResult(passed=True)
        order_mgr = OrderManager(provider=mock_prov, risk_manager=risk)
        eng = TradingEngine(
            provider=mock_prov,
            risk_manager=risk,
            order_manager=order_mgr,
            journal=journal,
        )
        return eng

    def test_engine_has_journal(self, engine, journal):
        """Engine stores the journal reference."""
        assert engine._journal is journal

    def test_engine_without_journal(self, mock_prov):
        """Engine works fine without journal (backward compat)."""
        from app.core.risk_manager import RiskManager
        from app.core.order_manager import OrderManager
        from app.core.trading_engine import TradingEngine

        risk = RiskManager()
        order_mgr = OrderManager(provider=mock_prov, risk_manager=risk)
        eng = TradingEngine(
            provider=mock_prov,
            risk_manager=risk,
            order_manager=order_mgr,
        )
        assert eng._journal is None
        assert eng._active_trades == {}

    async def test_journal_record_entry_on_buy_signal(self, engine, journal):
        """When engine processes a BUY signal, journal records an entry."""
        from app.core.trading_engine import StockPick, EngineState
        from app.strategies.cpr_breakout import CPRLevels
        from app.strategies.base import StrategySignal, StrategyState
        from app.providers.types import (
            OrderRequest, Exchange, TransactionType, OrderType,
            ProductType, Variety, Validity,
        )

        # Load a pick
        cpr = CPRLevels(pivot=2500, tc=2505, bc=2495, width=10, width_pct=0.2)
        pick = StockPick(
            trading_symbol="RELIANCE",
            instrument_token=256265,
            exchange="NSE",
            cpr=cpr,
            direction="LONG",
            today_open=2510.0,
            prev_close=2500.0,
            quantity=10,
        )
        engine.load_picks([pick])

        # Simulate: inject a BUY signal directly into the strategy
        strategy = engine._strategies[256265]
        strategy.state = StrategyState.RUNNING
        strategy._signals.append(StrategySignal(
            instrument_token=256265,
            trading_symbol="RELIANCE",
            action="BUY",
            reason="CPR breakout LONG",
            metadata={
                "entry_price": 2510.0,
                "stop_loss": 2495.0,
                "target": 2540.0,
            },
            order_request=OrderRequest(
                tradingsymbol="RELIANCE",
                exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY,
                order_type=OrderType.MARKET,
                quantity=10,
                product=ProductType.MIS,
                variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))

        engine.state = EngineState.RUNNING
        await engine._process_all_signals()

        # Check journal has an entry
        trades = journal.get_trades()
        assert len(trades) == 1
        t = trades[0]
        assert t.trading_symbol == "RELIANCE"
        assert t.direction == "LONG"
        assert t.entry_price == 2510.0
        assert t.stop_loss == 2495.0
        assert t.target == 2540.0
        assert t.quantity == 10
        assert t.is_closed is False

        # Check active_trades tracking
        sid = strategy.strategy_id
        assert sid in engine._active_trades
        assert engine._active_trades[sid] == t.trade_id

    async def test_journal_record_exit_on_sell_signal(self, engine, journal):
        """When engine processes an exit signal, journal records the exit with P&L."""
        from app.core.trading_engine import StockPick, EngineState
        from app.strategies.cpr_breakout import CPRLevels
        from app.strategies.base import StrategySignal, StrategyState
        from app.providers.types import (
            OrderRequest, Exchange, TransactionType, OrderType,
            ProductType, Variety, Validity,
        )

        cpr = CPRLevels(pivot=2500, tc=2505, bc=2495, width=10, width_pct=0.2)
        pick = StockPick(
            trading_symbol="RELIANCE",
            instrument_token=256265,
            exchange="NSE",
            cpr=cpr,
            direction="LONG",
            today_open=2510.0,
            prev_close=2500.0,
            quantity=10,
        )
        engine.load_picks([pick])
        strategy = engine._strategies[256265]
        strategy.state = StrategyState.RUNNING
        engine.state = EngineState.RUNNING

        # Step 1: Entry signal
        strategy._signals.append(StrategySignal(
            instrument_token=256265,
            trading_symbol="RELIANCE",
            action="BUY",
            reason="CPR breakout LONG",
            metadata={"entry_price": 2510.0, "stop_loss": 2495.0, "target": 2540.0},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        # Verify entry recorded
        assert journal.get_trade_count() == 1
        assert journal.get_open_trade_count() == 1

        # Step 2: Exit signal (target hit)
        strategy._signals.append(StrategySignal(
            instrument_token=256265,
            trading_symbol="RELIANCE",
            action="SELL",
            reason="Target hit at 2540.00",
            metadata={
                "exit_price": 2540.0,
                "entry_price": 2510.0,
                "stop_loss": 2495.0,
                "target": 2540.0,
            },
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.SELL, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        # Verify exit recorded
        assert journal.get_trade_count() == 1
        assert journal.get_open_trade_count() == 0
        t = journal.get_trades()[0]
        assert t.is_closed is True
        assert t.exit_price == 2540.0
        assert t.exit_reason == "target"
        assert t.pnl == pytest.approx(300.0)  # (2540 - 2510) * 10
        assert t.pnl_pct > 0

        # active_trades should be cleared
        assert strategy.strategy_id not in engine._active_trades

        # session_pnl should be updated
        assert engine._session_pnl == pytest.approx(300.0)

    async def test_journal_exit_sl_reason(self, engine, journal):
        """Exit reason is correctly classified as stop_loss."""
        from app.core.trading_engine import StockPick, EngineState
        from app.strategies.cpr_breakout import CPRLevels
        from app.strategies.base import StrategySignal, StrategyState
        from app.providers.types import (
            OrderRequest, Exchange, TransactionType, OrderType,
            ProductType, Variety, Validity,
        )

        cpr = CPRLevels(pivot=2500, tc=2505, bc=2495, width=10, width_pct=0.2)
        pick = StockPick(
            trading_symbol="RELIANCE", instrument_token=256265, exchange="NSE",
            cpr=cpr, direction="LONG", today_open=2510.0, prev_close=2500.0, quantity=10,
        )
        engine.load_picks([pick])
        strategy = engine._strategies[256265]
        strategy.state = StrategyState.RUNNING
        engine.state = EngineState.RUNNING

        # Entry
        strategy._signals.append(StrategySignal(
            instrument_token=256265, trading_symbol="RELIANCE", action="BUY",
            reason="CPR breakout LONG",
            metadata={"entry_price": 2510.0, "stop_loss": 2495.0, "target": 2540.0},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        # Exit with SL hit
        strategy._signals.append(StrategySignal(
            instrument_token=256265, trading_symbol="RELIANCE", action="SELL",
            reason="Tick SL hit at 2495.00 (SL=2495.00)",
            metadata={"exit_price": 2495.0, "entry_price": 2510.0, "stop_loss": 2495.0, "target": 2540.0, "exit_source": "tick"},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.SELL, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        t = journal.get_trades()[0]
        assert t.exit_reason == "stop_loss"
        assert t.pnl == pytest.approx(-150.0)  # (2495 - 2510) * 10

    async def test_journal_exit_eod_reason(self, engine, journal):
        """Exit reason is correctly classified as eod_close."""
        from app.core.trading_engine import StockPick, EngineState
        from app.strategies.cpr_breakout import CPRLevels
        from app.strategies.base import StrategySignal, StrategyState
        from app.providers.types import (
            OrderRequest, Exchange, TransactionType, OrderType,
            ProductType, Variety, Validity,
        )

        cpr = CPRLevels(pivot=2500, tc=2505, bc=2495, width=10, width_pct=0.2)
        pick = StockPick(
            trading_symbol="RELIANCE", instrument_token=256265, exchange="NSE",
            cpr=cpr, direction="LONG", today_open=2510.0, prev_close=2500.0, quantity=10,
        )
        engine.load_picks([pick])
        strategy = engine._strategies[256265]
        strategy.state = StrategyState.RUNNING
        engine.state = EngineState.RUNNING

        # Entry
        strategy._signals.append(StrategySignal(
            instrument_token=256265, trading_symbol="RELIANCE", action="BUY",
            reason="CPR breakout LONG",
            metadata={"entry_price": 2510.0, "stop_loss": 2495.0, "target": 2540.0},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        # Exit with EOD auto-close
        strategy._signals.append(StrategySignal(
            instrument_token=256265, trading_symbol="RELIANCE", action="SELL",
            reason="End of day auto-close",
            metadata={"exit_price": 2520.0, "entry_price": 2510.0},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.SELL, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        t = journal.get_trades()[0]
        assert t.exit_reason == "eod_close"

    async def test_journal_short_trade(self, engine, journal):
        """Short trade entry and exit are recorded correctly."""
        from app.core.trading_engine import StockPick, EngineState
        from app.strategies.cpr_breakout import CPRLevels
        from app.strategies.base import StrategySignal, StrategyState
        from app.providers.types import (
            OrderRequest, Exchange, TransactionType, OrderType,
            ProductType, Variety, Validity,
        )

        cpr = CPRLevels(pivot=2500, tc=2505, bc=2495, width=10, width_pct=0.2)
        pick = StockPick(
            trading_symbol="INFY", instrument_token=408065, exchange="NSE",
            cpr=cpr, direction="SHORT", today_open=2490.0, prev_close=2500.0, quantity=5,
        )
        engine.load_picks([pick])
        strategy = engine._strategies[408065]
        strategy.state = StrategyState.RUNNING
        engine.state = EngineState.RUNNING

        # Entry (SHORT = SELL action)
        strategy._signals.append(StrategySignal(
            instrument_token=408065, trading_symbol="INFY", action="SELL",
            reason="CPR breakout SHORT",
            metadata={"entry_price": 2490.0, "stop_loss": 2505.0, "target": 2460.0},
            order_request=OrderRequest(
                tradingsymbol="INFY", exchange=Exchange.NSE,
                transaction_type=TransactionType.SELL, order_type=OrderType.MARKET,
                quantity=5, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        t = journal.get_trades()[0]
        assert t.direction == "SHORT"
        assert t.entry_price == 2490.0

        # Exit (BUY to close short — target hit)
        strategy._signals.append(StrategySignal(
            instrument_token=408065, trading_symbol="INFY", action="BUY",
            reason="Tick target hit at 2460.00 (target=2460.00)",
            metadata={"exit_price": 2460.0, "entry_price": 2490.0, "stop_loss": 2505.0, "target": 2460.0},
            order_request=OrderRequest(
                tradingsymbol="INFY", exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY, order_type=OrderType.MARKET,
                quantity=5, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        t = journal.get_trades()[0]
        assert t.is_closed is True
        assert t.pnl == pytest.approx(150.0)  # (2490 - 2460) * 5
        assert t.exit_reason == "target"

    async def test_journal_paper_mode_flag(self, journal):
        """Paper mode flag is correctly set on journal entries."""
        from app.core.risk_manager import RiskManager, RiskCheckResult
        from app.core.order_manager import OrderManager
        from app.core.trading_engine import TradingEngine, StockPick, EngineState
        from app.strategies.cpr_breakout import CPRLevels
        from app.strategies.base import StrategySignal, StrategyState
        from app.providers.types import (
            OrderRequest, Exchange, TransactionType, OrderType,
            ProductType, Variety, Validity,
        )

        # Create a mock provider with is_paper = True
        clock = VirtualClock()
        prov = MockProvider(capital=1_000_000, clock=clock)
        prov.engine.register_instrument("NSE", "RELIANCE", 256265)
        prov.is_paper = True  # type: ignore[attr-defined]

        risk = RiskManager()
        risk.check_order = lambda request, price, open_orders=0, open_positions=0: RiskCheckResult(passed=True)
        order_mgr = OrderManager(provider=prov, risk_manager=risk)
        eng = TradingEngine(provider=prov, risk_manager=risk, order_manager=order_mgr, journal=journal)

        cpr = CPRLevels(pivot=2500, tc=2505, bc=2495, width=10, width_pct=0.2)
        pick = StockPick(
            trading_symbol="RELIANCE", instrument_token=256265, exchange="NSE",
            cpr=cpr, direction="LONG", today_open=2510.0, prev_close=2500.0, quantity=10,
        )
        eng.load_picks([pick])
        strategy = eng._strategies[256265]
        strategy.state = StrategyState.RUNNING
        eng.state = EngineState.RUNNING

        strategy._signals.append(StrategySignal(
            instrument_token=256265, trading_symbol="RELIANCE", action="BUY",
            reason="CPR breakout LONG",
            metadata={"entry_price": 2510.0, "stop_loss": 2495.0, "target": 2540.0},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await eng._process_all_signals()

        t = journal.get_trades()[0]
        assert t.is_paper is True

    async def test_engine_stop_closes_orphan_trades(self, engine, journal):
        """When engine stops, any still-open journal trades are closed."""
        from app.core.trading_engine import StockPick, EngineState
        from app.strategies.cpr_breakout import CPRLevels
        from app.strategies.base import StrategySignal, StrategyState
        from app.providers.types import (
            OrderRequest, Exchange, TransactionType, OrderType,
            ProductType, Variety, Validity,
        )
        import asyncio

        cpr = CPRLevels(pivot=2500, tc=2505, bc=2495, width=10, width_pct=0.2)
        pick = StockPick(
            trading_symbol="RELIANCE", instrument_token=256265, exchange="NSE",
            cpr=cpr, direction="LONG", today_open=2510.0, prev_close=2500.0, quantity=10,
        )
        engine.load_picks([pick])
        strategy = engine._strategies[256265]
        strategy.state = StrategyState.RUNNING
        engine.state = EngineState.RUNNING
        engine._loop = asyncio.get_running_loop()

        # Entry
        strategy._signals.append(StrategySignal(
            instrument_token=256265, trading_symbol="RELIANCE", action="BUY",
            reason="CPR breakout LONG",
            metadata={"entry_price": 2510.0, "stop_loss": 2495.0, "target": 2540.0},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await engine._process_all_signals()

        # Verify trade is open
        assert journal.get_open_trade_count() == 1

        # Stop engine (without an exit signal)
        await engine.stop()

        # Orphan trade should be closed with engine_stop reason
        assert journal.get_open_trade_count() == 0
        t = journal.get_trades()[0]
        assert t.is_closed is True
        assert t.exit_reason == "engine_stop"

    async def test_multiple_strategies_independent_tracking(self, journal):
        """Each strategy's trades are tracked independently."""
        from app.core.risk_manager import RiskManager, RiskCheckResult
        from app.core.order_manager import OrderManager
        from app.core.trading_engine import TradingEngine, StockPick, EngineState
        from app.strategies.cpr_breakout import CPRLevels
        from app.strategies.base import StrategySignal, StrategyState
        from app.providers.types import (
            OrderRequest, Exchange, TransactionType, OrderType,
            ProductType, Variety, Validity,
        )

        clock = VirtualClock()
        prov = MockProvider(capital=1_000_000, clock=clock)
        prov.engine.register_instrument("NSE", "RELIANCE", 256265)
        prov.engine.register_instrument("NSE", "INFY", 408065)

        risk = RiskManager()
        risk.check_order = lambda request, price, open_orders=0, open_positions=0: RiskCheckResult(passed=True)
        order_mgr = OrderManager(provider=prov, risk_manager=risk)
        eng = TradingEngine(provider=prov, risk_manager=risk, order_manager=order_mgr, journal=journal)

        cpr = CPRLevels(pivot=2500, tc=2505, bc=2495, width=10, width_pct=0.2)
        picks = [
            StockPick(
                trading_symbol="RELIANCE", instrument_token=256265, exchange="NSE",
                cpr=cpr, direction="LONG", today_open=2510.0, prev_close=2500.0, quantity=10,
            ),
            StockPick(
                trading_symbol="INFY", instrument_token=408065, exchange="NSE",
                cpr=cpr, direction="SHORT", today_open=2490.0, prev_close=2500.0, quantity=5,
            ),
        ]
        eng.load_picks(picks)
        eng.state = EngineState.RUNNING

        for strategy in eng._strategies.values():
            strategy.state = StrategyState.RUNNING

        # Entry for RELIANCE (LONG)
        eng._strategies[256265]._signals.append(StrategySignal(
            instrument_token=256265, trading_symbol="RELIANCE", action="BUY",
            reason="CPR breakout LONG",
            metadata={"entry_price": 2510.0, "stop_loss": 2495.0, "target": 2540.0},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))

        # Entry for INFY (SHORT)
        eng._strategies[408065]._signals.append(StrategySignal(
            instrument_token=408065, trading_symbol="INFY", action="SELL",
            reason="CPR breakout SHORT",
            metadata={"entry_price": 2490.0, "stop_loss": 2505.0, "target": 2460.0},
            order_request=OrderRequest(
                tradingsymbol="INFY", exchange=Exchange.NSE,
                transaction_type=TransactionType.SELL, order_type=OrderType.MARKET,
                quantity=5, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))

        await eng._process_all_signals()

        # Both entries recorded
        assert journal.get_trade_count() == 2
        assert journal.get_open_trade_count() == 2
        assert len(eng._active_trades) == 2

        # Exit RELIANCE only
        eng._strategies[256265]._signals.append(StrategySignal(
            instrument_token=256265, trading_symbol="RELIANCE", action="SELL",
            reason="Target hit at 2540.00",
            metadata={"exit_price": 2540.0, "entry_price": 2510.0, "stop_loss": 2495.0, "target": 2540.0},
            order_request=OrderRequest(
                tradingsymbol="RELIANCE", exchange=Exchange.NSE,
                transaction_type=TransactionType.SELL, order_type=OrderType.MARKET,
                quantity=10, product=ProductType.MIS, variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))
        await eng._process_all_signals()

        # Only RELIANCE closed, INFY still open
        assert journal.get_open_trade_count() == 1
        assert len(eng._active_trades) == 1

        rel_trades = journal.get_trades(trading_symbol="RELIANCE")
        assert len(rel_trades) == 1
        assert rel_trades[0].is_closed is True
        assert rel_trades[0].pnl == pytest.approx(300.0)

        infy_trades = journal.get_trades(trading_symbol="INFY")
        assert len(infy_trades) == 1
        assert infy_trades[0].is_closed is False
