"""
End-to-end tests for the CPR Trading Engine pipeline.

Validates the FULL flow: scanner picks → engine.load_picks() → engine.start()
→ feed candles → strategy emits signals → OrderManager processes through
RiskManager → provider.place_order() is called.

These tests use a MagicMock provider with controlled responses, a real
RiskManager with a VirtualClock (set to market hours), a real OrderManager,
and a real CPRBreakoutStrategy. The only mock is the provider — everything
else is the real implementation.

Key design decisions:
    - Candle timestamps use today's date so they match the _current_day
      set by load_picks() (which calls datetime.now()).
    - VirtualClock is set to 10:00 AM on a weekday for market hours.
    - We call engine._process_all_signals() directly instead of waiting
      for the background signal loop (which runs every 1s).
    - place_order returns a string "ORD-xxx" to match ManagedOrder.order_id: str.
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.clock import VirtualClock
from app.core.order_manager import ManagedOrder, OrderManager
from app.core.risk_manager import RiskLimits, RiskManager
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
from app.strategies.cpr_breakout import CPRLevels, calculate_cpr


# ── Helpers ──────────────────────────────────────────────────────────────────


def _today_ts(hour: int, minute: int, second: int = 0) -> datetime:
    """Create a datetime for today at the given time — matches load_picks _current_day."""
    now = datetime.now()
    return now.replace(hour=hour, minute=minute, second=second, microsecond=0)


def make_cpr(pivot: float = 2500.0, width_pct: float = 0.15) -> CPRLevels:
    """Create CPRLevels with controlled pivot and width."""
    half_width = (width_pct / 100.0) * pivot / 2.0
    tc = round(pivot + half_width, 2)
    bc = round(pivot - half_width, 2)
    width = round(tc - bc, 2)
    return CPRLevels(
        pivot=pivot, tc=tc, bc=bc, width=width, width_pct=round(width_pct, 4),
    )


def make_pick(
    symbol: str = "RELIANCE",
    token: int = 738561,
    direction: str = "LONG",
    quantity: int = 10,
    width_pct: float = 0.15,
    pivot: float = 2500.0,
) -> StockPick:
    """Create a StockPick with narrow CPR."""
    cpr = make_cpr(pivot=pivot, width_pct=width_pct)
    return StockPick(
        trading_symbol=symbol,
        instrument_token=token,
        exchange="NSE",
        cpr=cpr,
        direction=direction,
        today_open=pivot + 2,
        prev_close=pivot - 2,
        quantity=quantity,
    )


def make_candle(ts: datetime, o: float, h: float, l: float, c: float, v: int = 1000) -> Candle:
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def make_tick(token: int, price: float, ts: datetime) -> TickData:
    return TickData(
        instrument_token=token,
        last_price=price,
        timestamp=ts,
        volume=1000,
        mode=TickMode.QUOTE,
    )


_order_counter = 0


def _mock_place_order_factory():
    """Returns an AsyncMock that generates unique order IDs as strings."""
    counter = [0]

    async def _place_order(request):
        counter[0] += 1
        return f"ORD-{counter[0]:04d}"

    return AsyncMock(side_effect=_place_order)


def _make_provider():
    """Build a fully mocked BrokerProvider with sensible defaults."""
    provider = MagicMock()
    provider.place_order = _mock_place_order_factory()
    provider.get_ltp = AsyncMock(return_value={})
    provider.get_orders = AsyncMock(return_value=[])
    provider.get_positions = AsyncMock(return_value=MagicMock(net=[], day=[]))

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


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def provider():
    return _make_provider()


@pytest.fixture
def risk_manager():
    clock = VirtualClock(initial_time=datetime(2025, 1, 15, 10, 0, 0))
    return RiskManager(
        limits=RiskLimits(
            max_daily_loss=50_000,
            max_loss_per_trade=10_000,
            max_open_positions=10,
            max_open_orders=20,
        ),
        clock=clock,
    )


@pytest.fixture
def order_manager(provider, risk_manager):
    return OrderManager(provider=provider, risk_manager=risk_manager)


@pytest.fixture
def engine(provider, risk_manager, order_manager):
    return TradingEngine(
        provider=provider,
        risk_manager=risk_manager,
        order_manager=order_manager,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Full Pipeline — Load Picks → Start → Feed Candle → Signal → Order
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2ELongBreakout:
    """Full pipeline: narrow CPR LONG breakout entry, order placed."""

    @pytest.mark.asyncio
    async def test_long_breakout_places_buy_order(self, engine, provider):
        """
        Complete flow:
        1. Load a narrow CPR pick (RELIANCE, LONG direction)
        2. Start engine
        3. Feed a candle that closes above TC
        4. Process signals
        5. Verify: strategy emitted BUY signal, RiskManager approved, order placed
        """
        pick = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        # Feed a candle that closes above TC — triggers LONG breakout
        candle = make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        )
        await engine.feed_candle(738561, candle)

        # Strategy should have a pending BUY signal
        assert len(strategy._signals) == 1
        signal = strategy._signals[0]
        assert signal.action == "BUY"
        assert signal.trading_symbol == "RELIANCE"
        assert signal.order_request is not None
        assert signal.order_request.product == ProductType.MIS
        assert signal.order_request.transaction_type == TransactionType.BUY

        # Process signals through OrderManager → RiskManager → place_order
        await engine._process_all_signals()

        # Signals should be consumed
        assert len(strategy._signals) == 0

        # Provider's place_order should have been called
        provider.place_order.assert_called_once()
        call_args = provider.place_order.call_args[0][0]
        assert call_args.tradingsymbol == "RELIANCE"
        assert call_args.transaction_type == TransactionType.BUY
        assert call_args.quantity == 10
        assert call_args.product == ProductType.MIS

        # Engine metrics should reflect
        assert engine._total_signals == 1
        assert engine._total_orders == 1

        # Events should contain signal and order events
        signal_events = [e for e in engine._events if e.event_type == "signal"]
        order_events = [e for e in engine._events if e.event_type == "order"]
        assert len(signal_events) >= 1
        assert len(order_events) >= 1
        assert "placed" in order_events[0].data.get("status", "")

        # Strategy should be in LONG position
        assert strategy._position == "LONG"
        assert strategy._traded_today is True
        assert strategy._entry_price == tc + 3  # candle.close
        assert strategy._stop_loss == strategy._cpr.bc
        assert strategy._target > strategy._entry_price  # R:R target

        await engine.stop()

    @pytest.mark.asyncio
    async def test_long_breakout_signal_metadata(self, engine):
        """Verify signal metadata contains CPR levels and trade params."""
        pick = make_pick("INFY", 408065, direction="LONG", width_pct=0.12, quantity=5)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[408065]
        tc = strategy._cpr.tc

        candle = make_candle(
            _today_ts(9, 25), o=tc + 0.5, h=tc + 4, l=tc - 1, c=tc + 2,
        )
        await engine.feed_candle(408065, candle)

        assert len(strategy._signals) == 1
        meta = strategy._signals[0].metadata
        assert "cpr_pivot" in meta
        assert "cpr_tc" in meta
        assert "cpr_bc" in meta
        assert "entry_price" in meta
        assert "stop_loss" in meta
        assert "target" in meta
        assert meta["entry_price"] == tc + 2
        assert meta["stop_loss"] == strategy._cpr.bc
        assert meta["target"] > meta["entry_price"]

        await engine.stop()


class TestE2EShortBreakout:
    """Full pipeline: narrow CPR SHORT breakout entry."""

    @pytest.mark.asyncio
    async def test_short_breakout_places_sell_order(self, engine, provider):
        """
        Feed a candle that closes below BC → SHORT signal → SELL order placed.
        """
        pick = make_pick("HDFCBANK", 341249, direction="SHORT", width_pct=0.08, quantity=15)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[341249]
        bc = strategy._cpr.bc

        candle = make_candle(
            _today_ts(9, 20), o=bc - 1, h=bc + 0.5, l=bc - 6, c=bc - 3,
        )
        await engine.feed_candle(341249, candle)

        assert len(strategy._signals) == 1
        signal = strategy._signals[0]
        assert signal.action == "SELL"
        assert signal.order_request.transaction_type == TransactionType.SELL

        await engine._process_all_signals()

        provider.place_order.assert_called_once()
        call_args = provider.place_order.call_args[0][0]
        assert call_args.tradingsymbol == "HDFCBANK"
        assert call_args.transaction_type == TransactionType.SELL
        assert call_args.quantity == 15

        assert strategy._position == "SHORT"
        assert strategy._stop_loss == strategy._cpr.tc
        assert strategy._target < strategy._entry_price

        await engine.stop()


class TestE2EMultipleStocks:
    """E2E with multiple picks loaded simultaneously."""

    @pytest.mark.asyncio
    async def test_two_stocks_independent_signals(self, engine, provider):
        """
        Load two picks. Feed breakout candle to one, neutral to other.
        Only one should produce a signal and order.
        """
        pick_a = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10, quantity=10)
        pick_b = make_pick("TCS", 2953217, direction="LONG", width_pct=0.12, quantity=5)
        engine.load_picks([pick_a, pick_b])
        await engine.start()

        strategy_a = engine._strategies[738561]
        strategy_b = engine._strategies[2953217]

        # RELIANCE: candle breaks above TC → signal
        tc_a = strategy_a._cpr.tc
        candle_a = make_candle(
            _today_ts(9, 20), o=tc_a + 1, h=tc_a + 5, l=tc_a - 0.5, c=tc_a + 3,
        )
        await engine.feed_candle(738561, candle_a)

        # TCS: candle inside CPR range → no signal
        tc_b = strategy_b._cpr.tc
        bc_b = strategy_b._cpr.bc
        mid_b = (tc_b + bc_b) / 2
        candle_b = make_candle(
            _today_ts(9, 20), o=mid_b, h=mid_b + 1, l=mid_b - 1, c=mid_b,
        )
        await engine.feed_candle(2953217, candle_b)

        assert len(strategy_a._signals) == 1
        assert len(strategy_b._signals) == 0

        await engine._process_all_signals()

        # Only one order placed
        assert provider.place_order.call_count == 1
        assert engine._total_signals == 1
        assert engine._total_orders == 1

        await engine.stop()

    @pytest.mark.asyncio
    async def test_both_stocks_breakout(self, engine, provider):
        """
        Both stocks break out — two signals, two orders.
        """
        pick_a = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10, quantity=10)
        pick_b = make_pick("TCS", 2953217, direction="SHORT", width_pct=0.12, quantity=5)
        engine.load_picks([pick_a, pick_b])
        await engine.start()

        strategy_a = engine._strategies[738561]
        strategy_b = engine._strategies[2953217]

        # RELIANCE breaks above TC
        tc_a = strategy_a._cpr.tc
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc_a + 1, h=tc_a + 5, l=tc_a - 0.5, c=tc_a + 3,
        ))

        # TCS breaks below BC
        bc_b = strategy_b._cpr.bc
        await engine.feed_candle(2953217, make_candle(
            _today_ts(9, 20), o=bc_b - 1, h=bc_b + 0.5, l=bc_b - 6, c=bc_b - 3,
        ))

        assert len(strategy_a._signals) == 1
        assert len(strategy_b._signals) == 1

        await engine._process_all_signals()

        assert provider.place_order.call_count == 2
        assert engine._total_signals == 2
        assert engine._total_orders == 2

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Position Exit — SL and Target
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2EExitScenarios:
    """Test SL and target exits after entry."""

    @pytest.mark.asyncio
    async def test_long_stop_loss_exit(self, engine, provider):
        """
        LONG entry → next candle hits SL (low <= bc) → SELL exit signal → order.
        """
        pick = make_pick("SBIN", 779521, direction="LONG", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[779521]
        tc = strategy._cpr.tc
        bc = strategy._cpr.bc

        # Entry candle: close above TC
        await engine.feed_candle(779521, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))
        assert strategy._position == "LONG"

        # Process the entry signal
        await engine._process_all_signals()
        assert provider.place_order.call_count == 1  # Entry BUY order

        # SL candle: low goes below bc (stop loss)
        await engine.feed_candle(779521, make_candle(
            _today_ts(9, 25), o=tc, h=tc + 1, l=bc - 1, c=bc + 0.5,
        ))

        # Position should be closed
        assert strategy._position is None

        # Process exit signal
        await engine._process_all_signals()
        assert provider.place_order.call_count == 2  # Entry + Exit

        # Second order should be a SELL (closing LONG)
        second_call = provider.place_order.call_args_list[1][0][0]
        assert second_call.transaction_type == TransactionType.SELL

        # Should not trade again today
        assert strategy._traded_today is True

        await engine.stop()

    @pytest.mark.asyncio
    async def test_long_target_exit(self, engine, provider):
        """
        LONG entry → next candle hits target → SELL exit signal.
        """
        pick = make_pick("SBIN", 779521, direction="LONG", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[779521]
        tc = strategy._cpr.tc
        bc = strategy._cpr.bc

        # Entry candle
        entry_price = tc + 3
        await engine.feed_candle(779521, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=entry_price,
        ))
        assert strategy._position == "LONG"
        target = strategy._target

        await engine._process_all_signals()

        # Target candle: high reaches target
        await engine.feed_candle(779521, make_candle(
            _today_ts(9, 25), o=entry_price + 1, h=target + 1, l=entry_price, c=target - 0.5,
        ))
        assert strategy._position is None

        await engine._process_all_signals()
        assert provider.place_order.call_count == 2

        await engine.stop()

    @pytest.mark.asyncio
    async def test_short_stop_loss_exit(self, engine, provider):
        """SHORT entry → candle high hits TC (SL) → BUY exit."""
        pick = make_pick("ICICIBANK", 1270529, direction="SHORT", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[1270529]
        tc = strategy._cpr.tc
        bc = strategy._cpr.bc

        # Short entry: close below BC
        await engine.feed_candle(1270529, make_candle(
            _today_ts(9, 20), o=bc - 1, h=bc + 0.5, l=bc - 6, c=bc - 3,
        ))
        assert strategy._position == "SHORT"
        assert strategy._stop_loss == tc

        await engine._process_all_signals()

        # SL hit: high >= tc
        await engine.feed_candle(1270529, make_candle(
            _today_ts(9, 25), o=bc - 2, h=tc + 1, l=bc - 3, c=tc - 0.5,
        ))
        assert strategy._position is None

        await engine._process_all_signals()
        assert provider.place_order.call_count == 2

        # Exit order is BUY (closing SHORT)
        exit_order = provider.place_order.call_args_list[1][0][0]
        assert exit_order.transaction_type == TransactionType.BUY

        await engine.stop()

    @pytest.mark.asyncio
    async def test_short_target_exit(self, engine, provider):
        """SHORT entry → candle low hits target → BUY exit."""
        pick = make_pick("AXISBANK", 1510401, direction="SHORT", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[1510401]
        tc = strategy._cpr.tc
        bc = strategy._cpr.bc

        # Short entry
        await engine.feed_candle(1510401, make_candle(
            _today_ts(9, 20), o=bc - 1, h=bc + 0.5, l=bc - 6, c=bc - 3,
        ))
        assert strategy._position == "SHORT"
        target = strategy._target

        await engine._process_all_signals()

        # Target hit: low <= target
        await engine.feed_candle(1510401, make_candle(
            _today_ts(9, 25), o=bc - 4, h=bc - 2, l=target - 1, c=target + 0.5,
        ))
        assert strategy._position is None

        await engine._process_all_signals()
        assert provider.place_order.call_count == 2

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: One Trade Per Day Enforcement
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2EOneTradPerDay:
    """After entry+exit, strategy should NOT re-enter on same day."""

    @pytest.mark.asyncio
    async def test_no_reentry_after_sl_exit(self, engine, provider):
        """
        Entry → SL exit → another breakout candle → no new signal.
        """
        pick = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc
        bc = strategy._cpr.bc

        # Entry
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))
        await engine._process_all_signals()
        assert strategy._traded_today is True

        # SL exit
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 25), o=tc, h=tc + 1, l=bc - 1, c=bc + 0.5,
        ))
        await engine._process_all_signals()
        assert strategy._position is None

        # Another breakout candle — should NOT trigger new entry
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 30), o=tc + 2, h=tc + 8, l=tc + 1, c=tc + 6,
        ))
        assert len(strategy._signals) == 0

        # 2 orders total: entry + exit, no third
        assert provider.place_order.call_count == 2

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Tick Pipeline → Candle → Signal
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2ETickToOrder:
    """Full flow from raw ticks → candle builder → strategy → order."""

    @pytest.mark.asyncio
    async def test_ticks_build_candle_trigger_signal(self, engine, provider):
        """
        Feed enough ticks to build one 5-min candle that closes above TC.
        Signal should be emitted and order placed.
        """
        pick = make_pick("WIPRO", 969473, direction="LONG", width_pct=0.10, quantity=8)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[969473]
        tc = strategy._cpr.tc

        # Feed ticks in window 1 (9:15 - 9:19)
        base_ts = _today_ts(9, 15)
        ticks_w1 = [
            make_tick(969473, tc + 1, base_ts),
            make_tick(969473, tc + 3, base_ts.replace(minute=16)),
            make_tick(969473, tc - 0.5, base_ts.replace(minute=17)),
            make_tick(969473, tc + 2, base_ts.replace(minute=18)),  # close of window 1
        ]

        for tick in ticks_w1:
            await engine._process_ticks([tick])

        # No completed candle yet — still in window 1
        assert len(strategy._signals) == 0

        # First tick in window 2 (9:20) completes candle from window 1
        tick_w2 = make_tick(969473, tc + 4, base_ts.replace(minute=20))
        await engine._process_ticks([tick_w2])

        # Completed candle from window 1 should close above TC → LONG signal
        # close = tc + 2 (last tick of window 1)
        assert len(strategy._signals) == 1
        assert strategy._signals[0].action == "BUY"

        # Process signal through order pipeline
        await engine._process_all_signals()
        provider.place_order.assert_called_once()
        assert provider.place_order.call_args[0][0].quantity == 8

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Risk Manager Rejection
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2ERiskRejection:
    """Engine processes signal but RiskManager blocks the order."""

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_order(self, engine, provider, risk_manager):
        """
        Activate kill switch → signal generates but order is rejected.
        """
        pick = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        # Activate kill switch
        risk_manager.activate_kill_switch()

        # Feed breakout candle
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))
        assert len(strategy._signals) == 1

        # Process — should be rejected
        await engine._process_all_signals()

        # place_order should NOT have been called
        provider.place_order.assert_not_called()

        # Engine still logged the signal and order (as rejected)
        assert engine._total_signals == 1
        assert engine._total_orders == 1

        order_events = [e for e in engine._events if e.event_type == "order"]
        assert len(order_events) >= 1
        assert order_events[0].data.get("status") == "rejected"

        risk_manager.deactivate_kill_switch()
        await engine.stop()

    @pytest.mark.asyncio
    async def test_max_quantity_blocks_order(self, engine, provider, risk_manager):
        """
        Order with quantity exceeding max_quantity_per_order is rejected.
        """
        # Override quantity limit to something small
        risk_manager.limits.max_quantity_per_order = 5

        pick = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10, quantity=50)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))
        await engine._process_all_signals()

        # Order rejected due to quantity limit
        provider.place_order.assert_not_called()

        order_events = [e for e in engine._events if e.event_type == "order"]
        assert any("rejected" in e.data.get("status", "") for e in order_events)

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Engine Lifecycle + Signals
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2ELifecycle:
    """Test that engine lifecycle transitions interact correctly with signals."""

    @pytest.mark.asyncio
    async def test_pause_prevents_signal_processing(self, engine, provider):
        """
        While paused, candles build but no signals fire (strategy paused).
        """
        pick = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        # Pause
        engine.pause()
        assert engine.state == EngineState.PAUSED
        assert strategy.state == StrategyState.PAUSED

        # Feed candle — strategy is paused so feed_candle returns early
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))

        # No signal because feed_candle skips when state != RUNNING
        assert len(strategy._signals) == 0

        # Resume
        engine.resume()
        assert engine.state == EngineState.RUNNING
        assert strategy.state == StrategyState.RUNNING

        # Now a breakout candle works
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 25), o=tc + 2, h=tc + 6, l=tc + 0.5, c=tc + 4,
        ))
        assert len(strategy._signals) == 1

        await engine._process_all_signals()
        provider.place_order.assert_called_once()

        await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_processes_final_signals(self, engine, provider):
        """
        stop() force-completes candles and drains remaining signals.
        """
        pick = make_pick("RELIANCE", 738561, direction="LONG", width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        # Feed breakout candle
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))
        assert len(strategy._signals) == 1

        # Stop without manually draining — stop() should drain
        await engine.stop()

        # The signal should have been processed during stop()
        assert engine._total_signals >= 1

        await engine.stop()  # Idempotent

    @pytest.mark.asyncio
    async def test_reload_picks_resets_strategies(self, engine):
        """Loading new picks replaces previous strategies and state."""
        pick_1 = make_pick("RELIANCE", 738561)
        engine.load_picks([pick_1])
        assert 738561 in engine._strategies

        pick_2 = make_pick("TCS", 2953217)
        engine.load_picks([pick_2])
        assert 738561 not in engine._strategies
        assert 2953217 in engine._strategies
        assert len(engine._strategies) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: CPR Calculations Verification
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2ECPRIntegrity:
    """Verify that CPR levels injected by load_picks are used correctly."""

    @pytest.mark.asyncio
    async def test_cpr_levels_match_pick(self, engine):
        """Strategy's CPR should exactly match what the pick provided."""
        cpr = make_cpr(pivot=2500.0, width_pct=0.15)
        pick = StockPick(
            trading_symbol="TEST",
            instrument_token=999,
            exchange="NSE",
            cpr=cpr,
            direction="LONG",
            today_open=2502,
            prev_close=2498,
            quantity=1,
        )
        engine.load_picks([pick])

        strategy = engine._strategies[999]
        assert strategy._cpr == cpr
        assert strategy._cpr.pivot == 2500.0
        assert strategy._cpr.tc == cpr.tc
        assert strategy._cpr.bc == cpr.bc

    @pytest.mark.asyncio
    async def test_narrow_threshold_set_correctly(self, engine):
        """narrow_threshold should be width_pct + 0.01 (guarantees narrow)."""
        pick = make_pick("RELIANCE", 738561, width_pct=0.18)
        engine.load_picks([pick])

        strategy = engine._strategies[738561]
        threshold = strategy.get_param("narrow_threshold")
        assert threshold == pytest.approx(0.18 + 0.01, abs=0.001)

    @pytest.mark.asyncio
    async def test_risk_reward_computes_correct_target(self, engine):
        """
        For LONG: target = entry + 2.0 * (entry - bc)
        For RR=2.0, entry=tc+3, bc=cpr.bc:
        """
        pick = make_pick("RELIANCE", 738561, width_pct=0.10, quantity=1)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc
        bc = strategy._cpr.bc

        entry_price = tc + 3
        candle = make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=entry_price,
        )
        await engine.feed_candle(738561, candle)

        expected_sl_distance = entry_price - bc
        expected_target = entry_price + 2.0 * expected_sl_distance
        assert strategy._target == pytest.approx(expected_target, rel=1e-6)
        assert strategy._stop_loss == bc

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: No Signal Cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2ENoSignal:
    """Cases where no signal should be emitted."""

    @pytest.mark.asyncio
    async def test_candle_inside_cpr_range(self, engine, provider):
        """Close between BC and TC — no breakout."""
        pick = make_pick("RELIANCE", 738561, width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc
        bc = strategy._cpr.bc
        mid = (tc + bc) / 2

        candle = make_candle(
            _today_ts(9, 20), o=mid, h=mid + 0.5, l=mid - 0.5, c=mid,
        )
        await engine.feed_candle(738561, candle)

        assert len(strategy._signals) == 0
        await engine._process_all_signals()
        provider.place_order.assert_not_called()

        await engine.stop()

    @pytest.mark.asyncio
    async def test_candle_closes_exactly_at_tc(self, engine, provider):
        """Close == TC is NOT above TC, no LONG signal."""
        pick = make_pick("RELIANCE", 738561, width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        candle = make_candle(
            _today_ts(9, 20), o=tc - 1, h=tc + 1, l=tc - 2, c=tc,
        )
        await engine.feed_candle(738561, candle)

        assert len(strategy._signals) == 0

        await engine.stop()

    @pytest.mark.asyncio
    async def test_candle_closes_exactly_at_bc(self, engine, provider):
        """Close == BC is NOT below BC, no SHORT signal."""
        pick = make_pick("RELIANCE", 738561, width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        bc = strategy._cpr.bc

        candle = make_candle(
            _today_ts(9, 20), o=bc + 1, h=bc + 2, l=bc - 1, c=bc,
        )
        await engine.feed_candle(738561, candle)

        assert len(strategy._signals) == 0

        await engine.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Engine Status & Events
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2EStatusAndEvents:
    """Verify engine status and events reflect the full pipeline."""

    @pytest.mark.asyncio
    async def test_status_after_full_flow(self, engine, provider):
        """Status dict should reflect entry, position, metrics."""
        pick = make_pick("RELIANCE", 738561, width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))
        await engine._process_all_signals()

        status = engine.get_status()
        assert status["state"] == "running"
        assert status["picks_count"] == 1
        assert status["strategies_count"] == 1
        assert status["metrics"]["total_signals"] == 1
        assert status["metrics"]["total_orders"] == 1

        # Strategy detail
        strategy_status = status["strategies"][738561]
        assert strategy_status["position"] == "LONG"
        assert strategy_status["traded_today"] is True
        assert strategy_status["entry_price"] == tc + 3
        assert strategy_status["stop_loss"] == strategy._cpr.bc
        assert strategy_status["metrics"]["total_signals"] == 1

        await engine.stop()

    @pytest.mark.asyncio
    async def test_events_chronicle_full_flow(self, engine, provider):
        """Event log should contain: load info, start info, signal, order, stop info."""
        pick = make_pick("RELIANCE", 738561, width_pct=0.10, quantity=10)
        engine.load_picks([pick])
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))
        await engine._process_all_signals()
        await engine.stop()

        event_types = [e.event_type for e in engine._events]
        assert "info" in event_types        # load / start / stop
        assert "signal" in event_types      # BUY signal
        assert "order" in event_types       # order placed

        # Verify chronological ordering
        timestamps = [e.timestamp for e in engine._events]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1]

    @pytest.mark.asyncio
    async def test_get_picks_returns_correct_data(self, engine):
        """get_picks() should return pick data in a serializable format."""
        pick = make_pick("RELIANCE", 738561, width_pct=0.10, quantity=10)
        engine.load_picks([pick])

        picks = engine.get_picks()
        assert len(picks) == 1
        p = picks[0]
        assert p["trading_symbol"] == "RELIANCE"
        assert p["instrument_token"] == 738561
        assert p["exchange"] == "NSE"
        assert p["direction"] == "LONG"
        assert p["quantity"] == 10
        assert "cpr" in p
        assert p["cpr"]["pivot"] == 2500.0


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: WebSocket Broadcast Integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestE2EBroadcasts:
    """Verify that broadcast callbacks fire during the full flow."""

    @pytest.mark.asyncio
    async def test_callbacks_fire_during_flow(self, engine, provider):
        """Event, status, and tick callbacks should be invoked."""
        event_cb = AsyncMock()
        status_cb = AsyncMock()
        tick_cb = AsyncMock()

        engine._on_event_cb = event_cb
        engine._on_status_cb = status_cb
        engine._on_tick_cb = tick_cb

        pick = make_pick("RELIANCE", 738561, width_pct=0.10, quantity=10)
        engine.load_picks([pick])

        # load_picks calls _broadcast_status
        # (sync context — ensure_future may or may not work depending on loop)
        # Start engine to get into async context
        await engine.start()

        strategy = engine._strategies[738561]
        tc = strategy._cpr.tc

        # Process ticks to test tick_cb
        tick = make_tick(738561, tc + 2, _today_ts(9, 15))
        await engine._process_ticks([tick])
        tick_cb.assert_called()

        # Feed candle for signal — event_cb should fire for signal event
        await engine.feed_candle(738561, make_candle(
            _today_ts(9, 20), o=tc + 1, h=tc + 5, l=tc - 0.5, c=tc + 3,
        ))
        await engine._process_all_signals()

        # event_cb should have been called for multiple events
        assert event_cb.call_count >= 1

        await engine.stop()

        # status_cb should have been called (start, stop broadcast)
        assert status_cb.call_count >= 1
