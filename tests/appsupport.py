"""Headless FocusApp harness: real windows, fake clock, silent audio, isolated files.

One real app is built per test CLASS (building the windows is the slow part) and every test
starts from a freshly reset state, so tests stay independent."""
import os
import shutil
import tempfile
import time as real_time
import tkinter as tk
import types
from unittest import mock

from support import IsolatedCore, FakeTime, MORNING
import core
import focusapp as fa


class AppCase(IsolatedCore):
    CTK = True
    START = MORNING

    # ------------------------------------------------------------ class-level app
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.mkdtemp(prefix="focus_app_")
        cls._core_saved = (core.DATA_DIR, core.STATE_PATH, core.HOSTS_PATH)
        core.DATA_DIR = cls._tmp
        core.STATE_PATH = os.path.join(cls._tmp, "state.json")
        core.HOSTS_PATH = os.path.join(cls._tmp, "hosts")
        with open(core.HOSTS_PATH, "w") as f:
            f.write("127.0.0.1 localhost\n")

        cls.real_enforce_loop = fa.FocusApp._enforce_loop        # the patched-out original
        e = cls.env = types.SimpleNamespace(
            fake=FakeTime(cls.START), said=[], beeped=[], chimes=[], overlaps=[], customs=[],
            ctrl_w=[], pip=[], pip_closed=[], fg=("", ""), hook_active=[], popups=[], enforced=[])

        def _overlap(lines, n, voice=None):
            e.overlaps.append((list(lines), n, voice))

        cls._patches = [
            mock.patch.object(fa, "time", e.fake),
            mock.patch.object(core, "time", e.fake),
            mock.patch.object(fa, "HAVE_CTK", cls.CTK),
            mock.patch.object(fa, "list_voices", lambda: ["Voice A", "Voice B"]),
            mock.patch.object(fa, "_platform_beep",
                              lambda f=880, d=200: (e.beeped.append((f, d)), real_time.sleep(0.005))),
            mock.patch.object(fa, "beeps", lambda c, f, d: e.beeped.append(("beeps", c, f, d))),
            mock.patch.object(fa, "play_chime", lambda: e.chimes.append(1)),
            mock.patch.object(fa, "say", lambda text, voice=None, rate=0: e.said.append((text, voice))),
            mock.patch.object(fa, "say_overlap", _overlap),
            mock.patch.object(fa, "play_custom_overlap", lambda n: e.customs.append(n) or False),
            mock.patch.object(fa, "foreground_raw", lambda: e.fg),
            mock.patch.object(fa, "send_ctrl_w", lambda: e.ctrl_w.append(e.fake.now)),
            mock.patch.object(fa, "find_pip_windows", lambda: list(e.pip)),
            mock.patch.object(fa, "close_window", lambda h: (e.pip_closed.append(h), h in e.pip and e.pip.remove(h))),
            mock.patch.object(fa.ScrollCounter, "set_active", lambda s, on: e.hook_active.append(on)),
            mock.patch.object(fa.FocusApp, "_enforce_loop", lambda s: None),
            mock.patch.object(fa.FocusApp, "AUTO_TUTORIAL", False),         # no walkthrough popping up mid-test
            mock.patch.object(fa.FocusApp, "WATCHDOG_ENABLED", False),     # a restart would kill the test run
        ]
        for p in cls._patches:
            p.start()
        no_tick = mock.patch.object(fa.FocusApp, "_tick", lambda s: None)   # no first tick in __init__
        no_tick.start()
        try:
            cls.app = fa.FocusApp()
        finally:
            no_tick.stop()
        cls.app._popup = lambda title, body, color=None: e.popups.append((title, body))
        cls.app._enforce_async = lambda refresh=False: e.enforced.append(refresh)
        cls.real_enforce_async = fa.FocusApp._enforce_async

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.notifier.stop()
            try:
                cls.app.root.update_idletasks()
                for aid in cls.app.root.tk.call("after", "info"):
                    cls.app.root.after_cancel(aid)
            except Exception:
                pass
            cls.app._quit_app()
        finally:
            for p in reversed(cls._patches):
                p.stop()
            core.DATA_DIR, core.STATE_PATH, core.HOSTS_PATH = cls._core_saved
            shutil.rmtree(cls._tmp, ignore_errors=True)
            super().tearDownClass()

    # ------------------------------------------------------------ per-test reset
    def setUp(self):
        super().setUp()                       # fresh temp state/hosts for this test
        e, a = self.env, self.app
        for name in ("said", "beeped", "chimes", "overlaps", "customs", "ctrl_w",
                     "hook_active", "popups", "enforced", "pip", "pip_closed"):
            getattr(e, name).clear()
        e.fg = ("", "")
        e.fake.now = float(self.START)
        self.fake = e.fake
        self.said, self.beeped, self.chimes, self.overlaps = e.said, e.beeped, e.chimes, e.overlaps
        self.customs, self.ctrl_w, self.hook_active = e.customs, e.ctrl_w, e.hook_active
        self.popups, self.enforced = e.popups, e.enforced

        a.notifier.stop()
        for w in list(a.root.winfo_children()):
            if isinstance(w, tk.Toplevel) and w is not a.popout:
                try:
                    w.destroy()
                except Exception:
                    pass
        a.st = core.default_state()
        a.session_active = False
        a.session_remaining = 0
        a.session_paused = False
        a.session_manual_paused = False
        a.secret = None
        a._last_render = None
        a._recording = False
        a._last_nag_at = None
        a._noses_start = None
        a._pause_start = None
        a._play_until = 0
        a._break_prev = False
        a._steam_prev = False
        a._learn_prev = False
        a._lt_bad_since = None
        a._tk_errors = 0
        a.notifier._last_voice = -1e9
        a.notifier._styled_level = None
        a._last_tabclose = 0
        a._last_pipcheck = 0
        a.clock = 0
        a._last_tick_mono = None
        a._tick_errors = 0
        a._last_tick_error = ""
        a._hook_until = 0
        a._doom_flash = -999
        a.doom_active = False
        a._last_scroll = a.scroll.count
        a._clocked_prev = core.clocked_out(a.st, e.fake.now)
        a._clockout_offered = None
        a._tut = None
        a._m_r4_shown = False
        a.m_r4.pack_forget()
        a._enforce_busy = False
        a._enforce_again = False
        a._enforce_refresh = False
        a._apply_notif_settings()
        a._show_mini()
        a._maybe_reset_cheat_day()
        e.popups.clear()
        e.enforced.clear()

    def tearDown(self):
        self.app.notifier.stop()
        super().tearDown()

    # ------------------------------------------------------------ helpers
    @property
    def app(self):
        return type(self).app

    @property
    def st(self):
        return self.app.st

    def set_fg(self, proc, title):
        self.env.fg = (proc, title)

    def tick(self, n=1, dt=1.0):
        for _ in range(n):
            self.fake.advance(dt)
            self.app._tick_body()

    def popup_titles(self):
        return [t for t, _b in self.popups]

    def set_time(self, t):
        self.fake.now = float(t)

    def text_of(self, widget):
        return widget.cget("text")

    def wait_for(self, cond, secs=3.0):
        deadline = real_time.time() + secs
        while real_time.time() < deadline and not cond():
            real_time.sleep(0.01)
        return cond()
