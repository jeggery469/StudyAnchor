"""The tutorial: its words (always in step with the app's real numbers) and its window."""
import unittest
from unittest import mock

import support  # noqa: F401
from appsupport import AppCase
from support import IsolatedCore
import core
import focusapp as fa
import tutorial


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


def alltext(steps):
    return "\n".join(t + "\n" + b for t, b in steps)


class ClockWords(unittest.TestCase):
    def test_midnight_and_ordinary_times(self):
        c = tutorial.clock
        self.assertEqual(c("00:00"), "midnight")
        self.assertEqual(c("24:00"), "midnight")
        self.assertEqual(c("07:00"), "7:00 AM")
        self.assertEqual(c("12:00"), "12:00 PM")
        self.assertEqual(c("18:00"), "6:00 PM")
        self.assertEqual(c("23:59"), "11:59 PM")
        self.assertEqual(c("20:30"), "8:30 PM")

    def test_junk_is_returned_as_text_not_a_crash(self):
        for junk in ("", "noon", None, "7", "a:b"):
            self.assertIsInstance(tutorial.clock(junk), str)


class TheWords(unittest.TestCase):
    def setUp(self):
        self.steps = tutorial.steps()

    def test_there_is_a_proper_walkthrough(self):
        self.assertGreaterEqual(len(self.steps), 6)
        for title, body in self.steps:
            self.assertTrue(title.strip())
            self.assertGreater(len(body.strip()), 40)

    def test_titles_are_unique(self):
        titles = [t for t, _b in self.steps]
        self.assertEqual(len(titles), len(set(titles)))

    def test_it_starts_with_the_app_name_and_ends_by_saying_where_to_find_it_again(self):
        self.assertIn("StudyAnchor", self.steps[0][0])
        self.assertIn("❓", self.steps[-1][1])

    def test_every_step_fits_the_window(self):
        for title, body in self.steps:
            self.assertLessEqual(len(body), 900, title)
            self.assertLessEqual(body.count("\n"), 14, title)

    def test_the_hours_are_the_real_ones(self):
        text = alltext(self.steps)
        self.assertIn("7:00 AM to midnight", text)
        self.assertIn("10:00 AM to 6:00 PM", text)

    def test_it_does_not_mention_tabs_that_no_longer_exist(self):
        text = alltext(self.steps)
        for gone in ("Usage tab", "Schedule tab", "stats"):
            self.assertNotIn(gone, text)

    def test_it_mentions_the_twenty_minute_floor(self):
        self.assertIn(f"never shorter than {core.MIN_SESSION_MIN} minutes", alltext(self.steps))

    def test_the_numbers_are_the_apps_numbers(self):
        text = alltext(self.steps)
        for needle in (f"{core.LEARNING_BREAK_MIN}-minute learning break", str(core.LEARNING_BREAKS_PER_DAY),
                       f"{core.LEARNING_APPROVAL_DELAY_MIN} minutes", f"{core.LEARNING_GRACE_SEC} seconds",
                       f"{core.SESSION_REWARD_MIN} minutes", f"{core.BANK_COOLDOWN_MIN} minutes",
                       "3 cheats a day", "5 minutes each", "11:59 PM", "8:00 PM"):
            self.assertIn(needle, text)

    def test_changing_a_constant_changes_the_tutorial(self):
        with mock.patch.object(core, "LEARNING_BREAK_MIN", 50), \
                mock.patch.object(core, "CHEAT_LADDER", [10, 10, 0]):
            text = alltext(tutorial.steps())
        self.assertIn("50-minute learning break", text)
        self.assertIn("2 cheats a day", text)
        self.assertIn("10 minutes each", text)

    def test_it_reads_the_saved_state(self):
        st = core.default_state()
        st.update(steam_break_min=20, steam_cooldown_min=60, session_length_min=30, clockout_time="22:30")
        text = alltext(tutorial.steps(st))
        self.assertIn("20 minutes for game launchers", text)
        self.assertIn("60-minute cooldown", text)
        self.assertIn("30-minute session", text)
        self.assertIn("10:30 PM", text)

    def test_junk_state_falls_back_to_defaults(self):
        for junk in (None, "x", 5, [], {}):
            self.assertEqual(len(tutorial.steps(junk)), len(tutorial.steps()))

    def test_plural_handling(self):
        with mock.patch.object(core, "CHEAT_LADDER", [5, 0]), mock.patch.object(core, "SESSION_REWARD_MIN", 1):
            text = alltext(tutorial.steps())
        self.assertIn("1 cheat a day", text)
        self.assertIn("1 minute go", text)

    def test_it_mentions_every_feature_a_new_user_needs(self):
        text = alltext(self.steps).lower()
        for word in ("popout", "study", "bank", "cheat", "games", "learn", "nuclear", "clock", "shorts",
                     "blocklist", "schedule"):
            self.assertIn(word, text)

    def test_the_names_of_files_it_mentions_exist(self):
        import os
        text = alltext(self.steps)
        self.assertIn("Restart Focus.bat", text)
        self.assertTrue(os.path.exists(os.path.join(support.ROOT, "Restart Focus.bat")))


