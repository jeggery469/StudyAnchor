"""core: process gating, single-instance mutex, elevation helpers, launching."""
import os
import sys
import subprocess
import unittest
from unittest import mock

from support import IsolatedCore
import core

WIN = core.IS_WIN


@unittest.skipUnless(WIN, "Windows process snapshot")
class RunningProcessNames(unittest.TestCase):
    def test_sees_this_python_process(self):
        names = core._running_process_names()
        self.assertIsInstance(names, set)
        self.assertTrue(any(n.startswith("python") for n in names), sorted(names)[:10])
        self.assertTrue(all(n == n.lower() for n in names))

    def test_is_fast_and_spawns_nothing(self):
        import time
        with mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen:
            t = time.perf_counter()
            core._running_process_names()
            self.assertLess(time.perf_counter() - t, 0.5)
            run.assert_not_called()
            popen.assert_not_called()


class KillGameLaunchers(IsolatedCore):
    def setUp(self):
        super().setUp()
        self.p_win = mock.patch.object(core, "IS_WIN", True)
        self.p_win.start()

    def tearDown(self):
        self.p_win.stop()
        super().tearDown()

    def test_only_targets_launchers_that_are_running(self):
        with mock.patch.object(core, "_running_process_names", return_value={"steam.exe", "chrome.exe"}), \
                mock.patch("subprocess.run") as run:
            core.kill_game_launchers(force=True)
            args = run.call_args[0][0]
            self.assertEqual(args[:2], ["taskkill", "/F"])
            self.assertEqual(args[2:], ["/IM", "steam.exe"])

    def test_case_insensitive_match(self):
        with mock.patch.object(core, "_running_process_names", return_value={"epicgameslauncher.exe"}), \
                mock.patch("subprocess.run") as run:
            core.kill_game_launchers(force=True)
            self.assertIn("EpicGamesLauncher.exe", run.call_args[0][0])

    def test_no_launcher_running_means_no_subprocess(self):
        with mock.patch.object(core, "_running_process_names", return_value={"chrome.exe"}), \
                mock.patch("subprocess.run") as run:
            core.kill_game_launchers(force=True)
            run.assert_not_called()

    def test_snapshot_failure_falls_back_to_killing_all_names(self):
        with mock.patch.object(core, "_running_process_names", return_value=None), \
                mock.patch("subprocess.run") as run:
            core.kill_game_launchers(force=True)
            args = run.call_args[0][0]
            self.assertEqual(args.count("/IM"), len(core.GAME_LAUNCHER_PROCS))

    def test_throttled(self):
        with mock.patch.object(core, "_running_process_names", return_value={"steam.exe"}), \
                mock.patch("subprocess.run") as run:
            core.kill_game_launchers(force=True)
            core.kill_game_launchers()
            core.kill_game_launchers()
            self.assertEqual(run.call_count, 1)
            core.kill_game_launchers(force=True)
            self.assertEqual(run.call_count, 2)

    def test_throttle_expires(self):
        with mock.patch.object(core, "_running_process_names", return_value={"steam.exe"}), \
                mock.patch("subprocess.run") as run:
            core.kill_game_launchers(force=True)
            core._last_steam_kill -= core.STEAM_KILL_COOLDOWN + 1
            core.kill_game_launchers()
            self.assertEqual(run.call_count, 2)

    def test_never_raises(self):
        with mock.patch.object(core, "_running_process_names", side_effect=RuntimeError):
            core.kill_game_launchers(force=True)


