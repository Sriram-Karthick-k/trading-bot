"""
Live market data recorder.

Records ticks from a real provider into storage for later replay.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.providers.types import TickData

logger = logging.getLogger(__name__)


@dataclass
class RecordedTickEntry:
    """A single recorded tick with metadata."""
    seq_no: int
    timestamp: str  # ISO format
    instrument_token: int
    tick_json: str


class TickRecorder:
    """
    Records live tick data for later replay.

    Usage:
        recorder = TickRecorder(session_name="nifty_20250315")
        recorder.start(instrument_tokens=[256265, 260105])
        # ... ticks flow in via on_tick callback ...
        recorder.stop()
        entries = recorder.get_entries()
    """

    def __init__(self, session_name: str = ""):
        self.session_name = session_name
        self._entries: list[RecordedTickEntry] = []
        self._seq_counter = 0
        self._recording = False
        self._instrument_filter: set[int] = set()
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None

    def start(self, instrument_tokens: list[int] | None = None) -> None:
        """Start recording."""
        self._recording = True
        self._start_time = datetime.now()
        if instrument_tokens:
            self._instrument_filter = set(instrument_tokens)
        logger.info("Recording started: session=%s instruments=%s",
                     self.session_name, instrument_tokens)

    def stop(self) -> None:
        """Stop recording."""
        self._recording = False
        self._end_time = datetime.now()
        logger.info("Recording stopped: session=%s ticks=%d",
                     self.session_name, len(self._entries))

    def is_recording(self) -> bool:
        return self._recording

    def on_tick(self, ticks: list[TickData]) -> None:
        """Callback to receive ticks during recording."""
        if not self._recording:
            return

        for tick in ticks:
            if self._instrument_filter and tick.instrument_token not in self._instrument_filter:
                continue

            self._seq_counter += 1
            tick_dict = {
                "instrument_token": tick.instrument_token,
                "last_price": tick.last_price,
                "last_quantity": tick.last_quantity,
                "average_price": tick.average_price,
                "volume": tick.volume,
                "buy_quantity": tick.buy_quantity,
                "sell_quantity": tick.sell_quantity,
                "ohlc_open": tick.ohlc_open,
                "ohlc_high": tick.ohlc_high,
                "ohlc_low": tick.ohlc_low,
                "ohlc_close": tick.ohlc_close,
                "oi": tick.oi,
                "mode": tick.mode.value,
            }
            ts = tick.timestamp.isoformat() if tick.timestamp else datetime.now().isoformat()

            entry = RecordedTickEntry(
                seq_no=self._seq_counter,
                timestamp=ts,
                instrument_token=tick.instrument_token,
                tick_json=json.dumps(tick_dict),
            )
            self._entries.append(entry)

    def get_entries(self) -> list[RecordedTickEntry]:
        return list(self._entries)

    def get_metadata(self) -> dict[str, Any]:
        return {
            "session_name": self.session_name,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "end_time": self._end_time.isoformat() if self._end_time else None,
            "tick_count": len(self._entries),
            "instruments": list(self._instrument_filter),
        }

    def clear(self) -> None:
        self._entries.clear()
        self._seq_counter = 0
