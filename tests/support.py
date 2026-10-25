"""Shared helpers for the Focus test suite (no third-party dependencies)."""
import os
import sys
import time
import shutil
import tempfile
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import core  # noqa: E402

# Safety net for the WHOLE test process: until a test sets up its own scratch folder, the data
# folder, state file, hosts file and diagnostics log all point at a throwaway directory, so no test
# can ever touch the real C:\ProgramData\FocusTool or the real hosts file (a test that simulates a
# failure used to write a line into the user's real focus.log).
REAL_DATA_DIR = core.DATA_DIR
REAL_HOSTS_PATH = core.HOSTS_PATH
_SESSION_DIR = tempfile.mkdtemp(prefix="focus_tests_session_")
core.DATA_DIR = _SESSION_DIR
core.STATE_PATH = os.path.join(_SESSION_DIR, "state.json")
core.HOSTS_PATH = os.path.join(_SESSION_DIR, "hosts")

# The browser URL-blocklist policy (YouTube Shorts) lives in the registry. Tests get a throwaway
# per-process key under HKEY_CURRENT_USER - never the machine-wide HKLM policy keys - and it is
# deleted again when the test process exits.
REAL_POLICY_HIVE = core.POLICY_HIVE
REAL_POLICY_ROOT = core.POLICY_ROOT
if core.IS_WIN:
    import atexit
    import uuid
    import winreg
    core.POLICY_HIVE = "HKCU"
    core.POLICY_ROOT = "SOFTWARE\\FocusToolTests\\" + uuid.uuid4().hex + "\\Policies"
    _POLICY_TEST_ROOT = core.POLICY_ROOT.rsplit("\\", 1)[0]

    def _delete_tree(hive, path):
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    _delete_tree(hive, path + "\\" + sub)
            winreg.DeleteKey(hive, path)
        except OSError:
            pass
    atexit.register(_delete_tree, winreg.HKEY_CURRENT_USER, _POLICY_TEST_ROOT)

REAL_TIME = time


def ts(y, mo, d, h=0, mi=0, s=0):
    """Local-time timestamp, e.g. ts(2026, 9, 24, 14, 30)."""
    return datetime(y, mo, d, h, mi, s).timestamp()


# a weekday morning inside the default 07:00-midnight schedule, before the 23:59 clock-out
# (2026-09-23 is a Wednesday)
MORNING = ts(2026, 9, 23, 10, 0)
EVENING = ts(2026, 9, 23, 23, 59, 30)  # inside the schedule, AFTER the 23:59 clock-out
NIGHT = ts(2026, 9, 23, 3, 0)          # outside the schedule (small hours)
EARLY = ts(2026, 9, 23, 5, 0)          # outside the schedule

# the weekend equivalents (2026-09-26 = Saturday, 2026-09-27 = Sunday); weekend hours default
# to 10:00-18:00; SAT_EARLY / SAT_LATE land inside the WEEKDAY window but outside the WEEKEND
# one, to prove the two schedules are actually independent
SAT_MORNING = ts(2026, 9, 26, 12, 0)     # inside the 10:00-18:00 weekend window
SAT_EARLY = ts(2026, 9, 26, 8, 0)        # before the weekend start, but after the weekday one
SAT_LATE = ts(2026, 9, 26, 19, 0)        # after the weekend end, but before the weekday one
SUN_MORNING = ts(2026, 9, 27, 12, 0)


class FakeTime:
    """Drop-in for the `time` module with a clock the test controls. Everything except
    time()/monotonic() falls through to the real module (sleep, perf_counter, ...)."""

    def __init__(self, t0=MORNING):
        self.now = float(t0)

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds

    def __getattr__(self, name):
        return getattr(REAL_TIME, name)


class IsolatedCore(unittest.TestCase):
    """Points core at a scratch directory so a test can never touch the real hosts file or
    the real state.json, and gives every test a fresh, seeded hosts file."""

    HOSTS_SEED = "127.0.0.1 localhost\n"

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="focus_test_")
        self._saved = (core.DATA_DIR, core.STATE_PATH, core.HOSTS_PATH,
                       core._last_steam_kill)
        core.DATA_DIR = self.tmp
        core.STATE_PATH = os.path.join(self.tmp, "state.json")
        core.HOSTS_PATH = os.path.join(self.tmp, "hosts")
        core._last_steam_kill = 0.0
        with open(core.HOSTS_PATH, "w", encoding="utf-8") as f:
            f.write(self.HOSTS_SEED)

    def tearDown(self):
        core.DATA_DIR, core.STATE_PATH, core.HOSTS_PATH, core._last_steam_kill = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def hosts(self):
        with open(core.HOSTS_PATH, encoding="utf-8") as f:
            return f.read()

    def write_hosts(self, text):
        with open(core.HOSTS_PATH, "w", encoding="utf-8") as f:
            f.write(text)

    def state(self, **overrides):
        st = core.default_state()
        st.update(overrides)
        return st