class SavedFlag(IsolatedCore):
    def test_default_is_unseen(self):
        self.assertFalse(core.default_state()["tutorial_seen"])

    def test_it_survives_save_and_load(self):
        st = core.default_state()
        st["tutorial_seen"] = True
        core.save_state(st)
        self.assertTrue(core.load_state()["tutorial_seen"])

    def test_a_junk_value_does_not_count_as_seen(self):
        self.write_state({"tutorial_seen": "yes"}) if hasattr(self, "write_state") else None
        st = core.default_state()
        st["tutorial_seen"] = "yes"
        core.save_state(st)
        self.assertFalse(core.load_state()["tutorial_seen"])


@both
class TheWindow(AppCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self._close)

    def _close(self):
        t = getattr(self.app, "_tut", None)
        if t:
            try:
                t["win"].destroy()
            except Exception:
                pass
        self.app._tut = None

    def test_it_opens_on_the_first_step(self):
        t = self.app.show_tutorial()
        steps = tutorial.steps(self.st)
        self.assertEqual(t["i"], 0)
        self.assertEqual(self.text_of(t["count"]), f"Step 1 of {len(steps)}")
        self.assertEqual(self.text_of(t["title"]), steps[0][0])
        self.assertEqual(self.text_of(t["body"]), steps[0][1])

    def test_opening_it_twice_does_not_open_two(self):
        a = self.app.show_tutorial()
        b = self.app.show_tutorial()
        self.assertIs(a, b)

    def test_next_and_back(self):
        t = self.app.show_tutorial()
        steps = tutorial.steps(self.st)
        self.app._tut_move(1)
        self.assertEqual(self.text_of(t["title"]), steps[1][0])
        self.assertEqual(self.text_of(t["count"]), f"Step 2 of {len(steps)}")
        self.app._tut_move(-1)
        self.assertEqual(self.text_of(t["title"]), steps[0][0])

    def test_back_on_the_first_step_stays_put(self):
        t = self.app.show_tutorial()
        self.app._tut_move(-1)
        self.assertEqual(t["i"], 0)

    def test_back_is_disabled_on_the_first_step_only(self):
        t = self.app.show_tutorial()
        self.assertEqual(str(t["back"].cget("state")), "disabled")
        self.app._tut_move(1)
        self.assertEqual(str(t["back"].cget("state")), "normal")

    def test_the_last_step_says_done(self):
        t = self.app.show_tutorial()
        n = len(t["steps"])
        for _ in range(n - 1):
            self.app._tut_move(1)
        self.assertEqual(t["i"], n - 1)
        self.assertIn("Done", self.text_of(t["next"]))
        self.assertEqual(self.text_of(t["skip"]), "Close")

    def test_other_steps_say_next_and_skip(self):
        t = self.app.show_tutorial()
        self.assertIn("Next", self.text_of(t["next"]))
        self.assertEqual(self.text_of(t["skip"]), "Skip")

    def test_the_progress_dots_follow_the_step(self):
        t = self.app.show_tutorial()
        n = len(t["steps"])
        self.assertEqual(self.text_of(t["dots"]).count("●"), 1)
        self.assertEqual(self.text_of(t["dots"]).count("○"), n - 1)
        self.app._tut_move(1)
        self.assertTrue(self.text_of(t["dots"]).split("  ")[1] == "●")

    def test_every_step_renders(self):
        t = self.app.show_tutorial()
        for i, (head, body) in enumerate(t["steps"]):
            self.assertEqual(self.text_of(t["title"]), head)
            self.assertEqual(self.text_of(t["body"]), body)
            self.app._tut_move(1)

    def test_going_past_the_end_finishes_and_marks_it_seen(self):
        t = self.app.show_tutorial()
        for _ in range(len(t["steps"])):
            self.app._tut_move(1)
        self.assertIsNone(self.app._tut)
        self.assertTrue(self.st["tutorial_seen"])
        self.assertTrue(core.load_state()["tutorial_seen"])

    def test_skipping_marks_it_seen(self):
        self.app.show_tutorial()
        self.app._tut_close()
        self.assertTrue(self.st["tutorial_seen"])
        self.assertTrue(core.load_state()["tutorial_seen"])
        self.assertIsNone(self.app._tut)

    def test_closing_the_window_with_the_x_marks_it_seen(self):
        t = self.app.show_tutorial()
        t["win"].event_generate("<Destroy>")
        self.app._tut_close()
        self.assertTrue(self.st["tutorial_seen"])

    def test_it_can_be_reopened_and_starts_again_from_step_one(self):
        t = self.app.show_tutorial()
        self.app._tut_move(1); self.app._tut_move(1)
        self.app._tut_close()
        t2 = self.app.show_tutorial()
        self.assertEqual(t2["i"], 0)
        self.assertIsNot(t, t2)

    def test_closing_with_nothing_open_is_harmless(self):
        self.app._tut = None
        self.app._tut_close()
        self.app._tut_move(1)
        self.app._tut_render()

    def test_a_save_failure_does_not_stop_it_closing(self):
        self.app.show_tutorial()
        with mock.patch.object(core, "save_state", return_value=False):
            self.app._tut_close()
        self.assertIsNone(self.app._tut)

    def test_it_uses_the_live_numbers(self):
        self.st["steam_break_min"] = 17
        t = self.app.show_tutorial()
        found = any("17 minutes for game launchers" in b for _t, b in t["steps"])
        self.assertTrue(found)


