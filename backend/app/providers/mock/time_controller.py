"""
Time controller for mock/paper trading sessions.

Wraps VirtualClock with session-specific controls for the mock engine:
market session boundaries, trading day simulation, and speed management.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.core.clock import IST, VirtualClock


class TimeController:
    """
    Controls virtual time for a mock trading session.

    Enforces market hours and provides session-level time control
    (start, stop, seek, speed changes).
    """

    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MINUTE = 15
    MARKET_CLOSE_HOUR = 15
    MARKET_CLOSE_MINUTE = 30

    def __init__(self, clock: VirtualClock, start_date: date | None = None):
        self._clock = clock
        self._start_date = start_date or clock.today()
        self._end_date: date | None = None
        self._current_trading_day: date = self._start_date

        if start_date:
            # Set clock to market open on start date
            market_open = datetime(
                start_date.year, start_date.month, start_date.day,
                self.MARKET_OPEN_HOUR, self.MARKET_OPEN_MINUTE,
                tzinfo=IST,
            )
            self._clock.set_time(market_open)

    @property
    def clock(self) -> VirtualClock:
        return self._clock

    @property
    def current_trading_day(self) -> date:
        return self._current_trading_day

    def set_date_range(self, start: date, end: date) -> None:
        """Set the simulation date range."""
        self._start_date = start
        self._end_date = end
        self._current_trading_day = start
        market_open = datetime(
            start.year, start.month, start.day,
            self.MARKET_OPEN_HOUR, self.MARKET_OPEN_MINUTE,
            tzinfo=IST,
        )
        self._clock.set_time(market_open)

    def advance_to_market_open(self) -> datetime:
        """Advance to market open of the current trading day."""
        dt = datetime(
            self._current_trading_day.year,
            self._current_trading_day.month,
            self._current_trading_day.day,
            self.MARKET_OPEN_HOUR,
            self.MARKET_OPEN_MINUTE,
            tzinfo=IST,
        )
        self._clock.set_time(dt)
        return dt

    def advance_to_market_close(self) -> datetime:
        """Advance to market close of the current trading day."""
        dt = datetime(
            self._current_trading_day.year,
            self._current_trading_day.month,
            self._current_trading_day.day,
            self.MARKET_CLOSE_HOUR,
            self.MARKET_CLOSE_MINUTE,
            tzinfo=IST,
        )
        self._clock.set_time(dt)
        return dt

    def advance_to_next_trading_day(self) -> date | None:
        """Move to the next trading day (skip weekends)."""
        next_day = self._current_trading_day + timedelta(days=1)
        while next_day.weekday() >= 5:  # Skip Saturday/Sunday
            next_day += timedelta(days=1)

        if self._end_date and next_day > self._end_date:
            return None  # Session complete

        self._current_trading_day = next_day
        self.advance_to_market_open()
        return next_day

    def is_within_session(self) -> bool:
        """Check if current time is within the simulation date range."""
        if self._end_date is None:
            return True
        return self._current_trading_day <= self._end_date

    def is_market_hours(self) -> bool:
        """Check if current virtual time is within market hours."""
        return self._clock.is_market_open()

    def get_progress(self) -> float:
        """Get simulation progress as 0.0 to 1.0."""
        if self._end_date is None or self._start_date == self._end_date:
            return 0.0
        total_days = (self._end_date - self._start_date).days
        elapsed_days = (self._current_trading_day - self._start_date).days
        if total_days <= 0:
            return 1.0
        return min(1.0, elapsed_days / total_days)

    def seek(self, target: datetime) -> None:
        """Jump to a specific time within the session."""
        if target.tzinfo is None:
            target = target.replace(tzinfo=IST)
        self._clock.set_time(target)
        self._current_trading_day = target.date()

    def set_speed(self, speed: float) -> None:
        """Set replay speed multiplier."""
        self._clock.set_speed(speed)

    def pause(self) -> None:
        self._clock.pause()

    def resume(self) -> None:
        self._clock.resume()

    def is_paused(self) -> bool:
        return self._clock.is_paused()
