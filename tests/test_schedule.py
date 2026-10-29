import unittest
from datetime import datetime, timezone
from schedule import browse_allowed


class ScheduleTests(unittest.TestCase):
    def test_one_day_and_half_open_window_in_china_time(self):
        kw = {'timezone_name': 'Asia/Shanghai', 'windows': ['09:00-11:00'],
              'start_date': '2026-10-30', 'end_date': '2026-10-30'}
        self.assertFalse(browse_allowed(datetime(2026, 10, 30, 0, 59, tzinfo=timezone.utc), **kw))
        self.assertTrue(browse_allowed(datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc), **kw))
        self.assertFalse(browse_allowed(datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc), **kw))
        self.assertFalse(browse_allowed(datetime(2026, 10, 31, 1, 0, tzinfo=timezone.utc), **kw))

    def test_overnight_window_belongs_to_its_start_date(self):
        kw = {'timezone_name': 'Asia/Shanghai', 'windows': ['23:00-02:00'],
              'start_date': '2026-10-30', 'end_date': '2026-10-30'}
        self.assertTrue(browse_allowed(datetime(2026, 10, 30, 16, 30, tzinfo=timezone.utc), **kw))
        self.assertTrue(browse_allowed(datetime(2026, 10, 30, 17, 30, tzinfo=timezone.utc), **kw))
        self.assertFalse(browse_allowed(datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc), **kw))

    def test_empty_schedule_and_invalid_config(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(browse_allowed(now, timezone_name='Asia/Shanghai', windows=[]))
        with self.assertRaises(ValueError): browse_allowed(now, timezone_name='Bad/Zone', windows=[])
        for window in ('9:00-12:00', '09:00-09:00', '24:00-25:00'):
            with self.assertRaises(ValueError): browse_allowed(now, timezone_name='Asia/Shanghai', windows=[window])
        with self.assertRaises(ValueError):
            browse_allowed(now, timezone_name='Asia/Shanghai', windows=[], start_date='2026-11-01', end_date='2026-10-30')
