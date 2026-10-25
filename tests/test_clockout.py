"""Clocking out early: from 20:00 you may call it a night; otherwise the clock-out is 23:59."""
import unittest
from unittest import mock

from appsupport import AppCase
from support import IsolatedCore, MORNING, EVENING, NIGHT, SAT_LATE, ts
import core
import focusapp as fa

D = (2026, 9, 23)            # a Wednesday
AT_7_59 = ts(*D, 19, 59)
AT_8 = ts(*D, 20, 0)
AT_9 = ts(*D, 21, 0)
AT_11_58 = ts(*D, 23, 58)


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


class OptionWindow(IsolatedCore):
    def test_not_before_eight(self):
        st = core.default_state()
        for t in (MORNING, ts(*D, 15, 0), AT_7_59):
            self.assertFalse(core.clockout_option_available(st, t), t)

    def test_open_from_eight_until_the_automatic_clock_out(self):
        st = core.default_state()
        for t in (AT_8, AT_9, AT_11_58):
            self.assertTrue(core.clockout_option_available(st, t), t)
        self.assertFalse(core.clockout_option_available(st, EVENING))        # 23:59:30: already clocked out

    def test_nothing_to_clock_out_of_in_free_time(self):
        st = core.default_state()
        self.assertFalse(core.clockout_option_available(st, NIGHT))
        self.assertFalse(core.clockout_option_available(st, SAT_LATE))       # weekends end at 18:00

    def test_never_during_nuclear(self):
        st = core.default_state()
        st["nuclear_until"] = AT_9 + 3600
        self.assertFalse(core.clockout_option_available(st, AT_9))
        self.assertFalse(core.clock_out(st, AT_9))
        self.assertEqual(st["clockout_manual_at"], 0.0)
        self.assertTrue(core.sites_blocked(st, AT_9))

    def test_an_automatic_clock_out_turned_off_still_allows_the_option(self):
        st = core.default_state()
        st["clockout_time"] = ""
        self.assertTrue(core.clockout_option_available(st, AT_9))
        self.assertTrue(core.clock_out(st, AT_9))
        self.assertTrue(core.clocked_out(st, AT_9 + 1))


class ClockingOut(IsolatedCore):
    def test_clocking_out_frees_the_evening(self):
        st = core.default_state()
        self.assertTrue(core.sites_blocked(st, AT_9))
        self.assertTrue(core.clock_out(st, AT_9))
        self.assertEqual(st["clockout_manual_at"], AT_9)
        self.assertTrue(core.clocked_out(st, AT_9 + 1))
        self.assertFalse(core.sites_blocked(st, AT_9 + 1))
        self.assertFalse(core.steam_blocked(st, AT_9 + 1))

    def test_it_cannot_be_done_early(self):
        st = core.default_state()
        self.assertFalse(core.clock_out(st, AT_7_59))
        self.assertEqual(st["clockout_manual_at"], 0.0)
        self.assertTrue(core.sites_blocked(st, AT_7_59))

    def test_it_lapses_at_midnight_and_does_not_carry_over(self):
        st = core.default_state()
        core.clock_out(st, AT_9)
        tomorrow_morning = ts(2026, 9, 24, 10, 0)
        self.assertFalse(core.clocked_out(st, tomorrow_morning))
        self.assertTrue(core.sites_blocked(st, tomorrow_morning))
        tomorrow_9pm = ts(2026, 9, 24, 21, 0)
        self.assertFalse(core.clocked_out(st, tomorrow_9pm))                 # yesterday's choice is gone
        self.assertTrue(core.clockout_option_available(st, tomorrow_9pm))

    def test_a_faked_early_value_does_not_count(self):
        st = core.default_state()
        st["clockout_manual_at"] = ts(*D, 9, 0)                              # hand-edited: 9 in the morning
        self.assertFalse(core.clocked_out(st, MORNING + 3600))
        self.assertTrue(core.sites_blocked(st, MORNING + 3600))
        st["clockout_manual_at"] = ts(*D, 19, 59)
        self.assertFalse(core.clocked_out(st, AT_8 - 30))

    def test_a_future_value_does_not_count(self):
        st = core.default_state()
        st["clockout_manual_at"] = ts(*D, 22, 0)
        self.assertFalse(core.clocked_out(st, AT_9))

    def test_junk_values_do_not_count(self):
        st = core.default_state()
        for junk in ("yes", None, True, -5, [1], float("nan"), float("inf"), 1e30, -1e30):
            st["clockout_manual_at"] = junk
            self.assertFalse(core.manual_clockout_active(st, AT_9), junk)

    def test_the_automatic_clock_out_is_unchanged(self):
        st = core.default_state()
        self.assertFalse(core.clocked_out(st, AT_11_58))
        self.assertTrue(core.clocked_out(st, EVENING))

    def test_it_survives_save_and_load(self):
        st = core.default_state()
        core.clock_out(st, AT_9)
        self.assertTrue(core.save_state(st))
        got = core.load_state()
        self.assertEqual(got["clockout_manual_at"], AT_9)
        self.assertTrue(core.clocked_out(got, AT_9 + 5))

    def test_the_default_is_off(self):
        self.assertEqual(core.default_state()["clockout_manual_at"], 0.0)
        self.assertFalse(core.manual_clockout_active(core.default_state(), AT_9))