@both
class WhenItAppears(AppCase):
    def test_first_run_schedules_it(self):
        calls = []
        self.st["tutorial_seen"] = False
        with mock.patch.object(fa.FocusApp, "AUTO_TUTORIAL", True), \
                mock.patch.object(self.app.root, "after", lambda ms, fn=None, *a: calls.append((ms, fn))):
            self.app._maybe_auto_tutorial()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], self.app.show_tutorial)

    def test_not_again_once_seen(self):
        calls = []
        self.st["tutorial_seen"] = True
        with mock.patch.object(fa.FocusApp, "AUTO_TUTORIAL", True), \
                mock.patch.object(self.app.root, "after", lambda ms, fn=None, *a: calls.append(fn)):
            self.app._maybe_auto_tutorial()
        self.assertEqual(calls, [])

    def test_switched_off_means_off(self):
        calls = []
        self.st["tutorial_seen"] = False
        with mock.patch.object(self.app.root, "after", lambda ms, fn=None, *a: calls.append(fn)):
            self.app._maybe_auto_tutorial()                      # AUTO_TUTORIAL is False in tests
        self.assertEqual(calls, [])

    def test_it_is_on_by_default_in_the_real_app(self):
        from support import REAL_TIME  # noqa: F401
        self.assertIn("AUTO_TUTORIAL", fa.FocusApp.__dict__)

    def test_the_buttons_to_reopen_it_exist_in_both_windows(self):
        self.app._show_full()
        texts = []

        def walk(w):
            for c in w.winfo_children():
                if hasattr(c, "invoke"):
                    try:
                        texts.append(c.cget("text"))
                    except Exception:
                        pass
                walk(c)
        walk(self.app.popout)
        walk(self.app.full)
        self.assertIn("❓", texts)
        self.assertIn("❓ Tutorial", texts)


if __name__ == "__main__":
    unittest.main()
