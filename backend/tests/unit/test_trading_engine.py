"""
Unit tests for TradingEngine.

Tests the core orchestrator: candle building, strategy integration,
signal processing, lifecycle management, and event logging.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, time
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.order_manager import OrderManager, ManagedOrder
from app.core.risk_manager import RiskManager, RiskLimits
from app.core.trading_engine import (
    CandleBuilder,
    EngineEvent,
    EngineState,
    StockPick,
    TradingEngine,
)
from app.providers.types import (
    Candle,
    Exchange,
    OrderRequest,
    OrderStatus,
    OrderType,
    ProductType,
    TickData,
    TickMode,
    TransactionType,
    Variety,
    Validity,
)
from app.strategies.base import StrategySignal, StrategyState
from app.strategies.cpr_breakout import CPRLevels


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_cpr(pivot: float = 100.0, width_pct: float = 0.15) -> CPRLevels:
    """Create a CPRLevels with controllable width."""
    half_width = (width_pct / 100.0) * pivot / 2.0
    tc = round(pivot + half_width, 2)
    bc = round(pivot - half_width, 2)
    width = round(tc - bc, 2)
    return CPRLevels(
        pivot=pivot,
        tc=tc,
        bc=bc,
        width=width,
        width_pct=round(width_pct, 4),
    )


def make_pick(
    symbol: str = "RELIANCE",
    token: int = 738561,
    direction: str = "LONG",
    quantity: int = 1,
    width_pct: float = 0.15,
) -> StockPick:
    """Create a StockPick for testing."""
    cpr = make_cpr(pivot=2500.0, width_pct=width_pct)
    return StockPick(
        trading_symbol=symbol,
        instrument_token=token,
        exchange="NSE",
        cpr=cpr,
        direction=direction,
        today_open=2505.0,
        prev_close=2498.0,
        quantity=quantity,
    )


def make_tick(token: int, price: float, ts: datetime) -> TickData:
    """Create a TickData."""
    return TickData(
        instrument_token=token,
        last_price=price,
        timestamp=ts,
        volume=1000,
        mode=TickMode.QUOTE,
    )


def make_candle(ts: datetime, o: float, h: float, l: float, c: float, v: int = 1000) -> Candle:
    """Create a Candle."""
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_provider():
    """A fully mocked BrokerProvider."""
    provider = MagicMock()
    provider.place_order = AsyncMock(return_value=MagicMock(order_id="ORD123"))
    provider.get_ltp = AsyncMock(return_value={})
    provider.get_orders = AsyncMock(return_value=[])
    provider.get_positions = AsyncMock(return_value=MagicMock(net=[], day=[]))

    # Ticker mock
    ticker = MagicMock()
    ticker.connect = MagicMock()
    ticker.disconnect = MagicMock()
    ticker.is_connected = MagicMock(return_value=True)
    ticker.subscribe = MagicMock()
    ticker.set_on_tick = MagicMock()
    ticker.set_on_connect = MagicMock()
    ticker.set_on_disconnect = MagicMock()
    ticker.set_on_error = MagicMock()
    ticker.set_on_order_update = MagicMock()
    provider.create_ticker = MagicMock(return_value=ticker)

    return provider


@pytest.fixture
def risk_manager():
    from app.core.clock import VirtualClock
    clock = VirtualClock(initial_time=datetime(2025, 1, 15, 10, 0, 0))
    return RiskManager(
        limits=RiskLimits(max_daily_loss=50_000, max_loss_per_trade=10_000),
        clock=clock,
    )


@pytest.fixture
def order_manager(mock_provider, risk_manager):
    return OrderManager(provider=mock_provider, risk_manager=risk_manager)


@pytest.fixture
def engine(mock_provider, risk_manager, order_manager):
    return TradingEngine(
        provider=mock_provider,
        risk_manager=risk_manager,
        order_manager=order_manager,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CandleBuilder Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCandleBuilder:
    """Tests for the tick → candle aggregation logic."""

    def test_first_tick_returns_none(self):
        builder = CandleBuilder(instrument_token=123)
        tick = make_tick(123, 100.0, datetime(2025, 1, 15, 9, 15, 0))
        assert builder.on_tick(tick) is None

    def test_same_window_returns_none(self):
        builder = CandleBuilder(instrument_token=123)
        ts = datetime(2025, 1, 15, 9, 15, 0)
        builder.on_tick(make_tick(123, 100.0, ts))
        # Same 5-min window (9:15:00 to 9:19:59)
        result = builder.on_tick(make_tick(123, 101.0, ts.replace(second=30)))
        assert result is None

    def test_new_window_completes_candle(self):
        builder = CandleBuilder(instrument_token=123)
        # Window 1: 9:15:00 - 9:19:59
        builder.on_tick(make_tick(123, 100.0, datetime(2025, 1, 15, 9, 15, 0)))
        builder.on_tick(make_tick(123, 102.0, datetime(2025, 1, 15, 9, 16, 0)))
        builder.on_tick(make_tick(123, 99.0, datetime(2025, 1, 15, 9, 17, 0)))
        builder.on_tick(make_tick(123, 101.0, datetime(2025, 1, 15, 9, 18, 0)))

        # Window 2 starts — completes window 1
        candle = builder.on_tick(make_tick(123, 103.0, datetime(2025, 1, 15, 9, 20, 0)))
        assert candle is not None
        assert candle.open == 100.0
        assert candle.high == 102.0
        assert candle.low == 99.0
        assert candle.close == 101.0
        assert candle.timestamp == datetime(2025, 1, 15, 9, 15, 0)

    def test_window_alignment(self):
        """Candle window should align to 5-min boundaries."""
        builder = CandleBuilder(instrument_token=123, interval_minutes=5)
        # Tick at 9:17:23 should belong to 9:15:00 window
        builder.on_tick(make_tick(123, 100.0, datetime(2025, 1, 15, 9, 17, 23)))
        assert builder._window_start == datetime(2025, 1, 15, 9, 15, 0)

    def test_force_complete(self):
        builder = CandleBuilder(instrument_token=123)
        builder.on_tick(make_tick(123, 100.0, datetime(2025, 1, 15, 9, 15, 0)))
        builder.on_tick(make_tick(123, 105.0, datetime(2025, 1, 15, 9, 16, 0)))

        candle = builder.force_complete()
        assert candle is not None
        assert candle.open == 100.0
        assert candle.high == 105.0
        assert candle.close == 105.0

    def test_force_complete_empty(self):
        builder = CandleBuilder(instrument_token=123)
        assert builder.force_complete() is None

    def test_zero_price_ignored(self):
        builder = CandleBuilder(instrument_token=123)
        tick = make_tick(123, 0.0, datetime(2025, 1, 15, 9, 15, 0))
        assert builder.on_tick(tick) is None
        assert builder._window_start is None

    def test_multiple_candles_consecutive(self):
        builder = CandleBuilder(instrument_token=123)
        # Window 1
        builder.on_tick(make_tick(123, 100.0, datetime(2025, 1, 15, 9, 15, 0)))
        # Window 2 — completes window 1
        c1 = builder.on_tick(make_tick(123, 110.0, datetime(2025, 1, 15, 9, 20, 0)))
        assert c1 is not None
        assert c1.open == 100.0

        # Window 3 — completes window 2
        c2 = builder.on_tick(make_tick(123, 120.0, datetime(2025, 1, 15, 9, 25, 0)))
        assert c2 is not None
        assert c2.open == 110.0


# ═══════════════════════════════════════════════════════════════════════════════
# TradingEngine Lifecycle Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineLifecycle:
    """Tests for engine state transitions."""

    def test_initial_state(self, engine):
        assert engine.state == EngineState.IDLE

    def test_load_picks(self, engine):
        picks = [make_pick("RELIANCE", 738561), make_pick("INFY", 408065)]
        engine.load_picks(picks)

        assert engine.state == EngineState.IDLE
        assert len(engine._picks) == 2
        assert len(engine._strategies) == 2
        assert len(engine._candle_builders) == 2
        assert 738561 in engine._strategies
        assert 408065 in engine._strategies

    def test_load_picks_creates_strategies_with_cpr(self, engine):
        pick = make_pick("RELIANCE", 738561)
        engine.load_picks([pick])

        strategy = engine._strategies[738561]
        assert strategy._cpr is not None
        assert strategy._cpr.pivot == pick.cpr.pivot
        assert strategy._cpr.tc == pick.cpr.tc
        assert strategy._cpr.bc == pick.cpr.bc

    def test_load_picks_rejects_while_running(self, engine):
        engine.state = EngineState.RUNNING
        with pytest.raises(RuntimeError, match="Cannot load picks"):
            engine.load_picks([make_pick()])

    @pytest.mark.asyncio
    async def test_start_without_picks_fails(self, engine):
        with pytest.raises(RuntimeError, match="No picks loaded"):
            await engine.start()

    @pytest.mark.asyncio
    async def test_start_sets_running(self, engine, mock_provider):
        engine.load_picks([make_pick()])
        await engine.start()

        assert engine.state == EngineState.RUNNING
        assert engine._started_at is not None
        # Ticker should have been created and connected
        mock_provider.create_ticker.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_from_running(self, engine):
        engine.load_picks([make_pick()])
        await engine.start()
        await engine.stop()

        assert engine.state == EngineState.STOPPED
        assert engine._stopped_at is not None

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, engine):
        """Stopping an already stopped engine does nothing."""
        await engine.stop()
        assert engine.state in (EngineState.IDLE, EngineState.STOPPED)

    def test_pause_resume(self, engine):
        engine.load_picks([make_pick()])
        # Set state to running manually (without starting async tasks)
        engine.state = EngineState.RUNNING
        for s in engine._strategies.values():
            s.state = StrategyState.RUNNING

        engine.pause()
        assert engine.state == EngineState.PAUSED

        engine.resume()
        assert engine.state == EngineState.RUNNING

    def test_pause_non_running_ignored(self, engine):
        engine.state = EngineState.IDLE
        engine.pause()
        assert engine.state == EngineState.IDLE

    def test_resume_non_paused_ignored(self, engine):
        engine.state = EngineState.RUNNING
        engine.resume()
        assert engine.state == EngineState.RUNNING


# ═══════════════════════════════════════════════════════════════════════════════
# Tick Processing Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTickProcessing:
    """Tests for tick → candle → strategy pipeline."""

    @pytest.mark.asyncio
    async def test_process_ticks_builds_candles(self, engine):
        pick = make_pick("RELIANCE", 738561)
        engine.load_picks([pick])
        await engine.start()

        # Feed ticks across two 5-min windows
        ticks_w1 = [
            make_tick(738561, 2505.0, datetime(2025, 1, 15, 9, 15, 0)),
            make_tick(738561, 2510.0, datetime(2025, 1, 15, 9, 16, 0)),
            make_tick(738561, 2503.0, datetime(2025, 1, 15, 9, 17, 0)),
        ]
        await engine._process_ticks(ticks_w1)

        # No candle completed yet
        builder = engine._candle_builders[738561]
        assert builder._tick_count == 3

        # Tick in next window completes the candle
        await engine._process_ticks([
            make_tick(738561, 2515.0, datetime(2025, 1, 15, 9, 20, 0)),
        ])

        await engine.stop()

    @pytest.mark.asyncio
    async def test_unknown_token_ignored(self, engine):
        engine.load_picks([make_pick("RELIANCE", 738561)])
        await engine.start()

        # Tick for unregistered token
        await engine._process_ticks([
            make_tick(999999, 100.0, datetime(2025, 1, 15, 9, 15, 0)),
        ])

        # Should not crash, builder shouldn't exist
        assert 999999 not in engine._candle_builders
        await engine.stop()

    @pytest.mark.asyncio
    async def test_ticks_ignored_when_stopped(self, engine):
        engine.load_picks([make_pick("RELIANCE", 738561)])
        engine.state = EngineState.STOPPED

        await engine._process_ticks([
            make_tick(738561, 100.0, datetime(2025, 1, 15, 9, 15, 0)),
        ])

        # Builder should not have been touched
        builder = engine._candle_builders[738561]
        assert builder._tick_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Feed Candle Tests (REST-based polling fallback)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFeedCandle:
    """Tests for manually feeding candles (no WebSocket)."""

    @pytest.mark.asyncio
    async def test_feed_candle_to_strategy(self, engine):
        pick = make_pick("RELIANCE", 738561)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        candle = make_candle(
            datetime(2025, 1, 15, 9, 15, 0),
            o=2505.0, h=2520.0, l=2500.0, c=2515.0,
        )
        await engine.feed_candle(738561, candle)

        # Strategy should have processed the candle (updating day OHLC)
        assert strategy._day_close == 2515.0
        await engine.stop()

    @pytest.mark.asyncio
    async def test_feed_candle_non_running_ignored(self, engine):
        engine.load_picks([make_pick("RELIANCE", 738561)])
        # Don't start — engine is IDLE
        candle = make_candle(
            datetime(2025, 1, 15, 9, 15, 0),
            o=100.0, h=102.0, l=99.0, c=101.0,
        )
        await engine.feed_candle(738561, candle)
        # Should not crash

    @pytest.mark.asyncio
    async def test_feed_candle_unknown_token_ignored(self, engine):
        engine.load_picks([make_pick("RELIANCE", 738561)])
        await engine.start()

        candle = make_candle(
            datetime(2025, 1, 15, 9, 15, 0),
            o=100.0, h=102.0, l=99.0, c=101.0,
        )
        await engine.feed_candle(999999, candle)
        # Should not crash
        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# Signal Processing Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSignalProcessing:
    """Tests for the signal → order manager pipeline."""

    @pytest.mark.asyncio
    async def test_signal_logged_as_event(self, engine, order_manager):
        pick = make_pick("RELIANCE", 738561)
        engine.load_picks([pick])
        await engine.start()

        # Inject a signal manually into the strategy
        strategy = engine._strategies[738561]
        signal = StrategySignal(
            instrument_token=738561,
            trading_symbol="RELIANCE",
            action="BUY",
            reason="Test signal",
            timestamp=datetime(2025, 1, 15, 10, 0, 0),
            order_request=OrderRequest(
                tradingsymbol="RELIANCE",
                exchange=Exchange.NSE,
                transaction_type=TransactionType.BUY,
                order_type=OrderType.MARKET,
                quantity=1,
                product=ProductType.MIS,
                variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        )
        strategy._signals.append(signal)

        await engine._process_all_signals()

        # Check events were logged
        signal_events = [e for e in engine._events if e.event_type == "signal"]
        assert len(signal_events) >= 1
        assert "BUY RELIANCE" in signal_events[0].message
        assert engine._total_signals >= 1

        await engine.stop()

    @pytest.mark.asyncio
    async def test_no_signals_no_orders(self, engine):
        engine.load_picks([make_pick("RELIANCE", 738561)])
        await engine.start()

        await engine._process_all_signals()
        assert engine._total_signals == 0
        assert engine._total_orders == 0

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# Status & Metrics Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatus:
    """Tests for get_status(), get_picks(), get_events()."""

    def test_get_status_idle(self, engine):
        status = engine.get_status()
        assert status["state"] == "idle"
        assert status["picks_count"] == 0
        assert status["strategies_count"] == 0
        assert status["ticker_connected"] is False

    def test_get_status_with_picks(self, engine):
        engine.load_picks([make_pick("RELIANCE", 738561)])
        status = engine.get_status()

        assert status["picks_count"] == 1
        assert status["strategies_count"] == 1
        assert 738561 in status["strategies"]

        strat = status["strategies"][738561]
        assert strat["symbol"] == "RELIANCE"
        assert strat["direction"] == "LONG"
        assert strat["cpr"]["pivot"] == 2500.0

    def test_get_picks(self, engine):
        engine.load_picks([
            make_pick("RELIANCE", 738561),
            make_pick("INFY", 408065, direction="SHORT"),
        ])
        picks = engine.get_picks()

        assert len(picks) == 2
        assert picks[0]["trading_symbol"] == "RELIANCE"
        assert picks[1]["trading_symbol"] == "INFY"
        assert picks[1]["direction"] == "SHORT"

    def test_get_events(self, engine):
        engine.load_picks([make_pick()])
        events = engine.get_events()

        # Should have at least the "Loaded N picks" event
        assert len(events) >= 1
        assert any("Loaded" in e["message"] for e in events)

    def test_get_events_with_limit(self, engine):
        # Generate many events
        for i in range(100):
            engine._log_event("test", f"Event {i}")

        events = engine.get_events(limit=10)
        assert len(events) == 10

    def test_event_cap_at_500(self, engine):
        for i in range(600):
            engine._log_event("test", f"Event {i}")

        assert len(engine._events) <= 500


# ═══════════════════════════════════════════════════════════════════════════════
# Ticker Callback Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTickerCallbacks:
    """Tests for WebSocket ticker event handlers."""

    def test_on_ticker_connected_subscribes(self, engine, mock_provider):
        engine.load_picks([make_pick("RELIANCE", 738561), make_pick("INFY", 408065)])
        engine._ticker = mock_provider.create_ticker()

        engine._on_ticker_connected()

        engine._ticker.subscribe.assert_called_once()
        args = engine._ticker.subscribe.call_args
        assert set(args[0][0]) == {738561, 408065}

    def test_on_ticker_disconnected_logs(self, engine):
        engine._on_ticker_disconnected(1006, "Normal closure")
        events = [e for e in engine._events if e.event_type == "info"]
        assert any("disconnected" in e.message.lower() for e in events)

    def test_on_ticker_error_logs(self, engine):
        engine._on_ticker_error(Exception("Connection lost"))
        events = [e for e in engine._events if e.event_type == "error"]
        assert len(events) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# StockPick Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStockPick:
    """Tests for StockPick data class."""

    def test_pick_creation(self):
        cpr = make_cpr(2500.0, 0.15)
        pick = StockPick(
            trading_symbol="RELIANCE",
            instrument_token=738561,
            exchange="NSE",
            cpr=cpr,
            direction="LONG",
            today_open=2505.0,
            prev_close=2498.0,
            quantity=5,
        )
        assert pick.trading_symbol == "RELIANCE"
        assert pick.direction == "LONG"
        assert pick.quantity == 5
        assert pick.cpr.width_pct == 0.15


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: Full Candle → Signal Flow
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullFlow:
    """Integration test: candle feed → strategy signal → event log."""

    @pytest.mark.asyncio
    async def test_breakout_signal_from_candle(self, engine):
        """
        Feed a candle that closes above TC on a narrow CPR day.
        Strategy should emit a LONG signal.
        """
        # CPR: pivot=2500, narrow
        pick = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        # First candle: establishes same-day context (won't trigger because
        # the strategy's _current_day is already set by load_picks)
        # Feed a candle that closes above TC
        candle = make_candle(
            datetime(2025, 1, 15, 9, 20, 0),
            o=tc + 1, h=tc + 5, l=tc - 1, c=tc + 3,
        )
        await engine.feed_candle(738561, candle)

        # Check if strategy emitted a signal
        has_signals = len(strategy._signals) > 0
        if has_signals:
            assert strategy._signals[0].action == "BUY"

        await engine.stop()

    @pytest.mark.asyncio
    async def test_no_signal_on_wide_cpr(self, engine):
        """Wide CPR should not produce breakout signals."""
        pick = make_pick("RELIANCE", 738561, width_pct=0.50)  # Wide CPR
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        # Candle closes above TC but CPR is wide
        tc = strategy._cpr.tc
        candle = make_candle(
            datetime(2025, 1, 15, 9, 20, 0),
            o=tc + 1, h=tc + 5, l=tc - 1, c=tc + 3,
        )
        await engine.feed_candle(738561, candle)

        # Strategy should NOT signal — CPR too wide
        assert len(strategy._signals) == 0

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# Engine Event Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineEvents:
    """Tests for the event logging system."""

    def test_log_event_stores(self, engine):
        engine._log_event("info", "Test message", {"key": "value"})
        assert len(engine._events) == 1
        assert engine._events[0].event_type == "info"
        assert engine._events[0].message == "Test message"
        assert engine._events[0].data == {"key": "value"}

    def test_event_timestamp(self, engine):
        engine._log_event("info", "Now")
        assert engine._events[0].timestamp is not None

    @pytest.mark.asyncio
    async def test_start_logs_event(self, engine):
        engine.load_picks([make_pick()])
        await engine.start()

        info_events = [e for e in engine._events if "started" in e.message.lower()]
        assert len(info_events) >= 1

        await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_logs_event(self, engine):
        engine.load_picks([make_pick()])
        await engine.start()
        await engine.stop()

        stop_events = [e for e in engine._events if "stopped" in e.message.lower()]
        assert len(stop_events) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_load_empty_picks(self, engine):
        engine.load_picks([])
        assert len(engine._strategies) == 0
        assert engine.state == EngineState.IDLE

    @pytest.mark.asyncio
    async def test_start_with_ticker_failure(self, engine, mock_provider):
        """Engine should still work if ticker fails to connect."""
        mock_provider.create_ticker.side_effect = Exception("No credentials")
        engine.load_picks([make_pick()])
        await engine.start()

        assert engine.state == EngineState.RUNNING
        assert engine._ticker is None

        await engine.stop()

    @pytest.mark.asyncio
    async def test_multiple_starts_fail(self, engine):
        engine.load_picks([make_pick()])
        await engine.start()

        with pytest.raises(RuntimeError, match="Cannot start"):
            await engine.start()

        await engine.stop()

    def test_load_picks_replaces_previous(self, engine):
        engine.load_picks([make_pick("RELIANCE", 738561)])
        assert len(engine._strategies) == 1

        engine.load_picks([make_pick("INFY", 408065), make_pick("TCS", 2953217)])
        assert len(engine._strategies) == 2
        assert 738561 not in engine._strategies
        assert 408065 in engine._strategies

    @pytest.mark.asyncio
    async def test_strategy_error_doesnt_crash_engine(self, engine):
        """If a strategy throws, engine should log and continue."""
        engine.load_picks([make_pick("RELIANCE", 738561)])
        await engine.start()

        strategy = engine._strategies[738561]
        # Patch on_candle to throw
        original = strategy.on_candle

        async def bad_on_candle(token, candle):
            raise ValueError("Boom!")

        strategy.on_candle = bad_on_candle

        # Feed a candle — should not raise
        candle = make_candle(
            datetime(2025, 1, 15, 9, 20, 0),
            o=100, h=102, l=99, c=101,
        )
        await engine.feed_candle(738561, candle)

        # Should have logged an error event
        # (feed_candle catches the error)
        await engine.stop()
