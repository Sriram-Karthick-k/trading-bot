"""
Tests for Strategy base class.
"""

from datetime import datetime
import pytest

from app.strategies.base import (
    Strategy,
    StrategyState,
    StrategySignal,
    ParamDef,
    ParamType,
)
from app.providers.types import (
    Candle, TickData, TickMode,
)


class DummyStrategy(Strategy):
    @classmethod
    def name(cls) -> str:
        return "dummy"

    @classmethod
    def description(cls) -> str:
        return "A dummy strategy for testing"

    @classmethod
    def get_params_schema(cls) -> list[ParamDef]:
        return [
            ParamDef(name="threshold", param_type=ParamType.FLOAT, default=100.0, min_value=0, max_value=1000),
            ParamDef(name="mode", param_type=ParamType.ENUM, default="fast", enum_values=["fast", "slow"]),
        ]

    def get_instruments(self) -> list[int]:
        return [256265]

    async def on_tick(self, tick: TickData) -> None:
        if tick.last_price > self.get_param("threshold", 100.0):
            self._emit_signal(StrategySignal(
                instrument_token=tick.instrument_token,
                trading_symbol="NIFTY",
                action="BUY",
                reason="Price above threshold",
            ))

    async def on_candle(self, instrument_token: int, candle: Candle) -> None:
        pass


class TestStrategy:
    @pytest.fixture
    def strategy(self):
        return DummyStrategy(strategy_id="test-1", params={"threshold": 500.0, "mode": "fast"})

    def test_initial_state(self, strategy):
        assert strategy.state == StrategyState.IDLE

    @pytest.mark.asyncio
    async def test_start_stop(self, strategy):
        await strategy.start()
        assert strategy.state == StrategyState.RUNNING
        await strategy.stop()
        assert strategy.state == StrategyState.STOPPED

    def test_pause_resume(self, strategy):
        strategy.pause()
        assert strategy.state == StrategyState.PAUSED
        strategy.resume()
        assert strategy.state == StrategyState.RUNNING

    @pytest.mark.asyncio
    async def test_emits_signal(self, strategy):
        tick = TickData(
            instrument_token=256265,
            last_price=600.0,
            timestamp=datetime.now(),
            mode=TickMode.LTP,
        )
        await strategy.on_tick(tick)
        signals = strategy.consume_signals()
        assert len(signals) == 1
        assert signals[0].action == "BUY"

    @pytest.mark.asyncio
    async def test_no_signal_below_threshold(self, strategy):
        tick = TickData(
            instrument_token=256265,
            last_price=100.0,
            timestamp=datetime.now(),
            mode=TickMode.LTP,
        )
        await strategy.on_tick(tick)
        signals = strategy.consume_signals()
        assert len(signals) == 0

    def test_validate_params_valid(self, strategy):
        errors = strategy.validate_params()
        assert len(errors) == 0

    def test_validate_params_invalid_enum(self):
        s = DummyStrategy(strategy_id="test-2", params={"threshold": 100.0, "mode": "turbo"})
        errors = s.validate_params()
        assert any("turbo" in e for e in errors)

    def test_validate_params_out_of_range(self):
        s = DummyStrategy(strategy_id="test-3", params={"threshold": 5000.0, "mode": "fast"})
        errors = s.validate_params()
        assert any("max" in e for e in errors)

    def test_get_state_snapshot(self, strategy):
        snapshot = strategy.get_state_snapshot()
        assert snapshot["strategy_id"] == "test-1"
        assert snapshot["name"] == "dummy"
        assert snapshot["state"] == "idle"

    def test_record_trade_result(self, strategy):
        strategy.record_trade_result(500.0)
        strategy.record_trade_result(-200.0)
        assert strategy.metrics.total_trades == 2
        assert strategy.metrics.winning_trades == 1
        assert strategy.metrics.losing_trades == 1
        assert strategy.metrics.total_pnl == 300.0

    def test_consume_signals_drains(self, strategy):
        strategy._emit_signal(StrategySignal(
            instrument_token=256265, trading_symbol="TEST", action="BUY"
        ))
        assert len(strategy.consume_signals()) == 1
        assert len(strategy.consume_signals()) == 0
