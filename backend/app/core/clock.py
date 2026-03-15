"""
Injectable clock abstraction.

All time-dependent code (strategies, scheduler, risk manager) must use
the Clock protocol instead of datetime.now() directly. This enables:
1. Deterministic testing with fixed timestamps
2. Mock/paper trading with virtual time (custom date simulation)
3. Replay of historical market data at accelerated speed
"""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta
from typing import Protocol

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


class Clock(Protocol):
    """Protocol for time sources. All implementations must be IST-aware."""

    def now(self) -> datetime:
        """Current timestamp in IST."""
        ...

    def today(self) -> date:
        """Current date in IST."""
        ...

    def is_market_open(self) -> bool:
        """Whether the current time is within market hours (9:15 AM - 3:30 PM IST, Mon-Fri)."""
        ...


class RealClock:
    """Production clock using actual system time in IST."""

    def now(self) -> datetime:
        return datetime.now(IST)

    def today(self) -> date:
        return self.now().date()

    def is_market_open(self) -> bool:
        now = self.now()
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close


class VirtualClock:
    """
    Virtual clock for mock/paper trading and testing.

    Time can be set to any point and advanced manually or at
    a configurable speed multiplier.
    """

    def __init__(self, initial_time: datetime | None = None):
        self._current_time: datetime = initial_time or datetime.now(IST)
        self._speed: float = 1.0
        self._paused: bool = False
        self._last_real_time: datetime = datetime.now(IST)

    def now(self) -> datetime:
        if self._current_time.tzinfo is None:
            return self._current_time.replace(tzinfo=IST)
        return self._current_time

    def today(self) -> date:
        return self.now().date()

    def is_market_open(self) -> bool:
        now = self.now()
        if now.weekday() >= 5:
            return False
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close

    def set_time(self, dt: datetime) -> None:
        """Jump to a specific point in time."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        self._current_time = dt
        self._last_real_time = datetime.now(IST)

    def advance(self, delta: timedelta) -> None:
        """Advance virtual time by a specific duration."""
        self._current_time += delta

    def advance_to(self, dt: datetime) -> None:
        """Advance to a specific future timestamp."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        if dt < self._current_time:
            raise ValueError(
                f"Cannot advance backwards: current={self._current_time}, target={dt}"
            )
        self._current_time = dt

    def set_speed(self, speed: float) -> None:
        """Set the speed multiplier (1.0 = real-time, 10.0 = 10x faster)."""
        if speed <= 0:
            raise ValueError(f"Speed must be positive, got {speed}")
        self._speed = speed

    def get_speed(self) -> float:
        return self._speed

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False
        self._last_real_time = datetime.now(IST)

    def is_paused(self) -> bool:
        return self._paused

    def tick(self) -> None:
        """
        Advance virtual time based on elapsed real time and speed.
        Call this periodically in the simulation loop.
        """
        if self._paused:
            return
        real_now = datetime.now(IST)
        real_elapsed = real_now - self._last_real_time
        virtual_elapsed = real_elapsed * self._speed
        self._current_time += virtual_elapsed
        self._last_real_time = real_now

    def reset(self, initial_time: datetime | None = None) -> None:
        """Reset to initial state."""
        self._current_time = initial_time or datetime.now(IST)
        self._speed = 1.0
        self._paused = False
        self._last_real_time = datetime.now(IST)
