"""
Tests for CPR Breakout Strategy.

Tests cover:
  - calculate_cpr() utility function (basic, narrow, wide)
  - TC/BC ordering normalization
  - Long breakout signal on narrow CPR
  - Short breakout signal on narrow CPR
  - No signal on wide CPR
  - Stop-loss exit (candle-based)
  - Target exit (candle-based)
  - End-of-day auto-close
  - One trade per day limit
  - Tick-level SL exit (LONG and SHORT)
  - Tick-level target exit (LONG and SHORT)
  - Trailing stop loss (activation, update, never moves backward)
  - Tick ignores wrong instrument token
  - Tick ignores zero/negative price
  - No signal when no position (tick-level)
"""

from datetime import datetime

import pytest

from app.strategies.cpr_breakout import (
    CPRBreakoutStrategy,
    CPRLevels,
    NIFTY_INDEX_TOKENS,
    calculate_cpr,
)
from app.providers.types import Candle, TickData


# ── Helper ──────────────────────────────────────────────────────────────────


def make_candle(
    ts: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int = 1000,
) -> Candle:
    return Candle(
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_strategy(**overrides) -> CPRBreakoutStrategy:
    params = {
        "narrow_threshold": 0.3,
        "risk_reward_ratio": 2.0,
        "instrument_token": 256265,
        "trading_symbol": "NIFTY 50",
        "exchange": "NSE",
        "quantity": 1,
        "trail_activation_pct": 0.3,
        "trail_distance_pct": 0.2,
        **overrides,
    }
    return CPRBreakoutStrategy(strategy_id="test-cpr", params=params)


def make_tick(
    token: int,
    price: float,
    ts: datetime | None = None,
    volume: int = 1000,
) -> TickData:
    return TickData(
        instrument_token=token,
        last_price=price,
        timestamp=ts or datetime(2024, 1, 2, 9, 30),
        volume=volume,
    )


# ── calculate_cpr tests ────────────────────────────────────────────────────


class TestCalculateCPR:
    def test_basic_calculation(self):
        """Verify basic CPR formula: pivot, tc, bc from known values."""
        # H=100, L=90, C=95
        # pivot = (100+90+95)/3 = 95.0
        # bc = (100+90)/2 = 95.0
        # tc = 2*95 - 95 = 95.0
        cpr = calculate_cpr(high=100.0, low=90.0, close=95.0)
        assert cpr.pivot == 95.0
        assert cpr.bc == 95.0
        assert cpr.tc == 95.0
        assert cpr.width == 0.0

    def test_narrow_cpr(self):
        """CPR with close very near midpoint gives narrow range."""
        # H=100, L=99, C=99.5 (close == midrange exactly)
        # pivot = (100+99+99.5)/3 = 99.5
        # bc = (100+99)/2 = 99.5
        # tc = 2*99.5 - 99.5 = 99.5
        # width_pct = 0% — extremely narrow
        cpr = calculate_cpr(high=100.0, low=99.0, close=99.5)
        assert cpr.width_pct < 0.3
        assert cpr.tc >= cpr.bc
        assert cpr.is_narrow  # < 0.3% default

    def test_wide_cpr(self):
        """CPR with close far from midpoint gives wide range."""
        # H=110, L=90, C=108  (close near high)
        # pivot = (110+90+108)/3 = 102.6667
        # bc = (110+90)/2 = 100.0
        # tc = 2*102.6667 - 100 = 105.3333
        cpr = calculate_cpr(high=110.0, low=90.0, close=108.0)
        assert cpr.width_pct > 1.0  # Wide
        assert not cpr.is_narrow

    def test_tc_always_gte_bc(self):
        """TC should always be >= BC regardless of close position."""
        # Close below midrange: bc=(100+80)/2=90, close=82
        # pivot=(100+80+82)/3=87.33, tc=2*87.33-90=84.67 < bc=90
        # Should be swapped so tc=90, bc=84.67
        cpr = calculate_cpr(high=100.0, low=80.0, close=82.0)
        assert cpr.tc >= cpr.bc, f"tc={cpr.tc} should be >= bc={cpr.bc}"

    def test_tc_bc_with_close_above_midrange(self):
        """When close > midrange, natural TC > BC."""
        cpr = calculate_cpr(high=100.0, low=80.0, close=98.0)
        assert cpr.tc > cpr.bc
        # tc should be > pivot since close is above midrange
        assert cpr.pivot > cpr.bc


# ── CPR Breakout Strategy tests ─────────────────────────────────────────────


class TestCPRBreakoutStrategy:
    def test_strategy_name(self):
        assert CPRBreakoutStrategy.name() == "cpr_breakout"

    def test_strategy_params_schema(self):
        schema = CPRBreakoutStrategy.get_params_schema()
        names = [p.name for p in schema]
        assert "narrow_threshold" in names
        assert "risk_reward_ratio" in names
        assert "instrument_token" in names

    @pytest.mark.asyncio
    async def test_long_breakout_on_narrow_cpr(self):
        """
        Day 1: Build OHLC for CPR calculation.
        Day 2: If CPR is narrow, a candle closing above TC should trigger LONG.
        """
        strategy = make_strategy(narrow_threshold=1.0)  # Generous threshold
        token = 256265

        # Day 1 candles — build daily OHLC
        # We use a tight range so CPR will be narrow
        day1_candles = [
            make_candle(datetime(2024, 1, 1, 9, 15), 100.0, 100.5, 99.5, 100.2),
            make_candle(datetime(2024, 1, 1, 9, 20), 100.2, 100.6, 99.8, 100.3),
            make_candle(datetime(2024, 1, 1, 15, 25), 100.3, 100.4, 99.9, 100.1),
        ]

        for c in day1_candles:
            await strategy.on_candle(token, c)

        # No signals on day 1 (no CPR yet)
        signals = strategy.consume_signals()
        assert len(signals) == 0

        # Day 2 — first candle triggers CPR calculation from day 1
        # Day 1 accumulated: open=100.0 high=100.6, low=99.5, close=100.1
        # pivot = (100.6+99.5+100.1)/3 = 100.0667
        # bc = (100.6+99.5)/2 = 100.05
        # tc = 2*100.0667 - 100.05 = 100.0833
        # width_pct = (100.0833-100.05)/100.0667*100 ~ 0.033% => narrow!

        # First candle of day 2 (triggers day transition, no signal)
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 15), 100.0, 100.2, 99.8, 100.0,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 0  # Day transition candle, no entry yet

        # Candle that closes above TC — should trigger LONG
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 20), 100.0, 101.0, 100.0, 100.5,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "BUY"
        assert "LONG" in signals[0].reason

    @pytest.mark.asyncio
    async def test_short_breakout_on_narrow_cpr(self):
        """Candle closing below BC on narrow CPR day triggers SHORT."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265

        # Day 1 — tight range
        day1_candles = [
            make_candle(datetime(2024, 1, 1, 9, 15), 100.0, 100.5, 99.5, 100.2),
            make_candle(datetime(2024, 1, 1, 15, 25), 100.2, 100.6, 99.8, 100.1),
        ]
        for c in day1_candles:
            await strategy.on_candle(token, c)

        # Day 2 — first candle (transition)
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 15), 100.0, 100.1, 99.0, 99.5,
        ))

        # Candle closing below BC — trigger SHORT
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 20), 99.5, 99.6, 98.5, 99.0,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert "SHORT" in signals[0].reason

    @pytest.mark.asyncio
    async def test_no_signal_on_wide_cpr(self):
        """Wide CPR day should produce no entry signals."""
        strategy = make_strategy(narrow_threshold=0.3)  # Strict threshold
        token = 256265

        # Day 1 — wide range (big difference between close and midrange)
        day1_candles = [
            make_candle(datetime(2024, 1, 1, 9, 15), 100.0, 110.0, 90.0, 108.0),
        ]
        for c in day1_candles:
            await strategy.on_candle(token, c)

        # Day 2 — candle above TC should NOT trigger (wide CPR)
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 15), 108.0, 112.0, 107.0, 111.0,
        ))
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 20), 111.0, 115.0, 110.0, 114.0,
        ))

        signals = strategy.consume_signals()
        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_stop_loss_exit(self):
        """After LONG entry, price hitting SL (BC) should trigger SELL."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265

        # Day 1
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 1, 9, 15), 100.0, 100.5, 99.5, 100.2,
        ))

        # Day 2 — transition
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 15), 100.0, 100.2, 99.8, 100.0,
        ))
        strategy.consume_signals()

        # Entry — LONG
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 20), 100.0, 101.0, 100.0, 100.5,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "BUY"

        # SL hit — candle low goes below BC (stop loss)
        sl = strategy._stop_loss
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 25), 100.2, 100.3, sl - 0.5, sl - 0.3,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert "Stop loss" in signals[0].reason

    @pytest.mark.asyncio
    async def test_target_exit(self):
        """After LONG entry, price hitting target should trigger SELL."""
        strategy = make_strategy(narrow_threshold=1.0, risk_reward_ratio=2.0)
        token = 256265

        # Day 1
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 1, 9, 15), 100.0, 100.5, 99.5, 100.2,
        ))

        # Day 2 — transition
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 15), 100.0, 100.2, 99.8, 100.0,
        ))
        strategy.consume_signals()

        # Entry — LONG
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 20), 100.0, 101.0, 100.0, 100.5,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "BUY"

        target = strategy._target
        # Target hit — candle high reaches target
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 25), 100.5, target + 1.0, 100.4, target + 0.5,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert "Target" in signals[0].reason

    @pytest.mark.asyncio
    async def test_end_of_day_auto_close(self):
        """Open position auto-closes on day transition."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265

        # Day 1
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 1, 9, 15), 100.0, 100.5, 99.5, 100.2,
        ))

        # Day 2 — transition + entry
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 15), 100.0, 100.2, 99.8, 100.0,
        ))
        strategy.consume_signals()

        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 20), 100.0, 101.0, 100.0, 100.5,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "BUY"
        assert strategy._position == "LONG"

        # Day 3 — transition should auto-close the LONG position
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 3, 9, 15), 100.5, 100.8, 100.3, 100.6,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert "End of day" in signals[0].reason
        assert strategy._position is None

    @pytest.mark.asyncio
    async def test_one_trade_per_day(self):
        """After one trade per day, no further entries until next day."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265

        # Day 1
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 1, 9, 15), 100.0, 100.5, 99.5, 100.2,
        ))

        # Day 2 — transition
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 15), 100.0, 100.2, 99.8, 100.0,
        ))
        strategy.consume_signals()

        # Entry — LONG
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 20), 100.0, 101.0, 100.0, 100.5,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1

        # SL hit — exit
        sl = strategy._stop_loss
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 9, 25), 100.0, 100.1, sl - 0.5, sl - 0.3,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 1  # Exit signal

        # Another breakout candle — should NOT trigger (already traded today)
        await strategy.on_candle(token, make_candle(
            datetime(2024, 1, 2, 10, 0), 100.0, 101.5, 100.0, 101.2,
        ))
        signals = strategy.consume_signals()
        assert len(signals) == 0


