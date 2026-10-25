"""core: the block/unblock decision (sites_blocked, steam_blocked) and apply_enforcement."""
import itertools
import unittest
from unittest import mock

from support import IsolatedCore, MORNING, EVENING, NIGHT, EARLY
import core


class SitesBlocked(unittest.TestCase):
    def st(self, **kw):
        s = core.default_state()
        s.update(kw)
        return s

    def test_blocked_by_default_during_the_day(self):
        self.assertTrue(core.sites_blocked(self.st(), MORNING))

    def test_free_outside_schedule(self):
        self.assertFalse(core.sites_blocked(self.st(), NIGHT))
        self.assertFalse(core.sites_blocked(self.st(), EARLY))

    def test_free_after_clock_out(self):
        self.assertFalse(core.sites_blocked(self.st(), EVENING))

    def test_blank_clockout_keeps_blocking_until_schedule_end(self):
        self.assertTrue(core.sites_blocked(self.st(clockout_time=""), EVENING))

    def test_only_an_active_break_frees_you_inside_the_schedule(self):
        self.assertFalse(core.sites_blocked(self.st(unlock_until=MORNING + 60), MORNING))
        self.assertTrue(core.sites_blocked(self.st(unlock_until=MORNING - 1), MORNING))
        self.assertTrue(core.sites_blocked(self.st(unlock_until=MORNING), MORNING))   # exclusive

    def test_legacy_flags_from_old_state_files_do_not_create_gaps(self):
        self.assertTrue(core.sites_blocked(self.st(enabled=False), MORNING))
        self.assertTrue(core.sites_blocked(self.st(day_off_until=MORNING + 9999), MORNING))

    def test_nuclear_beats_everything(self):
        nuke = MORNING + 3600
        for now in (MORNING, EVENING, NIGHT, EARLY):
            st = self.st(nuclear_until=nuke + (now - MORNING) + 10, unlock_until=now + 9999)
            self.assertTrue(core.sites_blocked(st, now), now)

    def test_expired_nuclear_does_nothing(self):
        self.assertFalse(core.sites_blocked(self.st(nuclear_until=NIGHT - 1), NIGHT))

    def test_exhaustive_truth_table(self):
        """Every combination of {nuclear, in-schedule, clocked-out, break} against the rule."""
        for nuke, in_sched, clocked, brk in itertools.product((0, 1), repeat=4):
            now = MORNING
            st = self.st()
            st["schedule_start"], st["schedule_end"] = ("06:00", "23:00") if in_sched else ("11:00", "12:00")
            st["clockout_time"] = "09:00" if clocked else "23:30"
            st["unlock_until"] = now + 100 if brk else 0
            st["nuclear_until"] = now + 100 if nuke else 0
            expect = bool(nuke) or (bool(in_sched) and not clocked and not brk)
            self.assertEqual(core.sites_blocked(st, now), expect, (nuke, in_sched, clocked, brk))


class SteamBlocked(unittest.TestCase):
    def st(self, **kw):
        s = core.default_state()
        s.update(kw)
        return s

    def test_blocked_by_default_during_the_day(self):
        self.assertTrue(core.steam_blocked(self.st(), MORNING))

    def test_free_outside_hours_and_after_clock_out(self):
        self.assertFalse(core.steam_blocked(self.st(), NIGHT))
        self.assertFalse(core.steam_blocked(self.st(), EVENING))

    def test_only_a_gaming_break_frees_it(self):
        self.assertFalse(core.steam_blocked(self.st(steam_break_until=MORNING + 60), MORNING))
        # a web break does NOT free the launchers
        self.assertTrue(core.steam_blocked(self.st(unlock_until=MORNING + 60), MORNING))

    def test_nuclear_beats_a_gaming_break(self):
        st = self.st(steam_break_until=MORNING + 600, nuclear_until=MORNING + 600)
        self.assertTrue(core.steam_blocked(st, MORNING))


class ApplyEnforcement(IsolatedCore):
    def test_writes_block_when_blocked(self):
        core.apply_enforcement(self.state(), MORNING)
        self.assertIn(core.MARK_START, self.hosts())
        self.assertIn("0.0.0.0 youtube.com", self.hosts())

    def test_removes_block_when_free(self):
        core.apply_enforcement(self.state(), MORNING)
        core.apply_enforcement(self.state(), NIGHT)
        self.assertNotIn(core.MARK_START, self.hosts())
        self.assertEqual(self.hosts().strip(), "127.0.0.1 localhost")

    def test_break_lifts_then_relocks(self):
        st = self.state()
        core.apply_enforcement(st, MORNING)
        st["unlock_until"] = MORNING + 300
        core.apply_enforcement(st, MORNING + 1)
        self.assertNotIn(core.MARK_START, self.hosts())
        core.apply_enforcement(st, MORNING + 301)
        self.assertIn(core.MARK_START, self.hosts())

    def test_kills_launchers_only_while_blocked(self):
        with mock.patch.object(core, "kill_game_launchers") as kill:
            core.apply_enforcement(self.state(), MORNING)
            self.assertEqual(kill.call_count, 1)
            core.apply_enforcement(self.state(), NIGHT)
            self.assertEqual(kill.call_count, 1)
            core.apply_enforcement(self.state(steam_break_until=MORNING + 60), MORNING)
            self.assertEqual(kill.call_count, 1)

    def test_idempotent_no_rewrite_when_nothing_changed(self):
        core.apply_enforcement(self.state(), MORNING)
        with mock.patch.object(core, "_write_hosts") as w, mock.patch.object(core, "flush_dns") as f:
            core.apply_enforcement(self.state(), MORNING + 5)
            w.assert_not_called()
            f.assert_not_called()


if __name__ == "__main__":
    unittest.main()