class KillOnUnix(IsolatedCore):
    def test_uses_exact_names_never_command_line_substrings(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch("subprocess.run") as run:
            core.kill_game_launchers(force=True)
            self.assertEqual(run.call_count, len(core.GAME_LAUNCHER_UNIX_NAMES))
            for call in run.call_args_list:
                cmd = call[0][0]
                self.assertEqual(cmd[:2], ["pkill", "-x"])
                self.assertNotIn("-f", cmd)


class Elevation(unittest.TestCase):
    def test_is_admin_returns_bool(self):
        self.assertIsInstance(core.is_admin(), bool)

    def test_is_admin_swallows_errors(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch("os.geteuid", side_effect=OSError,
                                                                   create=True):
            self.assertFalse(core.is_admin())

    def test_relaunch_is_a_noop_off_windows(self):
        with mock.patch.object(core, "IS_WIN", False):
            self.assertIsNone(core.relaunch_as_admin())

    @unittest.skipUnless(WIN, "Windows ShellExecute")
    def test_relaunch_uses_runas_and_exits(self):
        fake = mock.MagicMock()
        with mock.patch.object(core.ctypes, "windll", fake), mock.patch.object(sys, "argv", ["a.py", "--x"]):
            with self.assertRaises(SystemExit):
                core.relaunch_as_admin()
        verb = fake.shell32.ShellExecuteW.call_args[0][1]
        self.assertEqual(verb, "runas")
        self.assertIn('"--x"', fake.shell32.ShellExecuteW.call_args[0][3])


@unittest.skipUnless(WIN, "Windows named mutex")
class SingleInstance(unittest.TestCase):
    def setUp(self):
        self._mutex = core.APP_MUTEX
        core.APP_MUTEX = f"Local\\FocusTestMutex_{os.getpid()}"      # never collide with the real app
        self._held = core._app_mutex

    def tearDown(self):
        import ctypes
        if core._app_mutex and core._app_mutex != self._held:
            k = ctypes.WinDLL("kernel32")
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            k.CloseHandle(core._app_mutex)          # release it so the next test starts clean
        core.APP_MUTEX = self._mutex
        core._app_mutex = self._held

    def test_first_claim_wins_and_is_visible(self):
        self.assertFalse(core.app_running())
        self.assertTrue(core.claim_app_instance())
        self.assertTrue(core.app_running())

    def test_a_second_process_is_refused(self):
        self.assertTrue(core.claim_app_instance())
        code = ("import sys; sys.path.insert(0, r'%s'); import core; core.APP_MUTEX=%r; "
                "print(core.claim_app_instance())" % (core.__file__.rsplit(os.sep, 1)[0], core.APP_MUTEX))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)

    def test_off_windows_it_is_always_true(self):
        with mock.patch.object(core, "IS_WIN", False):
            self.assertTrue(core.claim_app_instance())
            self.assertTrue(core.app_running())


class LaunchApp(unittest.TestCase):
    def test_off_windows_does_nothing(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch("subprocess.Popen") as popen:
            self.assertFalse(core.launch_app())
            popen.assert_not_called()

    def test_uses_pythonw_and_focusapp_detached(self):
        with mock.patch.object(core, "IS_WIN", True), \
                mock.patch.object(sys, "executable", r"C:\Py\python.exe"), \
                mock.patch("subprocess.Popen") as popen:
            self.assertTrue(core.launch_app())
            cmd = popen.call_args[0][0]
            self.assertTrue(cmd[0].lower().endswith("pythonw.exe"))
            self.assertTrue(cmd[1].endswith("focusapp.py"))
            self.assertEqual(popen.call_args[1]["creationflags"], 0x208)

    def test_keeps_pythonw_if_already_pythonw(self):
        with mock.patch.object(core, "IS_WIN", True), \
                mock.patch.object(sys, "executable", r"C:\Py\pythonw.exe"), \
                mock.patch("subprocess.Popen") as popen:
            core.launch_app()
            self.assertEqual(popen.call_args[0][0][0], r"C:\Py\pythonw.exe")

    def test_failure_is_reported_not_raised(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.Popen", side_effect=OSError):
            self.assertFalse(core.launch_app())


class PlatformFlags(unittest.TestCase):
    def test_exactly_one_family(self):
        self.assertEqual(core.IS_WIN, os.name == "nt")
        self.assertFalse(core.IS_WIN and (core.IS_MAC or core.IS_LINUX))

    def test_paths_are_absolute(self):
        self.assertTrue(os.path.isabs(core.DATA_DIR))
        self.assertTrue(os.path.isabs(core.HOSTS_PATH))
        self.assertEqual(os.path.basename(core.STATE_PATH), "state.json")


if __name__ == "__main__":
    unittest.main()
