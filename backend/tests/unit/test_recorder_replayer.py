"""
Tests for TickRecorder and TickReplayer.
"""

from datetime import datetime
import pytest

from app.providers.mock.recorder import TickRecorder
from app.providers.mock.replayer import TickReplayer, ReplayConfig
from app.providers.types import TickData, TickMode


def _make_ticks(count: int, base_price: float = 22000.0) -> list[TickData]:
    ticks = []
    for i in range(count):
        ticks.append(TickData(
            instrument_token=256265,
            last_price=base_price + i * 10,
            timestamp=datetime(2025, 1, 15, 10, 0, i),
            mode=TickMode.FULL,
        ))
    return ticks


class TestTickRecorder:
    def test_start_stop(self):
        recorder = TickRecorder(session_name="test")
        recorder.start()
        assert recorder.is_recording() is True
        recorder.stop()
        assert recorder.is_recording() is False

    def test_records_ticks(self):
        recorder = TickRecorder(session_name="test")
        recorder.start()
        ticks = _make_ticks(5)
        recorder.on_tick(ticks)
        recorder.stop()
        entries = recorder.get_entries()
        assert len(entries) == 5

    def test_instrument_filter(self):
        recorder = TickRecorder(session_name="test")
        recorder.start(instrument_tokens=[256265])
        ticks = [
            TickData(instrument_token=256265, last_price=100, timestamp=datetime.now(), mode=TickMode.LTP),
            TickData(instrument_token=999999, last_price=200, timestamp=datetime.now(), mode=TickMode.LTP),
        ]
        recorder.on_tick(ticks)
        recorder.stop()
        assert len(recorder.get_entries()) == 1

    def test_does_not_record_when_stopped(self):
        recorder = TickRecorder(session_name="test")
        ticks = _make_ticks(3)
        recorder.on_tick(ticks)
        assert len(recorder.get_entries()) == 0

    def test_metadata(self):
        recorder = TickRecorder(session_name="test_session")
        recorder.start(instrument_tokens=[256265])
        recorder.on_tick(_make_ticks(3))
        recorder.stop()
        meta = recorder.get_metadata()
        assert meta["session_name"] == "test_session"
        assert meta["tick_count"] == 3

    def test_clear(self):
        recorder = TickRecorder()
        recorder.start()
        recorder.on_tick(_make_ticks(5))
        recorder.clear()
        assert len(recorder.get_entries()) == 0


class TestTickReplayer:
    def test_load_entries(self):
        recorder = TickRecorder()
        recorder.start()
        recorder.on_tick(_make_ticks(10))
        recorder.stop()

        replayer = TickReplayer(entries=recorder.get_entries())
        assert replayer.total_ticks == 10

    @pytest.mark.asyncio
    async def test_replay_calls_on_tick(self):
        recorder = TickRecorder()
        recorder.start()
        recorder.on_tick(_make_ticks(5))
        recorder.stop()

        received = []
        replayer = TickReplayer(entries=recorder.get_entries())
        replayer.set_on_tick(lambda ticks: received.extend(ticks))
        replayer.configure(ReplayConfig(speed_multiplier=1000.0))  # Very fast
        await replayer.play()

        assert len(received) == 5

    def test_progress(self):
        replayer = TickReplayer()
        assert replayer.progress == 0.0

    def test_seek(self):
        recorder = TickRecorder()
        recorder.start()
        recorder.on_tick(_make_ticks(10))
        recorder.stop()

        replayer = TickReplayer(entries=recorder.get_entries())
        replayer.seek(5)
        assert replayer._current_index == 5

    def test_reset(self):
        recorder = TickRecorder()
        recorder.start()
        recorder.on_tick(_make_ticks(5))
        recorder.stop()

        replayer = TickReplayer(entries=recorder.get_entries())
        replayer.seek(3)
        replayer.reset()
        assert replayer._current_index == 0
