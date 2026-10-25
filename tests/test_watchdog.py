"""The freeze watchdog, the health monitor, and the app's self-restart."""
import os
import threading
import time
import unittest
from unittest import mock

from support import IsolatedCore
import core
import focusapp as fa


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def make(**kw):
    clock = FakeClock()
    logs, restarts = [], []
    wd = fa.Watchdog(restart=lambda: restarts.append(clock.t), log=logs.append, clock=clock,
                     health=kw.pop("health", None), **kw)
    return wd, clock, logs, restarts


def run(wd, clock, seconds, beat_every=None, step=1.0):
    """Advance time `seconds`, running a check each `step`, optionally beating like a live UI."""
    results = []
    elapsed = 0.0
    while elapsed < seconds:
        clock.advance(step)
        elapsed += step
        if beat_every and elapsed % beat_every == 0:
            wd.beat()
        results.append(wd.check(clock()))
    return results


class FreezeDetection(unittest.TestCase):
    def test_a_healthy_ui_is_never_flagged(self):
        wd, clock, logs, restarts = make()
        results = run(wd, clock, 300, beat_every=1)
        self.assertTrue(all(r is None for r in results))
        self.assertEqual((logs, restarts), ([], []))

    def test_a_freeze_is_logged_once_with_a_stack_dump(self):
        wd, clock, logs, restarts = make(stall_log_sec=8, stall_restart_sec=45)
        results = run(wd, clock, 30)
        self.assertEqual(results.count("stalled"), 30 - 7)
        self.assertEqual(len(logs), 1)                                    # once, not once a second
        self.assertIn("not responding for 8s", logs[0])
        self.assertIn("--- thread", logs[0])
        self.assertIn("MainThread", logs[0])
        self.assertEqual(restarts, [])

    def test_a_long_freeze_restarts_the_app(self):
        wd, clock, logs, restarts = make(stall_log_sec=8, stall_restart_sec=45)
        results = run(wd, clock, 60)
        self.assertIn("restart", results)
        self.assertEqual(len(restarts), 1)
        self.assertEqual(restarts[0], 1000 + 45)
        self.assertTrue(any("restarting Focus" in m for m in logs))

    def test_a_short_freeze_that_recovers_is_logged_but_not_restarted(self):
        wd, clock, logs, restarts = make()
        run(wd, clock, 12)                                                # frozen 12 s
        wd.beat()                                                         # ... and it came back
        results = run(wd, clock, 60, beat_every=1)
        self.assertTrue(all(r is None for r in results))
        self.assertEqual(restarts, [])
        self.assertEqual(len(logs), 1)

    def test_each_separate_freeze_is_logged_separately(self):
        wd, clock, logs, restarts = make()
        run(wd, clock, 10)
        wd.beat()
        run(wd, clock, 5, beat_every=1)                                   # healthy in between
        run(wd, clock, 10)
        self.assertEqual(len(logs), 2)

    def test_the_machine_sleeping_is_not_a_freeze(self):
        wd, clock, logs, restarts = make()
        run(wd, clock, 5, beat_every=1)
        clock.advance(3 * 3600)                                           # laptop lid closed for 3 hours
        self.assertEqual(wd.check(clock()), "resumed")
        results = run(wd, clock, 30, beat_every=1)
        self.assertTrue(all(r is None for r in results))
        self.assertEqual((logs, restarts), ([], []))

    def test_sleep_while_the_ui_is_also_frozen_still_does_not_restart(self):
        wd, clock, logs, restarts = make()
        run(wd, clock, 20)                                                # frozen, already logged
        clock.advance(600)                                                # then the machine sleeps
        self.assertEqual(wd.check(clock()), "resumed")
        self.assertEqual(restarts, [])

    def test_without_a_restart_callback_it_only_logs(self):
        wd = fa.Watchdog(restart=None, log=lambda m: None, clock=(c := FakeClock()), health=None)
        for _ in range(100):
            c.advance(1)
            self.assertIn(wd.check(c()), ("stalled",) + (None,))

    def test_thresholds_are_configurable(self):
        wd, clock, logs, restarts = make(stall_log_sec=2, stall_restart_sec=4)
        run(wd, clock, 5)
        self.assertEqual(len(restarts), 1)

    def test_beat_resets_the_stall_timer(self):
        wd, clock, logs, restarts = make()
        run(wd, clock, 7)
        wd.beat()
        run(wd, clock, 7)
        self.assertEqual((logs, restarts), ([], []))


