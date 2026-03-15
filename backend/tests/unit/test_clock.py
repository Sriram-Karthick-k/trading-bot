"""
Tests for VirtualClock, RealClock.
"""

from datetime import datetime, timedelta



class TestRealClock:
    def test_now_returns_current_time(self, real_clock):
        now = real_clock.now()
        assert isinstance(now, datetime)
        # Should be within a second of system time
        assert abs((datetime.now(now.tzinfo) - now).total_seconds()) < 2

    def test_today_returns_date(self, real_clock):
        today = real_clock.today()
        assert today == datetime.now().date()


class TestVirtualClock:
    def test_set_time(self, virtual_clock):
        target = datetime(2025, 3, 15, 9, 15, 0)
        virtual_clock.set_time(target)
        assert virtual_clock.now().replace(tzinfo=None) == target

    def test_advance(self, virtual_clock):
        before = virtual_clock.now()
        virtual_clock.advance(timedelta(minutes=30))
        after = virtual_clock.now()
        diff = (after - before).total_seconds()
        assert abs(diff - 1800) < 1

    def test_advance_to(self, virtual_clock):
        target = datetime(2025, 1, 15, 14, 0, 0)
        virtual_clock.advance_to(target)
        assert virtual_clock.now().replace(tzinfo=None) == target

    def test_speed_multiplier(self, virtual_clock):
        virtual_clock.set_speed(10.0)
        assert virtual_clock.get_speed() == 10.0

    def test_pause_resume(self, virtual_clock):
        virtual_clock.pause()
        assert virtual_clock.is_paused() is True
        virtual_clock.resume()
        assert virtual_clock.is_paused() is False

    def test_today(self, virtual_clock):
        virtual_clock.set_time(datetime(2025, 6, 20, 12, 0, 0))
        assert virtual_clock.today().day == 20
        assert virtual_clock.today().month == 6

    def test_tick(self, virtual_clock):
        before = virtual_clock.now()
        virtual_clock.tick()
        after = virtual_clock.now()
        assert after > before