@both
class ClockOutInTheApp(AppCase):
    def evening(self, t=AT_9):
        self.set_time(t)
        self.app._clocked_prev = False
        self.app._last_render = None

    def test_the_popout_button_appears_at_eight_and_not_before(self):
        self.set_time(AT_7_59); self.app._last_render = None
        self.app.refresh_ui()
        self.assertFalse(self.app._m_r4_shown)
        self.set_time(AT_8); self.app._last_render = None
        self.app.refresh_ui()
        self.assertTrue(self.app._m_r4_shown)
        self.assertTrue(self.app.m_r4.winfo_manager())

    def test_the_popout_grows_to_fit_the_button(self):
        self.set_time(AT_8); self.app._last_render = None
        self.app.refresh_ui()
        self.app.popout.update()
        need, got = self.app.popout.winfo_reqheight(), self.app.popout.winfo_height()
        self.assertGreater(need, 0)
        self.assertGreaterEqual(got, need - 2)               # nothing cut off...
        self.assertLessEqual(got, need + 14)                 # ...and no big empty gap under the button

    def test_the_popout_shrinks_back_when_the_button_goes(self):
        self.set_time(AT_8); self.app._last_render = None
        self.app.refresh_ui()
        self.app.popout.update()
        tall = self.app.popout.winfo_height()
        self.set_time(AT_7_59); self.app._last_render = None
        self.app.refresh_ui()
        self.app.popout.update()
        self.assertLess(self.app.popout.winfo_height(), tall)

    def test_the_button_goes_away_after_clocking_out(self):
        self.evening()
        self.app.refresh_ui()
        self.assertTrue(self.app._m_r4_shown)
        self.assertTrue(self.app._do_clock_out())
        self.assertFalse(self.app._m_r4_shown)
        self.assertFalse(self.app.m_r4.winfo_manager())

    def test_clock_out_before_eight_says_not_yet(self):
        self.set_time(AT_7_59)
        self.app.clock_out()
        self.assertEqual(self.popup_titles(), ["Not yet"])
        self.assertIn("20:00", self.popups[0][1])
        self.assertEqual(self.st["clockout_manual_at"], 0.0)

    def test_clock_out_when_already_free(self):
        self.set_time(NIGHT)
        self.app.clock_out()
        self.assertEqual(self.popup_titles(), ["Already free"])
        self.set_time(EVENING)
        self.popups.clear()
        self.app.clock_out()
        self.assertEqual(self.popup_titles(), ["Already free"])

    def test_clock_out_is_refused_during_nuclear(self):
        self.evening()
        self.st["nuclear_until"] = AT_9 + 3600
        self.app.clock_out()
        self.assertEqual(self.popup_titles(), ["☢ Nuclear lockdown"])
        self.assertEqual(self.st["clockout_manual_at"], 0.0)

    def test_clock_out_is_refused_mid_session(self):
        self.evening()
        self.app.session_active = True
        self.app.clock_out()
        self.assertEqual(self.popup_titles(), ["You're in a session"])
        self.assertEqual(self.st["clockout_manual_at"], 0.0)

    def test_it_asks_before_clocking_out(self):
        self.evening()
        dialogs = []
        real = fa.WToplevel

        def make(*a, **k):
            d = real(*a, **k)
            dialogs.append(d)
            return d
        with mock.patch.object(fa, "WToplevel", make):
            self.app.clock_out()
        self.assertEqual(len(dialogs), 1)
        self.assertEqual(self.st["clockout_manual_at"], 0.0)                 # nothing happens until you say yes
        dialogs[0].destroy()

    def test_confirming_clocks_out_and_unblocks(self):
        self.evening()
        self.assertTrue(core.sites_blocked(self.st, self.fake.now))
        self.assertTrue(self.app._do_clock_out())
        self.assertEqual(self.st["clockout_manual_at"], self.fake.now)
        self.assertFalse(core.sites_blocked(self.st, self.fake.now))
        self.assertEqual(self.enforced, [False])                              # hosts updated right away
        self.assertEqual(core.load_state()["clockout_manual_at"], self.fake.now)   # and saved

    def test_confirming_twice_is_harmless(self):
        self.evening()
        self.assertTrue(self.app._do_clock_out())
        first = self.st["clockout_manual_at"]
        self.fake.advance(30)
        self.assertFalse(self.app._do_clock_out())
        self.assertEqual(self.st["clockout_manual_at"], first)

    def test_status_shows_clocked_out_and_it_is_announced_once(self):
        self.evening()
        self.app._do_clock_out()
        self.assertEqual(self.app._status()[0], "🕗 CLOCKED OUT")
        self.tick(2)
        self.assertEqual(self.chimes, [1])
        self.tick(5)
        self.assertEqual(self.chimes, [1])

    def test_youtube_rules_stand_down_after_clocking_out(self):
        self.evening()
        self.st["learning_approved"] = [{"phrase": "dune audiobook", "added": self.fake.now - 99999, "always": True}]
        self.assertTrue(core.youtube_open(self.st, self.fake.now))
        self.app._do_clock_out()
        self.assertFalse(core.youtube_open(self.st, self.fake.now))
        self.set_fg("chrome.exe", "funny cat compilation - youtube - google chrome")
        self.tick(40)
        self.assertEqual(self.ctrl_w, [])
        self.assertEqual(self.env.pip_closed, [])

    def test_a_blocked_tab_is_still_closed_before_clocking_out(self):
        self.evening()
        self.set_fg("chrome.exe", "reddit - front page - google chrome")
        self.tick(3)
        self.assertGreaterEqual(len(self.ctrl_w), 1)

    def test_tomorrow_everything_is_blocked_again(self):
        self.evening()
        self.app._do_clock_out()
        self.set_time(ts(2026, 9, 24, 10, 0))
        self.assertTrue(core.sites_blocked(self.st, self.fake.now))
        self.assertEqual(self.app._status()[0], "🔒 LOCKED IN")

    def test_the_option_is_announced_once_a_day(self):
        self.evening(AT_8 - 2)
        self.tick(5)                                                          # crosses 20:00
        self.assertEqual(self.popup_titles(), ["🕗 You can clock out"])
        self.tick(30)
        self.assertEqual(self.popup_titles(), ["🕗 You can clock out"])

    def test_nothing_is_announced_before_eight(self):
        self.set_time(MORNING)
        self.tick(5)
        self.assertEqual(self.popups, [])

    def test_the_full_window_has_a_clock_out_button(self):
        self.app._show_full()
        found = []

        def walk(w):
            for c in w.winfo_children():
                if hasattr(c, "invoke"):
                    try:
                        found.append(c.cget("text"))
                    except Exception:
                        pass
                walk(c)
        walk(self.app.full)
        self.assertIn("🕗 Clock out", found)


if __name__ == "__main__":
    unittest.main()
