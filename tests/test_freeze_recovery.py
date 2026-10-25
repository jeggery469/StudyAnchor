"""End-to-end: a REAL frozen window restarts itself. Runs the app in a child process, blocks its UI
thread, and checks that it logged where it was stuck, started a replacement, and exited."""
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from support import ROOT      # (also puts the project folder on sys.path)
import core

WIN = core.IS_WIN

CHILD = textwrap.dedent('''
    import os, sys, time, threading
    sys.path.insert(0, {root!r})
    import core
    DATA = {data!r}
    core.DATA_DIR = DATA
    core.STATE_PATH = os.path.join(DATA, "state.json")
    core.HOSTS_PATH = os.path.join(DATA, "hosts")
    open(core.HOSTS_PATH, "w").write("127.0.0.1 localhost\\n")
    import focusapp as fa

    launched = []
    core.launch_app = lambda: launched.append(1) or open(os.path.join(DATA, "launched.txt"), "w").write("yes") or True
    fa.list_voices = lambda: []
    fa.FocusApp._enforce_loop = lambda self: None
    # a healthy window beats about once a second, so the thresholds must sit above that
    fa.FocusApp.WATCHDOG_STALL_LOG_SEC = {log_sec!r}
    fa.FocusApp.WATCHDOG_STALL_RESTART_SEC = {restart_sec!r}
    mode = {mode!r}

    app = fa.FocusApp()
    # Watchdog checks once a second by default; speed it up for the test
    app._watchdog.interval = 0.1
    if mode == "freeze":
        def freeze_the_window():
            time.sleep(60)                       # the UI thread stops responding
        app.root.after(500, freeze_the_window)
        app.root.after(40000, app.root.quit)     # never reached: the watchdog must act first
    else:
        app.root.after(3500, app.root.quit)      # healthy: runs, then quits normally
    app.run()
    sys.exit(0)
''')


def run_child(mode, timeout=25):
    data = tempfile.mkdtemp(prefix="focus_freeze_")
    log_sec, restart_sec = (0.6, 1.5) if mode == "freeze" else (3.0, 6.0)
    code = CHILD.format(root=ROOT, data=data, mode=mode, log_sec=log_sec, restart_sec=restart_sec)
    script = os.path.join(data, "child.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(code)
    t = time.time()
    p = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p, data, time.time() - t


@unittest.skipUnless(WIN, "needs a real window")
class FreezeRecovery(unittest.TestCase):
    def test_a_frozen_window_is_logged_and_replaced(self):
        p, data, took = run_child("freeze")
        self.assertEqual(p.returncode, 3, p.stderr[-800:])                  # exited via the watchdog
        self.assertLess(took, 20)                                           # long before the 60 s freeze ends
        self.assertTrue(os.path.exists(os.path.join(data, "launched.txt")))  # a replacement was started
        with open(os.path.join(data, "focus.log"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("UI thread not responding", log)
        self.assertIn("freeze_the_window", log)                              # the stack shows WHERE it hung
        self.assertIn("time.sleep(60)", log)
        self.assertIn("restarting Focus", log)

    def test_a_healthy_window_is_left_alone(self):
        p, data, took = run_child("healthy")
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        self.assertFalse(os.path.exists(os.path.join(data, "launched.txt")))
        log_path = os.path.join(data, "focus.log")
        text = ""
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                text = f.read()
        self.assertNotIn("not responding", text)
        self.assertNotIn("restarting", text)


if __name__ == "__main__":
    unittest.main()