class HealthMonitor(unittest.TestCase):
    def test_logs_resource_counters_periodically(self):
        stats = {"gdi": 120, "user": 60, "handles": 400, "mem_mb": 95.5, "threads": 9}
        wd, clock, logs, restarts = make(health=lambda: stats, health_every=600)
        run(wd, clock, 1500, beat_every=1)
        health = [m for m in logs if m.startswith("health")]
        self.assertEqual(len(health), 2)                                  # at 600 s and 1200 s
        self.assertIn("gdi=120", health[0])
        self.assertIn("mem_mb=95.5", health[0])
        self.assertEqual(restarts, [])

    def test_restarts_early_when_a_resource_is_heading_for_the_wall(self):
        for key, bad in (("gdi", 9000), ("user", 9000), ("handles", 30000), ("mem_mb", 2500)):
            stats = {"gdi": 100, "user": 100, "handles": 500, "mem_mb": 80.0, "threads": 8}
            wd, clock, logs, restarts = make(health=lambda: stats, health_every=10)
            run(wd, clock, 5, beat_every=1)
            stats[key] = bad
            run(wd, clock, 15, beat_every=1)
            self.assertEqual(len(restarts), 1, key)
            self.assertTrue(any("resource limit" in m and key in m for m in logs), key)

    def test_values_at_the_limit_are_fine(self):
        stats = dict(fa.Watchdog.LIMITS)
        wd, clock, logs, restarts = make(health=lambda: stats, health_every=10)
        run(wd, clock, 30, beat_every=1)
        self.assertEqual(restarts, [])

    def test_a_failing_or_empty_health_reading_is_harmless(self):
        wd, clock, logs, restarts = make(health=lambda: {}, health_every=5)
        run(wd, clock, 20, beat_every=1)
        self.assertEqual((logs, restarts), ([], []))

    def test_health_is_not_checked_while_the_ui_is_frozen(self):
        called = []
        wd, clock, logs, restarts = make(health=lambda: called.append(1) or {}, health_every=5, stall_log_sec=2)
        run(wd, clock, 20)                                              # frozen from second 2 on
        self.assertEqual(called, [])

    def test_a_failed_restart_is_not_retried_every_second(self):
        wd, clock, logs, restarts = make(stall_log_sec=2, stall_restart_sec=4, restart_cooldown=300)
        run(wd, clock, 200)                                             # restart "failed": still frozen
        self.assertEqual(len(restarts), 1)
        run(wd, clock, 200)                                             # after the cooldown it may try again
        self.assertEqual(len(restarts), 2)

    @unittest.skipUnless(core.IS_WIN, "Windows counters")
    def test_real_process_health_has_sane_numbers(self):
        h = fa.process_health()
        self.assertEqual(set(h), {"gdi", "user", "handles", "mem_mb", "threads"})
        self.assertGreater(h["handles"], 10)
        self.assertGreater(h["mem_mb"], 5)
        self.assertLess(h["mem_mb"], 5000)
        self.assertGreaterEqual(h["threads"], 1)
        self.assertLess(h["gdi"], fa.Watchdog.LIMITS["gdi"])             # the test process is nowhere near the limit

    def test_process_health_is_empty_off_windows(self):
        with mock.patch.object(core, "IS_WIN", False):
            self.assertEqual(fa.process_health(), {})


class ThreadDump(unittest.TestCase):
    def test_includes_every_thread_with_its_stack(self):
        started, release = threading.Event(), threading.Event()

        def parked():
            started.set()
            release.wait(3)
        t = threading.Thread(target=parked, name="parked-worker", daemon=True)
        t.start()
        started.wait(2)
        dump = fa.dump_threads()
        release.set()
        self.assertIn("--- thread parked-worker", dump)
        self.assertIn("--- thread MainThread", dump)
        self.assertIn("parked", dump)

    def test_is_bounded_in_size(self):
        self.assertLessEqual(len(fa.dump_threads()), 6000)


