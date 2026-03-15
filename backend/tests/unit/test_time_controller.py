"""
Tests for TimeController.
"""

from datetime import datetime



class TestTimeController:
    def test_set_date_range(self, time_controller):
        start = datetime(2025, 3, 10)
        end = datetime(2025, 3, 14)
        time_controller.set_date_range(start, end)
        now = time_controller.clock.now()
        assert now.replace(tzinfo=None).date() == start.date()

    def test_advance_to_market_open(self, time_controller):
        time_controller.set_date_range(datetime(2025, 3, 10), datetime(2025, 3, 10))
        time_controller.advance_to_market_open()
        now = time_controller.clock.now()
        assert now.hour == 9
        assert now.minute == 15

    def test_advance_to_market_close(self, time_controller):
        time_controller.set_date_range(datetime(2025, 3, 10), datetime(2025, 3, 10))
        time_controller.advance_to_market_close()
        now = time_controller.clock.now()
        assert now.hour == 15
        assert now.minute == 30

    def test_advance_to_next_trading_day_skips_weekend(self, time_controller):
        # Friday March 14, 2025
        time_controller.set_date_range(datetime(2025, 3, 14), datetime(2025, 3, 21))
        time_controller.advance_to_next_trading_day()
        now = time_controller.clock.now()
        assert now.replace(tzinfo=None).weekday() == 0  # Monday

    def test_is_market_hours(self, time_controller):
        time_controller.set_date_range(datetime(2025, 3, 10), datetime(2025, 3, 10))
        time_controller.advance_to_market_open()
        assert time_controller.is_market_hours() is True

    def test_get_progress(self, time_controller):
        time_controller.set_date_range(datetime(2025, 3, 10), datetime(2025, 3, 14))
        progress = time_controller.get_progress()
        assert 0.0 <= progress <= 1.0

    def test_pause_resume(self, time_controller):
        time_controller.pause()
        assert time_controller.clock.is_paused() is True
        time_controller.resume()
        assert time_controller.clock.is_paused() is False

    def test_set_speed(self, time_controller):
        time_controller.set_speed(5.0)
        assert time_controller.clock.get_speed() == 5.0
