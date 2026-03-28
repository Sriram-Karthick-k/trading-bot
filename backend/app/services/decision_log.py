"""
Decision Log — structured ring-buffer for strategy/risk/engine/order decisions.

Every decision point in the trading pipeline logs here so the trader can see
exactly WHY an order was placed, rejected, or skipped.

Components that log:
  - Strategy: entry/exit checks, breakout detection, SL/target evaluation
  - RiskManager: each risk check result
  - OrderManager: signal received, LTP fetch, risk result, placement
  - Engine: tick processing, candle building, signal drain

Usage:
    from app.services.decision_log import decision_log

    decision_log.log("strategy", "info", "Checking entry", {
        "candle_close": 1234.5,
        "tc": 1230.0,
        "bc": 1225.0,
        "breakout": False,
    })

API:
    GET /api/engine/logs?level=info&component=strategy&limit=200
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecisionEntry:
    """A single decision log entry."""

    timestamp: str
    component: str  # "strategy", "risk", "order_manager", "engine"
    level: str      # "debug", "info", "warn", "error"
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DecisionLog:
    """
    Thread-safe ring buffer of decision entries.

    Holds up to `max_size` entries. Oldest entries are evicted when full.
    """

    def __init__(self, max_size: int = 2000):
        self._buffer: deque[DecisionEntry] = deque(maxlen=max_size)
        self._broadcast_cb: Any = None  # async fn(entry_dict) for WS push

    def set_broadcast_callback(self, cb: Any) -> None:
        """Set the async callback for broadcasting new entries via WebSocket."""
        self._broadcast_cb = cb

    def log(
        self,
        component: str,
        level: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> DecisionEntry:
        """
        Record a decision entry.

        Args:
            component: Source component (strategy, risk, order_manager, engine)
            level: Log level (debug, info, warn, error)
            message: Human-readable description
            data: Structured data for inspection
        """
        entry = DecisionEntry(
            timestamp=datetime.now().isoformat(),
            component=component,
            level=level,
            message=message,
            data=data or {},
        )
        self._buffer.append(entry)

        # Also emit to Python logger at appropriate level
        log_level = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warn": logging.WARNING,
            "error": logging.ERROR,
        }.get(level, logging.INFO)
        logger.log(log_level, "[%s] %s %s", component, message, data or "")

        # Broadcast via WebSocket if callback is wired
        if self._broadcast_cb:
            self._schedule_broadcast(entry)

        return entry

    def get_entries(
        self,
        limit: int = 200,
        component: str | None = None,
        level: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Query entries from the ring buffer.

        Args:
            limit: Max entries to return (most recent first)
            component: Filter by component name
            level: Filter by minimum level (debug < info < warn < error)
            since: ISO timestamp — only return entries after this time
        """
        level_order = {"debug": 0, "info": 1, "warn": 2, "error": 3}
        min_level = level_order.get(level or "debug", 0)

        results: list[dict[str, Any]] = []
        for entry in reversed(self._buffer):
            if component and entry.component != component:
                continue
            entry_level = level_order.get(entry.level, 0)
            if entry_level < min_level:
                continue
            if since and entry.timestamp < since:
                break  # Entries are chronological, so we can stop
            results.append(entry.to_dict())
            if len(results) >= limit:
                break

        # Return in chronological order (oldest first)
        results.reverse()
        return results

    def clear(self) -> int:
        """Clear all entries. Returns count cleared."""
        count = len(self._buffer)
        self._buffer.clear()
        return count

    @property
    def size(self) -> int:
        return len(self._buffer)

    def _schedule_broadcast(self, entry: DecisionEntry) -> None:
        """Schedule async broadcast on the event loop."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._broadcast_cb(entry.to_dict()),
            )
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(
                        asyncio.ensure_future,
                        self._broadcast_cb(entry.to_dict()),
                    )
            except Exception:
                pass  # No event loop — skip broadcast


# ── Singleton ────────────────────────────────────────────────────────────────

decision_log = DecisionLog()
