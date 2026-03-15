"""
Tick replay engine.

Replays previously recorded ticks through a MockProvider at configurable speed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from app.providers.types import TickData, TickMode
from app.providers.mock.recorder import RecordedTickEntry

logger = logging.getLogger(__name__)


@dataclass
class ReplayConfig:
    speed_multiplier: float = 1.0
    start_seq: int = 0
    end_seq: int | None = None
    instrument_filter: set[int] | None = None


class TickReplayer:
    """
    Replays recorded tick data at configurable speed.

    Usage:
        replayer = TickReplayer(entries=recorded_entries)
        replayer.set_on_tick(callback)
        replayer.configure(ReplayConfig(speed_multiplier=10.0))
        await replayer.play()
    """

    def __init__(self, entries: list[RecordedTickEntry] | None = None):
        self._entries = entries or []
        self._config = ReplayConfig()
        self._on_tick: Callable[[list[TickData]], None] | None = None
        self._playing = False
        self._paused = False
        self._current_index = 0

    def load_entries(self, entries: list[RecordedTickEntry]) -> None:
        self._entries = sorted(entries, key=lambda e: e.seq_no)
        self._current_index = 0

    def set_on_tick(self, callback: Callable[[list[TickData]], None]) -> None:
        self._on_tick = callback

    def configure(self, config: ReplayConfig) -> None:
        self._config = config

    @property
    def total_ticks(self) -> int:
        return len(self._entries)

    @property
    def progress(self) -> float:
        if not self._entries:
            return 0.0
        return self._current_index / len(self._entries)

    @property
    def is_playing(self) -> bool:
        return self._playing and not self._paused

    def _deserialize_tick(self, entry: RecordedTickEntry) -> TickData:
        d = json.loads(entry.tick_json)
        return TickData(
            instrument_token=d["instrument_token"],
            last_price=d.get("last_price", 0.0),
            last_quantity=d.get("last_quantity", 0),
            average_price=d.get("average_price", 0.0),
            volume=d.get("volume", 0),
            buy_quantity=d.get("buy_quantity", 0),
            sell_quantity=d.get("sell_quantity", 0),
            ohlc_open=d.get("ohlc_open", 0.0),
            ohlc_high=d.get("ohlc_high", 0.0),
            ohlc_low=d.get("ohlc_low", 0.0),
            ohlc_close=d.get("ohlc_close", 0.0),
            oi=d.get("oi", 0),
            timestamp=datetime.fromisoformat(entry.timestamp),
            mode=TickMode(d.get("mode", "full")),
        )

    def _should_include(self, entry: RecordedTickEntry) -> bool:
        if self._config.start_seq and entry.seq_no < self._config.start_seq:
            return False
        if self._config.end_seq and entry.seq_no > self._config.end_seq:
            return False
        if self._config.instrument_filter and entry.instrument_token not in self._config.instrument_filter:
            return False
        return True

    async def play(self) -> None:
        """Replay all ticks asynchronously, calling on_tick for each."""
        import asyncio

        if not self._on_tick:
            logger.warning("No on_tick callback set, replay will have no effect")
            return

        self._playing = True
        self._paused = False
        logger.info("Replay started: ticks=%d speed=%.1fx",
                     len(self._entries), self._config.speed_multiplier)

        prev_ts: datetime | None = None

        while self._current_index < len(self._entries) and self._playing:
            if self._paused:
                await asyncio.sleep(0.05)
                continue

            entry = self._entries[self._current_index]
            if not self._should_include(entry):
                self._current_index += 1
                continue

            # Calculate inter-tick delay
            current_ts = datetime.fromisoformat(entry.timestamp)
            if prev_ts and self._config.speed_multiplier > 0:
                delta = (current_ts - prev_ts).total_seconds()
                if delta > 0:
                    await asyncio.sleep(delta / self._config.speed_multiplier)

            tick = self._deserialize_tick(entry)
            self._on_tick([tick])
            prev_ts = current_ts
            self._current_index += 1

        self._playing = False
        logger.info("Replay finished at index %d", self._current_index)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._playing = False
        self._paused = False

    def seek(self, index: int) -> None:
        self._current_index = max(0, min(index, len(self._entries) - 1))

    def reset(self) -> None:
        self._current_index = 0
        self._playing = False
        self._paused = False
