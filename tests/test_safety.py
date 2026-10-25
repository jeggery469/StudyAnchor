"""The tests themselves must never touch the real hosts file, state file or diagnostics log."""
import os
import unittest

from support import REAL_DATA_DIR, REAL_HOSTS_PATH, IsolatedCore
import core


def same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class NeverTouchesRealFiles(unittest.TestCase):
    def test_paths_point_at_a_scratch_folder_even_outside_isolated_tests(self):
        self.assertFalse(same(core.DATA_DIR, REAL_DATA_DIR))
        self.assertFalse(same(core.HOSTS_PATH, REAL_HOSTS_PATH))
        self.assertFalse(same(os.path.dirname(core.STATE_PATH), REAL_DATA_DIR))
        self.assertFalse(same(os.path.dirname(core.log_path()), REAL_DATA_DIR))

    def test_logging_does_not_write_to_the_real_log(self):
        real_log = os.path.join(REAL_DATA_DIR, "focus.log")
        before = os.path.getsize(real_log) if os.path.exists(real_log) else None
        core.log_event("a test line that must never reach the real log")
        after = os.path.getsize(real_log) if os.path.exists(real_log) else None
        self.assertEqual(before, after)
        self.assertTrue(os.path.exists(core.log_path()))

    def test_a_simulated_launch_failure_logs_to_the_scratch_folder_only(self):
        from unittest import mock
        real_log = os.path.join(REAL_DATA_DIR, "focus.log")
        before = os.path.getsize(real_log) if os.path.exists(real_log) else None
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.Popen", side_effect=OSError):
            self.assertFalse(core.launch_app())
        after = os.path.getsize(real_log) if os.path.exists(real_log) else None
        self.assertEqual(before, after)

    def test_saving_state_goes_to_the_scratch_folder(self):
        core.save_state(core.default_state())
        self.assertTrue(os.path.exists(core.STATE_PATH))
        self.assertFalse(same(core.STATE_PATH, os.path.join(REAL_DATA_DIR, "state.json")))

    def test_writing_hosts_goes_to_the_scratch_file(self):
        core.set_hosts_block(core.default_state(), True)
        with open(core.HOSTS_PATH, encoding="utf-8") as f:
            self.assertIn(core.MARK_START, f.read())


class IsolatedCoreRestoresTheSafeDefaults(IsolatedCore):
    def test_inside_an_isolated_test_the_paths_are_per_test(self):
        self.assertTrue(same(core.DATA_DIR, self.tmp))
        self.assertFalse(same(core.DATA_DIR, REAL_DATA_DIR))


class AfterIsolatedTestStillSafe(unittest.TestCase):
    def test_paths_are_restored_to_the_session_scratch_not_the_real_folder(self):
        self.assertFalse(same(core.DATA_DIR, REAL_DATA_DIR))


if __name__ == "__main__":
    unittest.main()