# ── Constants test ──────────────────────────────────────────────────────────


class TestNiftyIndexTokens:
    def test_has_16_indices(self):
        assert len(NIFTY_INDEX_TOKENS) == 16

    def test_contains_key_indices(self):
        assert "NIFTY 50" in NIFTY_INDEX_TOKENS
        assert "NIFTY BANK" in NIFTY_INDEX_TOKENS
        assert "NIFTY IT" in NIFTY_INDEX_TOKENS

    def test_all_tokens_are_positive_ints(self):
        for name, token in NIFTY_INDEX_TOKENS.items():
            assert isinstance(token, int), f"{name} token should be int"
            assert token > 0, f"{name} token should be positive"


# ── Helpers to create strategy with pre-injected open positions ─────────────


async def setup_long_position(
    strategy: CPRBreakoutStrategy, token: int = 256265
) -> None:
    """Feed candles to put the strategy into a LONG position on day 2."""
    # Day 1 — tight range for narrow CPR
    await strategy.on_candle(token, make_candle(
        datetime(2024, 1, 1, 9, 15), 100.0, 100.5, 99.5, 100.2,
    ))

    # Day 2 — transition (calculates CPR from day 1)
    await strategy.on_candle(token, make_candle(
        datetime(2024, 1, 2, 9, 15), 100.0, 100.2, 99.8, 100.0,
    ))
    strategy.consume_signals()

    # LONG entry — candle closes above TC
    await strategy.on_candle(token, make_candle(
        datetime(2024, 1, 2, 9, 20), 100.0, 101.0, 100.0, 100.5,
    ))
    signals = strategy.consume_signals()
    assert len(signals) == 1
    assert signals[0].action == "BUY"
    assert strategy._position == "LONG"

    # Simulate order confirmation so tick-level SL/target checks are active
    strategy._order_confirmed = True


