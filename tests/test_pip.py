"""Picture-in-Picture: browser video pop-out windows are closed while sites are blocked.
Nothing here touches a real browser window: enumeration/closing is patched in the app tests, and the
real Win32 enumeration is exercised against a scratch window this test process owns."""
import unittest
from unittest import mock

from appsupport import AppCase
from support import IsolatedCore, MORNING, EVENING, NIGHT, SAT_MORNING
import core
import focusapp as fa

WIN = core.IS_WIN


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


class PipTitles(unittest.TestCase):
    def test_the_browser_window_titles_match(self):
        for t in ("Picture in picture", "picture in picture", "Picture-in-Picture", "  Picture   in picture "):
            self.assertTrue(fa.is_pip_title(t), t)

    def test_normal_windows_never_match(self):
        for t in ("", "YouTube - Google Chrome", "How to use picture in picture - Google Chrome",
                  "Picture in picture settings", "picture in picture - youtube", "Picture", "pip"):
            self.assertFalse(fa.is_pip_title(t), t)

    def test_non_strings_are_safe(self):
        self.assertFalse(fa.is_pip_title(None))


class PolicyFollowsBlocking(IsolatedCore):
    def test_blocked_during_work_hours(self):
        self.assertTrue(core.pip_blocked(core.default_state(), MORNING))

    def test_allowed_in_free_time(self):
        st = core.default_state()
        self.assertFalse(core.pip_blocked(st, EVENING))           # clocked out
        self.assertFalse(core.pip_blocked(st, NIGHT))             # outside the schedule

    def test_allowed_during_a_break_but_not_nuclear(self):
        st = core.default_state()
        st["unlock_until"] = MORNING + 600
        self.assertFalse(core.pip_blocked(st, MORNING + 1))
        st["nuclear_until"] = MORNING + 600
        self.assertTrue(core.pip_blocked(st, MORNING + 1))

    def test_still_blocked_in_learning_and_audiobook_modes(self):
        st = core.default_state()
        st["learning_until"] = MORNING + 600
        self.assertTrue(core.pip_blocked(st, MORNING + 1))
        st["learning_until"] = 0
        st["learning_approved"] = [{"phrase": "dune audiobook", "added": MORNING - 99999, "always": True}]
        self.assertTrue(core.youtube_open(st, MORNING))
        self.assertTrue(core.pip_blocked(st, MORNING))


@both
class ClosingPip(AppCase):
    def test_a_pip_window_is_closed_during_work_hours(self):
        self.env.pip.append(1234)
        self.tick(3)
        self.assertEqual(self.env.pip_closed, [1234])

    def test_it_closes_only_what_was_found(self):
        self.env.pip.extend([11, 22])
        self.tick(3)
        self.assertEqual(sorted(self.env.pip_closed), [11, 22])

    def test_no_pip_window_nothing_closed(self):
        self.tick(5)
        self.assertEqual(self.env.pip_closed, [])

    def test_never_uses_keystrokes(self):
        self.env.pip.append(5)
        self.tick(5)
        self.assertEqual(self.ctrl_w, [])

    def test_free_time_leaves_it_alone(self):
        self.set_time(EVENING)
        self.env.pip.append(7)
        self.tick(5)
        self.assertEqual(self.env.pip_closed, [])

    def test_a_break_leaves_it_alone(self):
        self.st["unlock_until"] = self.fake.now + 600
        self.env.pip.append(7)
        self.tick(5)
        self.assertEqual(self.env.pip_closed, [])

    def test_the_end_of_a_break_closes_it(self):
        self.st["unlock_until"] = self.fake.now + 3
        self.env.pip.append(7)
        self.tick(2)
        self.assertEqual(self.env.pip_closed, [])
        self.tick(5)
        self.assertTrue(self.env.pip_closed)

    def test_closed_even_during_a_learning_break(self):
        self.st["learning_until"] = self.fake.now + 600
        self.env.pip.append(9)
        self.tick(3)
        self.assertEqual(self.env.pip_closed, [9])

    def test_closed_even_in_audiobook_mode(self):
        self.st["learning_approved"] = [{"phrase": "dune audiobook", "added": self.fake.now - 99999,
                                         "always": True}]
        self.env.pip.append(9)
        self.tick(3)
        self.assertEqual(self.env.pip_closed, [9])

    def test_the_sweep_is_throttled(self):
        calls = []
        with mock.patch.object(fa, "find_pip_windows", lambda: calls.append(1) or []):
            self.tick(10)
        self.assertLessEqual(len(calls), 6)
        self.assertGreaterEqual(len(calls), 3)

    def test_free_time_skips_the_window_scan_entirely(self):
        self.set_time(NIGHT)
        calls = []
        with mock.patch.object(fa, "find_pip_windows", lambda: calls.append(1) or []):
            self.tick(10)
        self.assertEqual(calls, [])

    def test_each_close_is_logged(self):
        with mock.patch.object(core, "log_event") as log:
            self.env.pip.append(3)
            self.tick(3)
        self.assertTrue(any("Picture-in-Picture" in str(c) for c in log.call_args_list))