class WatchdogThread(unittest.TestCase):
    def test_runs_in_the_background_and_stops(self):
        logs = []
        wd = fa.Watchdog(restart=None, log=logs.append, interval=0.01, stall_log_sec=0.05, health=None)
        wd.start()
        wd.start()                                                        # idempotent
        time.sleep(0.4)                                                   # nobody beats -> it must notice
        wd.stop()
        self.assertTrue(any("not responding" in m for m in logs))
        self.assertEqual(sum(t.name == "focus-watchdog" for t in threading.enumerate()
                             if t.is_alive()) <= 1, True)

    def test_a_beating_ui_keeps_it_quiet(self):
        logs = []
        wd = fa.Watchdog(restart=None, log=logs.append, interval=0.01, stall_log_sec=0.2, health=None)
        wd.start()
        end = time.time() + 0.5
        while time.time() < end:
            wd.beat()
            time.sleep(0.01)
        wd.stop()
        self.assertEqual(logs, [])

    def test_an_error_inside_the_check_is_logged_not_fatal(self):
        logs = []
        wd = fa.Watchdog(restart=None, log=logs.append, interval=0.01, health=None)
        with mock.patch.object(wd, "check", side_effect=RuntimeError("boom")):
            wd.start()
            time.sleep(0.15)
            wd.stop()
        self.assertTrue(any("watchdog error" in m and "boom" in m for m in logs))

    def test_uses_the_real_clock_not_the_patched_module_time(self):
        """Tests (and a few tools) replace `time` inside focusapp; the watchdog must not follow."""
        self.assertIs(fa._mono, __import__("time").monotonic)


class SelfRestart(IsolatedCore):
    def make_app(self):
        import types
        return types.SimpleNamespace(_restart_self=fa.FocusApp._restart_self)

    def test_releases_the_lock_launches_a_new_copy_then_exits(self):
        order = []
        with mock.patch.object(core, "release_app_instance", lambda: order.append("release")), \
                mock.patch.object(core, "launch_app", lambda: order.append("launch") or True), \
                mock.patch.object(core, "claim_app_instance", lambda: order.append("claim") or True), \
                mock.patch.object(fa.os, "_exit", lambda code: order.append(f"exit{code}")):
            fa.FocusApp._restart_self(object())
        self.assertEqual(order, ["release", "launch", "exit3"])           # the new copy can claim the lock

    def test_keeps_running_if_the_new_copy_could_not_be_started(self):
        order = []
        with mock.patch.object(core, "release_app_instance", lambda: order.append("release")), \
                mock.patch.object(core, "launch_app", lambda: order.append("launch") or False), \
                mock.patch.object(core, "claim_app_instance", lambda: order.append("claim") or True), \
                mock.patch.object(fa.os, "_exit", lambda code: order.append("exit")):
            fa.FocusApp._restart_self(object())
        self.assertEqual(order, ["release", "launch", "claim"])           # takes the lock back, never exits
        self.assertIn("restarting Focus", open(core.log_path(), encoding="utf-8").read())

    def test_the_app_class_keeps_the_watchdog_off_in_tests_only_by_flag(self):
        self.assertTrue(fa.FocusApp.WATCHDOG_ENABLED)


class ErrorLogging(IsolatedCore):
    def test_tk_callback_errors_are_logged_with_a_traceback(self):
        import types
        stub = types.SimpleNamespace(_tk_errors=0)
        try:
            1 / 0
        except ZeroDivisionError as ex:
            fa.FocusApp._on_tk_error(stub, type(ex), ex, ex.__traceback__)
        text = open(core.log_path(), encoding="utf-8").read()
        self.assertIn("callback error #1", text)
        self.assertIn("ZeroDivisionError", text)
        self.assertEqual(stub._tk_errors, 1)

    def test_a_storm_of_identical_errors_does_not_flood_the_log(self):
        import types
        stub = types.SimpleNamespace(_tk_errors=0)
        for _ in range(1000):
            try:
                1 / 0
            except ZeroDivisionError as ex:
                fa.FocusApp._on_tk_error(stub, type(ex), ex, ex.__traceback__)
        entries = open(core.log_path(), encoding="utf-8").read().count("callback error #")
        self.assertLessEqual(entries, 20 + 10)                            # the first 20, then every 100th
        self.assertEqual(stub._tk_errors, 1000)


if __name__ == "__main__":
    unittest.main()