async def setup_short_position(
    strategy: CPRBreakoutStrategy, token: int = 256265
) -> None:
    """Feed candles to put the strategy into a SHORT position on day 2."""
    # Day 1 — tight range
    await strategy.on_candle(token, make_candle(
        datetime(2024, 1, 1, 9, 15), 100.0, 100.5, 99.5, 100.2,
    ))

    # Day 2 — transition
    await strategy.on_candle(token, make_candle(
        datetime(2024, 1, 2, 9, 15), 100.0, 100.1, 99.0, 99.5,
    ))
    strategy.consume_signals()

    # SHORT entry — candle closes below BC
    await strategy.on_candle(token, make_candle(
        datetime(2024, 1, 2, 9, 20), 99.5, 99.6, 98.5, 99.0,
    ))
    signals = strategy.consume_signals()
    assert len(signals) == 1
    assert signals[0].action == "SELL"
    assert strategy._position == "SHORT"

    # Simulate order confirmation so tick-level SL/target checks are active
    strategy._order_confirmed = True


# ── Tick-level SL/target exit tests ────────────────────────────────────────


class TestTickLevelExits:
    """Tests for on_tick() SL/target checking — immediate exits on tick data."""

    @pytest.mark.asyncio
    async def test_tick_sl_exit_long(self):
        """LONG position: tick at or below SL emits SELL signal."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_long_position(strategy, token)

        sl = strategy._stop_loss
        # Tick at SL price
        await strategy.on_tick(make_tick(token, sl, datetime(2024, 1, 2, 9, 22)))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert "Tick SL hit" in signals[0].reason
        assert signals[0].metadata.get("exit_source") == "tick"
        assert strategy._position is None

    @pytest.mark.asyncio
    async def test_tick_sl_exit_long_below(self):
        """LONG position: tick below SL also triggers exit."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_long_position(strategy, token)

        sl = strategy._stop_loss
        await strategy.on_tick(make_tick(token, sl - 1.0, datetime(2024, 1, 2, 9, 22)))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert strategy._position is None

    @pytest.mark.asyncio
    async def test_tick_target_exit_long(self):
        """LONG position: tick at or above target emits SELL signal."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_long_position(strategy, token)

        target = strategy._target
        await strategy.on_tick(make_tick(token, target, datetime(2024, 1, 2, 9, 25)))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert "Tick target hit" in signals[0].reason
        assert strategy._position is None

    @pytest.mark.asyncio
    async def test_tick_sl_exit_short(self):
        """SHORT position: tick at or above SL emits BUY signal."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_short_position(strategy, token)

        sl = strategy._stop_loss
        await strategy.on_tick(make_tick(token, sl, datetime(2024, 1, 2, 9, 22)))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "BUY"
        assert "Tick SL hit" in signals[0].reason
        assert strategy._position is None

    @pytest.mark.asyncio
    async def test_tick_target_exit_short(self):
        """SHORT position: tick at or below target emits BUY signal."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_short_position(strategy, token)

        target = strategy._target
        await strategy.on_tick(make_tick(token, target, datetime(2024, 1, 2, 9, 25)))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "BUY"
        assert "Tick target hit" in signals[0].reason
        assert strategy._position is None

    @pytest.mark.asyncio
    async def test_tick_no_signal_when_no_position(self):
        """No position: on_tick should not emit any signal."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        assert strategy._position is None

        await strategy.on_tick(make_tick(token, 100.0))
        signals = strategy.consume_signals()
        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_tick_ignores_wrong_token(self):
        """Tick with wrong instrument_token is ignored."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_long_position(strategy, token)

        wrong_token = 999999
        sl = strategy._stop_loss
        await strategy.on_tick(make_tick(wrong_token, sl - 1.0))
        signals = strategy.consume_signals()
        assert len(signals) == 0
        assert strategy._position == "LONG"  # Still open

    @pytest.mark.asyncio
    async def test_tick_ignores_zero_price(self):
        """Tick with zero price is ignored."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_long_position(strategy, token)

        await strategy.on_tick(make_tick(token, 0.0))
        signals = strategy.consume_signals()
        assert len(signals) == 0
        assert strategy._position == "LONG"

    @pytest.mark.asyncio
    async def test_tick_between_sl_and_target_no_exit(self):
        """Tick between SL and target does NOT trigger exit."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_long_position(strategy, token)

        sl = strategy._stop_loss
        target = strategy._target
        mid_price = (sl + target) / 2.0  # In the middle, safe zone

        await strategy.on_tick(make_tick(token, mid_price))
        signals = strategy.consume_signals()
        assert len(signals) == 0
        assert strategy._position == "LONG"


# ── Trailing stop loss tests ────────────────────────────────────────────────


class TestTrailingStopLoss:
    """Tests for trailing SL logic in on_tick()."""

    @pytest.mark.asyncio
    async def test_trailing_sl_activates_on_profit_long(self):
        """LONG: trailing SL activates after price moves trail_activation_pct% above entry."""
        strategy = make_strategy(
            narrow_threshold=1.0,
            trail_activation_pct=0.3,
            trail_distance_pct=0.2,
        )
        token = 256265
        await setup_long_position(strategy, token)

        entry = strategy._entry_price   # ~100.5
        original_sl = strategy._stop_loss  # ~bc

        # Move price up by 0.5% (well above 0.3% activation threshold)
        high_price = entry * 1.005
        await strategy.on_tick(make_tick(token, high_price, datetime(2024, 1, 2, 9, 22)))
        signals = strategy.consume_signals()
        assert len(signals) == 0  # No exit yet

        # SL should have moved up from the original BC-based SL
        assert strategy._stop_loss > original_sl, (
            f"Trailing SL {strategy._stop_loss} should be > original SL {original_sl}"
        )

    @pytest.mark.asyncio
    async def test_trailing_sl_does_not_activate_below_threshold_long(self):
        """LONG: SL should NOT trail when profit is below activation threshold."""
        strategy = make_strategy(
            narrow_threshold=1.0,
            trail_activation_pct=1.0,  # Need 1% move to activate
            trail_distance_pct=0.2,
        )
        token = 256265
        await setup_long_position(strategy, token)

        entry = strategy._entry_price
        original_sl = strategy._stop_loss

        # Move price up by only 0.1% (below 1% threshold)
        small_move_price = entry * 1.001
        await strategy.on_tick(make_tick(token, small_move_price, datetime(2024, 1, 2, 9, 22)))
        strategy.consume_signals()

        # SL should remain at original level
        assert strategy._stop_loss == original_sl

    @pytest.mark.asyncio
    async def test_trailing_sl_never_moves_backward_long(self):
        """LONG: trailing SL should never decrease (even when price retraces)."""
        strategy = make_strategy(
            narrow_threshold=1.0,
            trail_activation_pct=0.1,
            trail_distance_pct=0.2,
        )
        token = 256265
        await setup_long_position(strategy, token)

        entry = strategy._entry_price

        # Price moves up sharply
        high_price = entry * 1.01  # +1%
        await strategy.on_tick(make_tick(token, high_price, datetime(2024, 1, 2, 9, 22)))
        strategy.consume_signals()
        sl_after_high = strategy._stop_loss

        # Price retraces but stays above SL
        retrace_price = entry * 1.003  # Retraced from +1% to +0.3%
        if retrace_price > strategy._stop_loss:
            await strategy.on_tick(make_tick(token, retrace_price, datetime(2024, 1, 2, 9, 23)))
            strategy.consume_signals()
            assert strategy._stop_loss >= sl_after_high, (
                f"SL should not decrease: {strategy._stop_loss} < {sl_after_high}"
            )

    @pytest.mark.asyncio
    async def test_trailing_sl_updates_on_new_high_long(self):
        """LONG: SL moves higher when price makes new highs."""
        strategy = make_strategy(
            narrow_threshold=1.0,
            trail_activation_pct=0.1,
            trail_distance_pct=0.2,
            risk_reward_ratio=5.0,  # High R:R so target is far away
        )
        token = 256265
        await setup_long_position(strategy, token)

        entry = strategy._entry_price

        # First move up
        price1 = entry * 1.005  # +0.5%
        await strategy.on_tick(make_tick(token, price1, datetime(2024, 1, 2, 9, 22)))
        strategy.consume_signals()
        sl1 = strategy._stop_loss

        # Second, higher move
        price2 = entry * 1.008  # +0.8% (still below target with R:R=5)
        await strategy.on_tick(make_tick(token, price2, datetime(2024, 1, 2, 9, 23)))
        strategy.consume_signals()
        sl2 = strategy._stop_loss

        assert sl2 > sl1, f"SL should increase on new high: {sl2} vs {sl1}"

    @pytest.mark.asyncio
    async def test_trailing_sl_activates_on_profit_short(self):
        """SHORT: trailing SL activates after price moves trail_activation_pct% below entry."""
        strategy = make_strategy(
            narrow_threshold=1.0,
            trail_activation_pct=0.3,
            trail_distance_pct=0.2,
        )
        token = 256265
        await setup_short_position(strategy, token)

        entry = strategy._entry_price  # ~99.0
        original_sl = strategy._stop_loss  # ~tc

        # Move price down by 0.5% (above 0.3% activation)
        low_price = entry * 0.995
        await strategy.on_tick(make_tick(token, low_price, datetime(2024, 1, 2, 9, 22)))
        signals = strategy.consume_signals()
        assert len(signals) == 0

        # SL should have moved down from original TC-based SL
        assert strategy._stop_loss < original_sl, (
            f"Trailing SL {strategy._stop_loss} should be < original SL {original_sl}"
        )

    @pytest.mark.asyncio
    async def test_trailing_sl_never_moves_backward_short(self):
        """SHORT: trailing SL should never increase (even when price bounces up)."""
        strategy = make_strategy(
            narrow_threshold=1.0,
            trail_activation_pct=0.1,
            trail_distance_pct=0.2,
        )
        token = 256265
        await setup_short_position(strategy, token)

        entry = strategy._entry_price

        # Price moves down sharply
        low_price = entry * 0.99  # -1%
        await strategy.on_tick(make_tick(token, low_price, datetime(2024, 1, 2, 9, 22)))
        strategy.consume_signals()
        sl_after_low = strategy._stop_loss

        # Price bounces up but stays below SL
        bounce_price = entry * 0.997  # -0.3%, bounced from -1%
        if bounce_price < strategy._stop_loss:
            await strategy.on_tick(make_tick(token, bounce_price, datetime(2024, 1, 2, 9, 23)))
            strategy.consume_signals()
            assert strategy._stop_loss <= sl_after_low, (
                f"SL should not increase: {strategy._stop_loss} > {sl_after_low}"
            )

    @pytest.mark.asyncio
    async def test_trailing_sl_triggers_exit_on_retrace_long(self):
        """LONG: price moves up (trail activates), then retraces to trailing SL — exit."""
        strategy = make_strategy(
            narrow_threshold=1.0,
            trail_activation_pct=0.1,  # Low threshold for easy activation
            trail_distance_pct=0.2,    # Trail 0.2% below peak
            risk_reward_ratio=5.0,     # High R:R so target is far away
        )
        token = 256265
        await setup_long_position(strategy, token)

        entry = strategy._entry_price

        # Push price up to +0.8% (below target with R:R=5)
        peak = entry * 1.008
        await strategy.on_tick(make_tick(token, peak, datetime(2024, 1, 2, 9, 22)))
        strategy.consume_signals()

        trailing_sl = strategy._stop_loss
        assert strategy._cpr is not None
        assert trailing_sl > strategy._cpr.bc  # Trail must be above original SL

        # Price falls to trailing SL
        await strategy.on_tick(make_tick(token, trailing_sl, datetime(2024, 1, 2, 9, 25)))
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "SELL"
        assert "Tick SL hit" in signals[0].reason
        assert strategy._position is None

    @pytest.mark.asyncio
    async def test_trailing_peak_resets_on_close(self):
        """After position close, _trailing_peak should be reset to 0."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_long_position(strategy, token)

        assert strategy._trailing_peak == strategy._entry_price

        sl = strategy._stop_loss
        await strategy.on_tick(make_tick(token, sl, datetime(2024, 1, 2, 9, 22)))
        strategy.consume_signals()

        assert strategy._position is None
        assert strategy._trailing_peak == 0.0

    @pytest.mark.asyncio
    async def test_trailing_peak_initialized_at_entry(self):
        """_trailing_peak should be set to entry_price at entry time."""
        strategy = make_strategy(narrow_threshold=1.0)
        token = 256265
        await setup_long_position(strategy, token)

        assert strategy._trailing_peak == strategy._entry_price

    @pytest.mark.asyncio
    async def test_params_schema_includes_trailing_params(self):
        """Param schema should include trail_activation_pct and trail_distance_pct."""
        schema = CPRBreakoutStrategy.get_params_schema()
        names = [p.name for p in schema]
        assert "trail_activation_pct" in names
        assert "trail_distance_pct" in names