@unittest.skipUnless(WIN, "Win32 window enumeration")
class RealEnumeration(unittest.TestCase):
    """Uses a hidden-from-nobody scratch window owned by THIS process, titled like a PiP window."""
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.root.title("Picture in picture")
        self.root.geometry("40x40+5000+5000")           # off-screen
        self.root.update()
        self.closed = []
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.closed.append(1))

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_ignored_when_the_owner_is_not_a_browser(self):
        # whatever else is open on the real desktop (a real browser's Picture-in-Picture, say), every
        # owner is reported as "not a browser" here, so nothing may be found
        with mock.patch.object(fa, "_pid_name", return_value="notabrowser.exe"):
            self.assertEqual(fa.find_pip_windows(), [])

    def test_found_when_the_owner_is_a_browser(self):
        import os
        me = os.path.basename(fa._pid_name_uncached(os.getpid())).lower()
        with mock.patch.object(fa, "BROWSERS", {me}):
            fa._PID_CACHE.clear()
            found = fa.find_pip_windows()
        self.assertTrue(found)

    def test_close_window_sends_a_close_request_to_that_window_only(self):
        import os
        me = os.path.basename(fa._pid_name_uncached(os.getpid())).lower()
        with mock.patch.object(fa, "BROWSERS", {me}):
            fa._PID_CACHE.clear()
            found = fa.find_pip_windows()
        self.assertTrue(found)
        import ctypes
        own = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        self.assertIn(own, found)
        fa.close_window(own)                       # only this test's own window, never "whatever was found"
        for _ in range(20):
            self.root.update()
        self.assertEqual(self.closed, [1])

    def test_a_normal_title_is_not_found(self):
        import os
        self.root.title("How to use picture in picture - Google Chrome")
        self.root.update()
        me = os.path.basename(fa._pid_name_uncached(os.getpid())).lower()
        with mock.patch.object(fa, "BROWSERS", {me}):
            self.assertEqual(fa.find_pip_windows(), [])


class WindowsOnlyGuards(unittest.TestCase):
    def test_noops_off_windows(self):
        with mock.patch.object(core, "IS_WIN", False):
            self.assertEqual(fa.find_pip_windows(), [])
            fa.close_window(1)

    @unittest.skipUnless(WIN, "Win32")
    def test_enumeration_errors_give_an_empty_list(self):
        with mock.patch.object(fa, "user32") as u:
            u.EnumWindows.side_effect = OSError
            self.assertEqual(fa.find_pip_windows(), [])

    @unittest.skipUnless(WIN, "Win32")
    def test_close_errors_are_swallowed(self):
        with mock.patch.object(fa, "user32") as u:
            u.PostMessageW.side_effect = OSError
            fa.close_window(1)
            u.PostMessageW.side_effect = None
            fa.close_window(42)
            u.PostMessageW.assert_called_with(42, fa.WM_CLOSE, 0, 0)


if __name__ == "__main__":
    unittest.main()
