"""core: time-of-day logic (schedule, clock-out, nuclear, burnout, midnight)."""
import unittest
from datetime import datetime

from support import (IsolatedCore, MORNING, EVENING, NIGHT, EARLY, ts,        # noqa: F401
                     SAT_MORNING, SAT_EARLY, SAT_LATE, SUN_MORNING)
import core


class HhmmToMin(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(core._hhmm_to_min("00:00"), 0)
        self.assertEqual(core._hhmm_to_min("07:00"), 420)
        self.assertEqual(core._hhmm_to_min("23:59"), 1439)
        self.assertEqual(core._hhmm_to_min("7:5"), 425)

    def test_malformed_is_zero(self):
        for bad in ("", "abc", "12", "12:xx", None, "12:30:45", ":", "-1:00"):
            self.assertEqual(core._hhmm_to_min(bad), 0, bad)

    def test_out_of_range_is_zero(self):
        for bad in ("24:00", "25:10", "10:60", "10:99"):
            self.assertEqual(core._hhmm_to_min(bad), 0, bad)


class ScheduleHours(unittest.TestCase):
    def test_normal_window(self):
        self.assertEqual(core.schedule_hours("07:00", "22:00"), 15.0)
        self.assertEqual(core.schedule_hours("08:30", "09:00"), 0.5)

    def test_overnight_window(self):
        self.assertEqual(core.schedule_hours("22:00", "06:00"), 8.0)

    def test_equal_means_always_on(self):
        self.assertEqual(core.schedule_hours("07:00", "07:00"), 24.0)


class WithinSchedule(unittest.TestCase):
    def st(self, a, b):
        return {"schedule_start": a, "schedule_end": b}

    def test_default_window_boundaries(self):
        st = self.st("07:00", "22:00")
        self.assertFalse(core.within_schedule(st, ts(2026, 9, 23, 6, 59)))
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 23, 7, 0)))      # start inclusive
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 23, 21, 59)))
        self.assertFalse(core.within_schedule(st, ts(2026, 9, 23, 22, 0)))    # end exclusive
        self.assertFalse(core.within_schedule(st, ts(2026, 9, 23, 0, 0)))

    def test_overnight(self):
        st = self.st("22:00", "06:00")
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 23, 23, 0)))
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 23, 2, 0)))
        self.assertFalse(core.within_schedule(st, ts(2026, 9, 23, 12, 0)))
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 23, 22, 0)))
        self.assertFalse(core.within_schedule(st, ts(2026, 9, 23, 6, 0)))

    def test_equal_start_end_is_always(self):
        st = self.st("09:00", "09:00")
        for h in (0, 5, 9, 12, 23):
            self.assertTrue(core.within_schedule(st, ts(2026, 9, 23, h, 0)))

    def test_missing_keys_use_defaults(self):
        self.assertTrue(core.within_schedule({}, MORNING))
        self.assertFalse(core.within_schedule({}, NIGHT))

    def test_now_none_uses_real_clock(self):
        self.assertIn(core.within_schedule(self.st("00:00", "23:59")), (True, False))

    def test_now_zero_is_not_treated_as_missing(self):
        # regression: `now or time.time()` used to swallow an explicit 0
        st = self.st("07:00", "22:00")
        self.assertEqual(core.within_schedule(st, 0),
                         core.within_schedule(st, 0.0))
        lt = datetime.fromtimestamp(0)
        expect = 420 <= lt.hour * 60 + lt.minute < 1320
        self.assertEqual(core.within_schedule(st, 0), expect)


class IsWeekend(unittest.TestCase):
    def test_saturday_and_sunday_are_weekend(self):
        self.assertTrue(core.is_weekend(SAT_MORNING))
        self.assertTrue(core.is_weekend(SUN_MORNING))

    def test_weekdays_are_not(self):
        for t in (MORNING, EVENING, NIGHT, EARLY):
            self.assertFalse(core.is_weekend(t), t)


class TodaySchedule(unittest.TestCase):
    def test_picks_weekday_or_weekend_keys(self):
        st = core.default_state()
        self.assertEqual(core.today_schedule(st, MORNING), ("07:00", "00:00"))
        self.assertEqual(core.today_schedule(st, SAT_MORNING), ("10:00", "18:00"))
        self.assertEqual(core.today_schedule(st, SUN_MORNING), ("10:00", "18:00"))

    def test_custom_weekend_hours_are_used(self):
        st = core.default_state()
        st["weekend_schedule_start"], st["weekend_schedule_end"] = "12:00", "18:00"
        self.assertEqual(core.today_schedule(st, SAT_MORNING), ("12:00", "18:00"))
        self.assertEqual(core.today_schedule(st, MORNING), ("07:00", "00:00"))   # weekday untouched


