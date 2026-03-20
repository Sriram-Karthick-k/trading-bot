"""
Tests for CPR Breakout Strategy.

Tests cover:
  - calculate_cpr() utility function (basic, narrow, wide)
  - TC/BC ordering normalization
  - Long breakout signal on narrow CPR
  - Short breakout signal on narrow CPR
  - No signal on wide CPR
  - Stop-loss exit
  - Target exit
  - End-of-day auto-close
  - One trade per day limit
"""

from datetime import datetime

import pytest

from app.strategies.cpr_breakout import (
    CPRBreakoutStrategy,
    CPRLevels,
    NIFTY_INDEX_TOKENS,
    calculate_cpr,
)
from app.providers.types import Candle


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
        **overrides,
    }
    return CPRBreakoutStrategy(strategy_id="test-cpr", params=params)


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
