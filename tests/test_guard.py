"""guard.py: the headless enforcer run by the scheduled task."""
import unittest
from unittest import mock

from support import IsolatedCore
import core
import guard


class GuardMain(IsolatedCore):
    def setUp(self):
        super().setUp()
        self.p = [mock.patch("os.name", "nt")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        super().tearDown()

    def test_not_admin_relaunches_elevated_and_does_nothing_else(self):
        with mock.patch.object(core, "is_admin", return_value=False), \
                mock.patch.object(core, "relaunch_as_admin") as relaunch, \
                mock.patch.object(core, "apply_enforcement") as apply:
            self.assertEqual(guard.main([]), "relaunched")
            relaunch.assert_called_once()
            apply.assert_not_called()

    def test_off_flag_removes_blocking(self):
        core.set_hosts_block(self.state(), True)
        with mock.patch.object(core, "is_admin", return_value=True):
            self.assertEqual(guard.main(["guard.py", "--off"]), "off")
        self.assertNotIn(core.MARK_START, self.hosts())

    def test_enforces_and_relaunches_a_closed_app(self):
        with mock.patch.object(core, "is_admin", return_value=True), \
                mock.patch.object(core, "apply_enforcement") as apply, \
                mock.patch.object(core, "app_running", return_value=False), \
                mock.patch.object(core, "launch_app") as launch:
            self.assertEqual(guard.main([]), "enforced+launched")
            apply.assert_called_once()
            launch.assert_called_once()

    def test_does_not_start_a_second_copy(self):
        with mock.patch.object(core, "is_admin", return_value=True), \
                mock.patch.object(core, "apply_enforcement"), \
                mock.patch.object(core, "app_running", return_value=True), \
                mock.patch.object(core, "launch_app") as launch:
            self.assertEqual(guard.main([]), "enforced")
            launch.assert_not_called()

    def test_a_failing_launch_check_never_crashes_the_guard(self):
        with mock.patch.object(core, "is_admin", return_value=True), \
                mock.patch.object(core, "apply_enforcement"), \
                mock.patch.object(core, "app_running", side_effect=OSError):
            self.assertEqual(guard.main([]), "enforced")

    def test_end_to_end_writes_the_real_block_into_the_temp_hosts(self):
        import support
        with mock.patch.object(core, "is_admin", return_value=True), \
                mock.patch.object(core, "app_running", return_value=True), \
                mock.patch.object(core.time, "time", return_value=support.MORNING):
            guard.main([])
        self.assertIn(core.MARK_START, self.hosts())


class GuardOffWindows(unittest.TestCase):
    def test_unsupported_platform(self):
        with mock.patch("os.name", "posix"):
            self.assertEqual(guard.main([]), "unsupported")


if __name__ == "__main__":
    unittest.main()