class WithinScheduleWeekend(unittest.TestCase):
    def test_weekend_window_is_ten_to_six(self):
        st = core.default_state()
        self.assertFalse(core.within_schedule(st, SAT_EARLY))     # 08:00, before weekend start
        self.assertTrue(core.within_schedule(st, SAT_MORNING))    # 12:00, inside
        self.assertFalse(core.within_schedule(st, SAT_LATE))      # 19:00, after weekend end
        self.assertTrue(core.within_schedule(st, SUN_MORNING))

    def test_weekday_hours_do_not_leak_into_the_weekend(self):
        """08:00 and 19:00 are inside the WEEKDAY schedule (07:00-midnight) but outside the
        weekend one (10:00-18:00) — proves the two windows are actually independent, not the
        same check applied on both kinds of day."""
        st = core.default_state()
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 23, 8, 0)))    # weekday: blocked
        self.assertFalse(core.within_schedule(st, SAT_EARLY))              # weekend: free
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 23, 19, 0)))
        self.assertFalse(core.within_schedule(st, SAT_LATE))

    def test_boundaries_are_the_same_shape_as_weekdays(self):
        st = core.default_state()
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 26, 10, 0)))     # start inclusive
        self.assertTrue(core.within_schedule(st, ts(2026, 9, 26, 17, 59)))    # last minute inside
        self.assertFalse(core.within_schedule(st, ts(2026, 9, 26, 18, 0)))    # end exclusive

    def test_clockout_applies_on_weekends_too(self):
        st = core.default_state()
        self.assertFalse(core.clocked_out(st, SAT_MORNING))
        self.assertTrue(core.clocked_out(st, ts(2026, 9, 26, 23, 59)))

    def test_sites_blocked_respects_the_weekend_window(self):
        st = core.default_state()
        self.assertTrue(core.sites_blocked(st, SAT_MORNING))
        self.assertFalse(core.sites_blocked(st, SAT_EARLY))
        self.assertFalse(core.sites_blocked(st, SAT_LATE))

    def test_equal_start_end_weekend_is_always_on_like_weekdays(self):
        st = core.default_state()
        st["weekend_schedule_start"] = st["weekend_schedule_end"] = "09:00"
        for t in (SAT_EARLY, SAT_MORNING, SAT_LATE):
            self.assertTrue(core.within_schedule(st, t), t)


class NextScheduleStart(unittest.TestCase):
    def test_today_if_still_to_come(self):
        st = core.default_state()
        self.assertEqual(core.next_schedule_start(st, EARLY), "07:00")
        self.assertEqual(core.next_schedule_start(st, SAT_EARLY), "10:00")

    def test_tomorrows_window_once_todays_has_passed(self):
        st = core.default_state()
        self.assertEqual(core.next_schedule_start(st, NIGHT), "07:00")            # Wed night -> Thu 07:00

    def test_crossing_into_the_weekend(self):
        st = core.default_state()
        friday_night = ts(2026, 9, 25, 23, 0)
        self.assertEqual(core.next_schedule_start(st, friday_night), "10:00")     # Fri -> Sat weekend hours

    def test_crossing_out_of_the_weekend(self):
        st = core.default_state()
        self.assertEqual(core.next_schedule_start(st, SAT_LATE), "10:00")         # Sat -> Sun is STILL weekend
        sunday_night = ts(2026, 9, 27, 21, 0)
        self.assertEqual(core.next_schedule_start(st, sunday_night), "07:00")     # Sun -> Mon weekday hours


class LockedWeekendKeys(unittest.TestCase):
    def test_weekend_keys_are_locked_too(self):
        self.assertIn("weekend_schedule_start", core.LOCKED_KEYS)
        self.assertIn("weekend_schedule_end", core.LOCKED_KEYS)


class HoursRunToMidnight(unittest.TestCase):
    def test_default_hours(self):
        st = core.default_state()
        self.assertEqual((st["schedule_end"], st["weekend_schedule_end"], st["clockout_time"]),
                         ("00:00", "18:00", "23:59"))

    def test_weekday_is_blocked_late_in_the_evening(self):
        st = core.default_state()
        for hm in ((20, 30), (22, 30), (23, 30), (23, 58)):
            self.assertTrue(core.sites_blocked(st, ts(2026, 9, 23, *hm)), hm)

    def test_the_last_minute_is_the_clock_out_and_midnight_ends_it(self):
        st = core.default_state()
        self.assertFalse(core.sites_blocked(st, ts(2026, 9, 23, 23, 59, 30)))     # clocked out
        self.assertFalse(core.sites_blocked(st, ts(2026, 9, 24, 0, 0)))           # window over
        self.assertFalse(core.sites_blocked(st, ts(2026, 9, 24, 6, 59)))          # small hours free
        self.assertTrue(core.sites_blocked(st, ts(2026, 9, 24, 7, 0)))            # back on at 07:00

    def test_weekends_are_lighter_and_end_at_six(self):
        st = core.default_state()
        self.assertTrue(core.sites_blocked(st, ts(2026, 9, 26, 17, 30)))
        self.assertFalse(core.sites_blocked(st, ts(2026, 9, 26, 18, 0)))
        self.assertFalse(core.sites_blocked(st, ts(2026, 9, 27, 21, 0)))
        self.assertTrue(core.sites_blocked(st, ts(2026, 9, 28, 21, 0)))       # Monday evening: blocked again

    def test_midnight_end_is_not_mistaken_for_always_on(self):
        st = core.default_state()
        self.assertFalse(core.within_schedule(st, ts(2026, 9, 23, 3, 0)))


class ClockedOut(unittest.TestCase):
    def test_off_when_blank(self):
        self.assertFalse(core.clocked_out({"clockout_time": ""}, EVENING))
        self.assertFalse(core.clocked_out({}, EVENING))

    def test_boundary(self):
        st = {"clockout_time": "20:00"}
        self.assertFalse(core.clocked_out(st, ts(2026, 9, 23, 19, 59)))
        self.assertTrue(core.clocked_out(st, ts(2026, 9, 23, 20, 0)))
        self.assertTrue(core.clocked_out(st, ts(2026, 9, 23, 23, 59)))

    def test_resets_after_midnight(self):
        self.assertFalse(core.clocked_out({"clockout_time": "20:00"}, ts(2026, 9, 24, 0, 30)))


class Nuclear(unittest.TestCase):
    def test_active_and_expired(self):
        self.assertTrue(core.nuclear({"nuclear_until": MORNING + 60}, MORNING))
        self.assertFalse(core.nuclear({"nuclear_until": MORNING - 1}, MORNING))
        self.assertFalse(core.nuclear({}, MORNING))
        self.assertFalse(core.nuclear({"nuclear_until": MORNING}, MORNING))   # exclusive


class Burnout(unittest.TestCase):
    def test_cap(self):
        self.assertFalse(core.burnout({"daily_study_cap_min": 240, "studied_today_min": 239}))
        self.assertTrue(core.burnout({"daily_study_cap_min": 240, "studied_today_min": 240}))
        self.assertTrue(core.burnout({"daily_study_cap_min": 240, "studied_today_min": 500}))

    def test_zero_cap_is_off(self):
        self.assertFalse(core.burnout({"daily_study_cap_min": 0, "studied_today_min": 9999}))
        self.assertFalse(core.burnout({}))


class NextMidnight(unittest.TestCase):
    def test_is_next_local_midnight(self):
        got = datetime.fromtimestamp(core.next_midnight(ts(2026, 9, 23, 15, 45)))
        self.assertEqual((got.year, got.month, got.day, got.hour, got.minute), (2026, 9, 24, 0, 0))

    def test_just_before_midnight(self):
        got = datetime.fromtimestamp(core.next_midnight(ts(2026, 9, 23, 23, 59, 59)))
        self.assertEqual((got.month, got.day, got.hour), (9, 24, 0))

    def test_exactly_midnight_goes_to_the_following_one(self):
        got = datetime.fromtimestamp(core.next_midnight(ts(2026, 9, 24, 0, 0, 0)))
        self.assertEqual((got.month, got.day), (9, 25))

    def test_month_and_year_rollover(self):
        got = datetime.fromtimestamp(core.next_midnight(ts(2026, 12, 31, 12, 0)))
        self.assertEqual((got.year, got.month, got.day), (2027, 1, 1))


if __name__ == "__main__":
    unittest.main()
