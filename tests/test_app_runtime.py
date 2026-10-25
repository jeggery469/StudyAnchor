"""FocusApp runtime behaviour: status, views, the 1-second tick, nagging, the notifier windows,
background enforcement and startup. Runs on customtkinter and on plain tkinter."""
import threading
import time as real_time
import types
import unittest
from unittest import mock

from appsupport import AppCase
from support import MORNING, EVENING, NIGHT, ts
import core
import focusapp as fa


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


@both
class Status(AppCase):
    def head(self):
        return self.app._status()[0]

    def test_locked_in_by_default(self):
        self.assertEqual(self.head(), "🔒 LOCKED IN")

    def test_off_hours(self):
        self.set_time(NIGHT)
        self.assertEqual(self.head(), "🌙 OFF-HOURS")
        self.assertIn("07:00", self.app._status()[1])

    def test_clocked_out(self):
        self.set_time(EVENING)
        self.assertEqual(self.head(), "🕗 CLOCKED OUT")

    def test_break_shows_a_countdown(self):
        self.st["unlock_until"] = MORNING + 125
        self.assertEqual(self.head(), "☕ BREAK 02:05")

    def test_snoozed(self):
        self.st["snooze_until"] = MORNING + 60
        self.assertEqual(self.head(), "😴 SNOOZED 01:00")

    def test_burnout_rest(self):
        self.st["studied_today_min"] = 999
        self.assertEqual(self.head(), "🌿 REST")

    def test_session_and_pause(self):
        self.app.session_active = True
        self.app.session_remaining = 90
        self.assertEqual(self.head(), "📚 STUDY 01:30")
        self.app.session_manual_paused = True
        self.assertEqual(self.head(), "⏸ PAUSED 01:30")

    def test_nuclear_outranks_everything(self):
        self.app.session_active = True
        self.st.update(nuclear_until=MORNING + 3661, unlock_until=MORNING + 100)
        self.assertEqual(self.head(), "☢ NUCLEAR 1:01:01")

    def test_precedence_break_over_snooze_over_clockout(self):
        self.set_time(EVENING)
        self.st["snooze_until"] = EVENING + 60
        self.assertEqual(self.head(), "😴 SNOOZED 01:00")
        self.st["unlock_until"] = EVENING + 60
        self.assertTrue(self.head().startswith("☕ BREAK"))


@both
class Views(AppCase):
    def test_full_and_mini_swap_windows(self):
        self.app._show_full()
        self.assertFalse(self.app.is_mini)
        self.assertEqual(self.app.popout.state(), "withdrawn")
        self.assertNotEqual(self.app.root.state(), "withdrawn")
        self.app._show_mini()
        self.assertTrue(self.app.is_mini)
        self.assertEqual(self.app.root.state(), "withdrawn")
        self.assertNotEqual(self.app.popout.state(), "withdrawn")

    def test_full_view_fills_every_form_field(self):
        self.st.update(reminders="- a", reminder_interval_min=9, reminder_voice="Voice A",
                       nag_own_words=False, strobe_enabled=False, nag_frequency=5)
        self.app._show_full()
        self.assertEqual(self.app.rem_text.get("1.0", "end").strip(), "- a")
        self.assertEqual(self.app.rem_interval.get(), "9")
        self.assertEqual(self.app.voice_var.get(), "Voice A")
        self.assertEqual(self.app.nag_own_var.get(), 0)
        self.assertEqual(self.app.strobe_var.get(), 0)
        self.assertEqual(self.app.slider_widgets["nag_frequency"][0].get(), 5)
        self.assertEqual(self.text_of(self.app.slider_widgets["nag_frequency"][1]), "5")

    def test_losing_focus_to_another_app_snaps_back_to_the_mini_popout(self):
        self.app._show_full()
        with mock.patch.object(self.app.root, "focus_get", return_value=None):
            self.app._check_root_focus_lost()
        self.assertTrue(self.app.is_mini)

    def test_focus_moving_to_our_own_dialog_keeps_the_full_window(self):
        self.app._show_full()
        with mock.patch.object(self.app.root, "focus_get", return_value=self.app.root):
            self.app._check_root_focus_lost()
        self.assertFalse(self.app.is_mini)

    def test_focus_check_is_harmless_in_mini_mode_and_after_destroy(self):
        self.app._check_root_focus_lost()
        self.app._show_full()
        with mock.patch.object(self.app.root, "focus_get", return_value=None), \
                mock.patch.object(self.app, "_show_mini", side_effect=fa.tk.TclError):
            self.app._check_root_focus_lost()             # must not raise

    def test_focus_out_schedules_the_check(self):
        with mock.patch.object(self.app.root, "after") as after:
            self.app._on_root_focus_out()
        self.assertEqual(after.call_args[0][0], 150)

    def test_bring_to_front_only_pins_the_popout(self):
        self.app._bring_to_front()
        self.assertTrue(bool(int(self.app.popout.attributes("-topmost"))))
        self.app._show_full()
        self.app._bring_to_front()
        self.assertFalse(bool(int(self.app.root.attributes("-topmost"))))

    def test_tab_change_refreshes_and_reloads_learning_only_for_that_tab(self):
        with mock.patch.object(self.app, "refresh_ui") as ui, mock.patch.object(self.app, "_render_learning") as learn:
            self.app._on_tab_changed("Dashboard")
            self.assertEqual((ui.call_count, learn.call_count), (1, 0))
            self.app._on_tab_changed("Learning")
            self.assertEqual((ui.call_count, learn.call_count), (2, 1))
            self.app._on_tab_changed("Settings")
            self.assertEqual((ui.call_count, learn.call_count), (3, 1))

    def test_icon_loaded(self):
        self.assertIsNotNone(getattr(self.app, "_icon_img", None))

    def test_quit_destroys_both_windows_and_stops_the_notifier(self):
        # covered end-to-end by tearDownClass; here just check it is idempotent-safe on a stub
        stub = types.SimpleNamespace(notifier=mock.Mock(), popout=mock.Mock(), root=mock.Mock())
        fa.FocusApp._quit_app(stub)
        stub.notifier.stop.assert_called_once()
        stub.popout.destroy.assert_called_once()
        stub.root.destroy.assert_called_once()
        stub.popout.destroy.side_effect = RuntimeError
        fa.FocusApp._quit_app(stub)                        # a failing destroy must not raise


@both
class Rendering(AppCase):
    def test_mini_labels_follow_the_state(self):
        self.app.refresh_ui()
        self.assertEqual(self.text_of(self.app.m_study), "▶ Study")
        self.assertEqual(self.text_of(self.app.m_btn2), "⚡ Cheat")
        self.assertEqual(self.text_of(self.app.m_status), "🔒 LOCKED IN")
        self.app.toggle_session()
        self.assertEqual(self.text_of(self.app.m_study), "■ Stop")
        self.assertEqual(self.text_of(self.app.m_btn2), "⏸ Pause")
        self.app.toggle_pause()
        self.assertEqual(self.text_of(self.app.m_btn2), "▶ Resume")

    def test_full_labels_and_chips(self):
        self.app._show_full()
        self.st["time_bank_minutes"] = 33
        self.app.refresh_ui()
        self.assertEqual(self.text_of(self.app.d_bank_v), "33 min")
        self.assertEqual(self.text_of(self.app.b_balance), "33 min")
        self.assertEqual(self.text_of(self.app.d_steam_v), "BLOCKED")
        self.assertEqual(self.text_of(self.app.d_cheat_v), f"{len(core.CHEAT_LADDER) - 1} × 5m")
        self.assertEqual(self.text_of(self.app.d_study), "▶  Start study session")
        self.st["steam_break_until"] = MORNING + 60
        self.st["cheat_index"] = len(core.CHEAT_LADDER) - 1
        self.app._last_render = None
        self.app.refresh_ui()
        self.assertEqual(self.text_of(self.app.d_steam_v), "OPEN")
        self.assertEqual(self.text_of(self.app.d_cheat_v), "none")
        self.set_time(NIGHT + 24 * 3600)    # small hours of the NEXT day: the break is long over
        self.app._last_render = None
        self.app.refresh_ui()
        self.assertEqual(self.text_of(self.app.d_steam_v), "FREE")

    def test_cheats_left_counts_down(self):
        self.app._show_full()
        total = len(core.CHEAT_LADDER) - 1
        for used in range(total + 2):
            left = max(0, total - used)
            self.st["cheat_index"] = used
            self.app._last_render = None
            self.app.refresh_ui()
            want = f"{left} × 5m" if left else "none"
            self.assertEqual(self.text_of(self.app.d_cheat_v), want, used)

    def test_negative_bank_is_still_shown(self):
        self.app._show_full()
        self.st["time_bank_minutes"] = -4
        self.app.refresh_ui()
        self.assertEqual(self.text_of(self.app.d_bank_v), "-4 min")

    def test_unchanged_state_skips_every_widget_write(self):
        self.app.refresh_ui()
        with mock.patch.object(fa, "set_label") as sl:
            self.app.refresh_ui()
            self.app.refresh_ui()
        sl.assert_not_called()

    def test_doomscroll_banner(self):
        self.app.doom_active = True
        self.app.refresh_ui()
        self.assertIn("DOOMSCROLLING", self.text_of(self.app.m_sub))
        self.assertIn("−1 min/scroll", self.text_of(self.app.m_sub))

    def test_helpers_survive_dead_widgets(self):
        dead = mock.Mock()
        dead.configure.side_effect = RuntimeError
        fa.set_label(dead, "x", "#fff")
        fa.FocusApp._cfg(dead, text="x")
        fa.set_label(dead)

    def test_set_label_writes_text_and_colour(self):
        lab = fa.WLabel(self.app.root, "a")
        fa.set_label(lab, "b", "#123456")
        self.assertEqual(lab.cget("text"), "b")
        lab.destroy()


@both
class NoUsageTracking(AppCase):
    """The Usage tab is gone, and so is the record of which windows you used."""
    def setUp(self):
        super().setUp()
        self.app._show_full()

    def test_the_tracking_code_is_gone(self):
        for name in ("refresh_usage", "_flush_usage", "_build_usage", "_usage_buf", "_usage_last_flush",
                     "tab_usage", "u_list", "u_total"):
            self.assertFalse(hasattr(self.app, name), name)
        for name in ("_pretty_label", "foreground_label"):
            self.assertFalse(hasattr(fa, name), name)

    def test_the_foreground_window_is_not_recorded(self):
        self.set_fg("chrome.exe", "khan academy - google chrome")
        self.tick(40)
        self.assertNotIn("usage", self.st)
        self.assertNotIn("usage", core.load_state())

    def test_nothing_about_usage_is_written_to_the_state_file(self):
        self.set_fg("chrome.exe", "khan academy - google chrome")
        self.tick(40)
        self.app._save()
        with open(core.STATE_PATH, encoding="utf-8") as f:
            text = f.read().lower()
        self.assertNotIn("khan academy", text)
        self.assertNotIn('"usage"', text)

    def test_ticking_still_works_without_it(self):
        self.set_fg("", "")
        self.tick(20)
        self.assertEqual(self.app.clock, 20)


@both
class TickLoop(AppCase):
    def test_a_crash_inside_a_tick_never_stops_the_loop(self):
        with mock.patch.object(self.app, "_tick_body", side_effect=RuntimeError("boom")), \
                mock.patch.object(self.app.root, "after") as after:
            self.app._tick()
        self.assertEqual(self.app._tick_errors, 1)
        self.assertIn("boom", self.app._last_tick_error)
        after.assert_called_once_with(1000, self.app._tick)

    def test_normal_tick_reschedules_once(self):
        with mock.patch.object(self.app.root, "after") as after:
            self.app._tick()
        after.assert_called_once_with(1000, self.app._tick)
        self.assertEqual(self.app._tick_errors, 0)

    def test_a_dead_window_does_not_raise(self):
        with mock.patch.object(self.app.root, "after", side_effect=fa.tk.TclError):
            self.app._tick()

    def test_many_failing_ticks_keep_counting(self):
        with mock.patch.object(self.app, "_tick_body", side_effect=ValueError), \
                mock.patch.object(self.app.root, "after"):
            for _ in range(5):
                self.app._tick()
        self.assertEqual(self.app._tick_errors, 5)

    def test_clock_counter_increments(self):
        self.tick(3)
        self.assertEqual(self.app.clock, 3)

    def test_clock_out_is_announced_exactly_once(self):
        self.st["clockout_time"] = "20:00"                    # an arbitrary clock-out inside the day
        self.set_time(ts(2026, 9, 23, 19, 59, 58))
        self.app._clocked_prev = False
        self.tick(1)
        self.assertEqual(self.chimes, [])
        self.tick(3)                                          # crosses 20:00
        self.assertEqual(self.chimes, [1])
        self.assertEqual([t for t, _ in self.said], ["You're clocked out. Step away and relax."])
        self.assertEqual(self.popup_titles(), ["🕗 Clocked out"])
        self.tick(5)
        self.assertEqual(self.chimes, [1])

    def test_starting_the_app_after_clock_out_does_not_announce(self):
        self.set_time(EVENING)
        self.app._clocked_prev = core.clocked_out(self.st, EVENING)
        self.tick(3)
        self.assertEqual(self.chimes, [])

    def test_reminders_are_read_on_the_interval_only_during_hours(self):
        self.st.update(reminders="- keep going", reminder_interval_min=1, reminder_voice="Voice B")
        self.tick(59)
        self.assertEqual(self.said, [])
        self.tick(1)
        self.assertEqual(self.said, [("keep going", "Voice B")])

    def test_reminder_reading_can_be_off(self):
        self.st.update(reminders="- x", reminder_interval_min=0)
        self.tick(120)
        self.assertEqual(self.said, [])

    def test_reminders_stay_quiet_outside_hours(self):
        self.set_time(NIGHT)
        self.app._clocked_prev = True                    # already past clock-out, nothing to announce
        self.st.update(reminders="- x", reminder_interval_min=1)
        self.tick(60)
        self.assertEqual(self.said, [])

    def test_new_day_rolls_over_during_a_tick(self):
        self.st.update(cheat_day="1999-01-01", cheat_index=3)
        self.tick(1)
        self.assertEqual(self.st["cheat_index"], 0)


@both
class TabAutoClose(AppCase):
    def test_closes_a_blocked_site_in_front(self):
        self.set_fg("chrome.exe", "youtube - google chrome")
        self.tick(1)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_every_default_site_title_is_closed(self):
        for title in ("(2) instagram", "reddit - front page", "naruto | fandom", "bilibili",
                      "minecraft wiki", "amazon.com : shoes", "netflix", "twitch"):
            self.ctrl_w.clear()
            self.app._last_tabclose = 0
            self.set_fg("msedge.exe", title + " - microsoft edge")
            self.tick(1)
            self.assertEqual(len(self.ctrl_w), 1, title)

    def test_leaves_study_and_music_tabs_alone(self):
        for title in ("laotzu - google search", "desmos | graphing calculator", "spotify - my playlist",
                      "khan academy", "amazon rainforest - wikipedia", "search results"):
            self.set_fg("chrome.exe", title + " - google chrome")
            self.tick(3)
        self.assertEqual(self.ctrl_w, [])

    def test_only_browsers_are_touched(self):
        self.set_fg("code.exe", "youtube downloader - notes")
        self.tick(3)
        self.assertEqual(self.ctrl_w, [])

    def test_cooldown_between_closes(self):
        self.set_fg("chrome.exe", "youtube - google chrome")
        self.tick(1)
        self.tick(1)
        self.assertEqual(len(self.ctrl_w), 1)                # 1s later: still cooling down
        self.tick(1)
        self.assertEqual(len(self.ctrl_w), 2)                # 2s after the first

    def test_nothing_closes_during_a_break_or_off_hours(self):
        self.set_fg("chrome.exe", "youtube - google chrome")
        self.st["unlock_until"] = MORNING + 999
        self.tick(3)
        self.st["unlock_until"] = 0
        self.set_time(NIGHT)
        self.tick(3)
        self.assertEqual(self.ctrl_w, [])

    def test_nuclear_closes_even_during_a_break(self):
        self.set_fg("chrome.exe", "youtube - google chrome")
        self.st.update(unlock_until=MORNING + 999, nuclear_until=MORNING + 999)
        self.tick(1)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_a_site_added_later_is_recognised(self):
        self.st["blocklist"] = self.st["blocklist"] + ["mycustomsite.org"]
        self.set_fg("firefox.exe", "mycustomsite home - mozilla firefox")
        self.tick(1)
        self.assertEqual(len(self.ctrl_w), 1)


@both
class Doomscroll(AppCase):
    def scroll(self, n):
        self.app.scroll.count += n

    def test_each_scroll_costs_a_bank_minute(self):
        self.st["time_bank_minutes"] = 10
        self.set_fg("chrome.exe", "youtube shorts - google chrome")
        self.scroll(3)
        self.tick(1)
        self.assertEqual(self.st["time_bank_minutes"], 7)
        self.assertTrue(self.app.doom_active)
        self.assertIn(("beeps", 1, 200, 90), self.beeped)

    def test_the_bank_can_go_into_debt(self):
        self.set_fg("chrome.exe", "instagram reels - google chrome")
        self.scroll(5)
        self.tick(1)
        self.assertEqual(self.st["time_bank_minutes"], -5)

    def test_penalty_setting_is_used(self):
        self.st["doomscroll_penalty_min"] = 2
        self.set_fg("chrome.exe", "tiktok - google chrome")
        self.scroll(3)
        self.tick(1)
        self.assertEqual(self.st["time_bank_minutes"], -6)

    def test_scrolling_normal_pages_is_free(self):
        self.set_fg("chrome.exe", "wikipedia - google chrome")
        self.scroll(50)
        self.tick(1)
        self.assertEqual(self.st["time_bank_minutes"], 0)
        self.assertFalse(self.app.doom_active)

    def test_scrolling_outside_a_browser_is_free(self):
        self.set_fg("code.exe", "shorts.py")
        self.scroll(50)
        self.tick(1)
        self.assertEqual(self.st["time_bank_minutes"], 0)

    def test_scrolls_are_only_charged_once(self):
        self.set_fg("chrome.exe", "youtube shorts - google chrome")
        self.scroll(2)
        self.tick(3)
        self.assertEqual(self.st["time_bank_minutes"], -2)

    def test_hook_is_only_active_while_it_matters(self):
        self.set_fg("chrome.exe", "wikipedia - google chrome")
        self.tick(2)
        self.assertEqual(set(self.hook_active), {False})
        self.hook_active.clear()
        self.set_fg("chrome.exe", "youtube shorts - google chrome")
        self.tick(1)
        self.assertEqual(self.hook_active[-1], True)
        self.set_fg("chrome.exe", "wikipedia - google chrome")
        self.tick(2)
        self.assertEqual(self.hook_active[-1], True)                 # lingers a few seconds
        self.tick(5)
        self.assertEqual(self.hook_active[-1], False)

    def test_custom_keywords(self):
        self.st["doomscroll_keywords"] = ["memes"]
        self.set_fg("chrome.exe", "funny memes - google chrome")
        self.scroll(2)
        self.tick(1)
        self.assertEqual(self.st["time_bank_minutes"], -2)

    def test_is_doomscrolling_helper(self):
        self.set_fg("chrome.exe", "youtube shorts - google chrome")
        self.assertTrue(self.app._is_doomscrolling())
        self.set_fg("chrome.exe", "hello")
        self.assertFalse(self.app._is_doomscrolling())
        self.set_fg("code.exe", "shorts")
        self.assertFalse(self.app._is_doomscrolling())


@both
class BreakEnd(AppCase):
    def setUp(self):
        super().setUp()
        self.updates = []
        real = self.app.notifier.update
        self.app.notifier.update = lambda level, head, sub, voice_lines=None: self.updates.append(
            (level, head, voice_lines))
        self.addCleanup(setattr, self.app.notifier, "update", real)
        self.app.notifier.update.__name__ = "spy"

    def test_web_break_ending_relocks_and_alerts(self):
        self.app.cheat_break()
        self.updates.clear(); self.enforced.clear()
        self.tick(299)
        self.assertEqual(self.enforced, [])
        self.tick(2)
        self.assertEqual(self.enforced, [False])
        self.assertIn((3, "⏰ BREAK OVER", ["Break is over.", "Back to work now."]), self.updates)

    def test_gaming_break_ending_says_games_over(self):
        self.app.steam_break()
        self.updates.clear()
        self.tick(30 * 60 - 1)
        self.tick(2)
        self.assertTrue(any(h == "⏰ GAMES OVER" for _l, h, _v in self.updates), self.updates[-3:])

    def test_no_alert_when_a_break_is_cut_short_during_a_session(self):
        self.app.cheat_break()
        self.app.toggle_session()
        self.updates.clear()
        self.tick(400)
        self.assertFalse(any("OVER" in h for _l, h, _v in self.updates))

    def test_no_alert_outside_hours(self):
        self.st["unlock_until"] = MORNING + 3
        self.tick(1)
        self.set_time(NIGHT)
        self.st["unlock_until"] = NIGHT - 1
        self.updates.clear()
        self.tick(2)
        self.assertFalse(any("OVER" in h for _l, h, _v in self.updates))


@both
class Nagging(AppCase):
    def setUp(self):
        super().setUp()
        self.updates = []
        real = self.app.notifier.update
        self.app.notifier.update = lambda level, head, sub, voice_lines=None: self.updates.append(
            (self.fake.now, level, head))
        self.addCleanup(setattr, self.app.notifier, "update", real)
        self.stopped = []
        real_stop = self.app.notifier.stop
        self.app.notifier.stop = lambda: self.stopped.append(self.fake.now)
        self.addCleanup(setattr, self.app.notifier, "stop", real_stop)

    def test_level_table(self):
        L = self.app._level
        self.assertEqual([L(x) for x in (0, 7.9, 8, 24.9, 25, 69.9, 70, 149.9, 150, 299.9, 300, 9999)],
                         [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5])

    def test_interval_table(self):
        I = self.app._interval
        self.assertEqual([I(x) for x in (0, 7.9, 8, 24.9, 25, 69.9, 70, 149.9, 150, 9999)],
                         [6, 6, 4, 4, 3, 3, 2, 2, 1, 1])

    def test_maybe_nag_respects_the_interval_and_scale(self):
        a = self.app
        a.clock = 100
        a._maybe_nag(0, "H", "S")
        self.assertEqual(len(self.updates), 1)
        for c in range(101, 106):                    # interval for 'over=0' is 6 ticks at frequency 3
            a.clock = c
            a._maybe_nag(0, "H", "S")
        self.assertEqual(len(self.updates), 1)
        a.clock = 106
        a._maybe_nag(0, "H", "S")
        self.assertEqual(len(self.updates), 2)

    def test_frequency_scales_the_interval(self):
        for freq, itv in ((1, 15), (2, 10), (3, 6), (4, 4), (5, 2)):
            self.updates.clear()
            self.app.nag_frequency = freq
            self.app._last_nag_at = None
            self.app.clock = 0
            self.app._maybe_nag(0, "H", "S")
            self.app.clock = itv - 1
            self.app._maybe_nag(0, "H", "S")
            self.assertEqual(len(self.updates), 1, freq)
            self.app.clock = itv
            self.app._maybe_nag(0, "H", "S")
            self.assertEqual(len(self.updates), 2, freq)

    def test_floor_and_cap_levels(self):
        self.app._maybe_nag(0, "H", "S", floor_level=1)
        self.assertEqual(self.updates[-1][1], 1)
        self.app._last_nag_at = None
        self.app._maybe_nag(9999, "H", "S", cap_level=2)
        self.assertEqual(self.updates[-1][1], 2)

    def test_on_the_clock_without_a_session_starts_nagging_immediately(self):
        self.tick(1)
        self.assertEqual(self.updates[0][1:], (0, "START A SESSION"))

    def test_nag_escalates_the_longer_you_ignore_it(self):
        self.tick(400)
        levels = [lvl for _t, lvl, _h in self.updates]
        self.assertEqual(levels[0], 0)
        self.assertEqual(max(levels), 5)
        self.assertEqual(levels, sorted(levels))                 # never de-escalates
        gaps = [b[0] - a[0] for a, b in zip(self.updates, self.updates[1:])]
        self.assertGreater(gaps[0], gaps[-1])                    # and gets more frequent

    def test_no_nag_when_you_should_not_be_nagged(self):
        cases = {
            "snoozed": lambda: self.st.update(snooze_until=MORNING + 9999),
            "burnout": lambda: self.st.update(studied_today_min=9999),
            "low frequency": lambda: setattr(self.app, "nag_frequency", 1),
            "nuclear": lambda: self.st.update(nuclear_until=MORNING + 9999),
            "on a break": lambda: self.st.update(unlock_until=MORNING + 9999),
            "gaming break": lambda: self.st.update(steam_break_until=MORNING + 9999),
        }
        for name, setup in cases.items():
            self.updates.clear()
            self.app._noses_start = None
            self.app._last_nag_at = None
            self.app._break_prev = self.app._steam_prev = False       # a break ending is its own alert
            self.st.update(snooze_until=0, studied_today_min=0, nuclear_until=0, unlock_until=0,
                           steam_break_until=0)
            self.app.nag_frequency = 3
            setup()
            self.tick(3)
            self.assertEqual(self.updates, [], name)

    def test_no_nag_outside_hours_or_after_clock_out(self):
        for t in (NIGHT, EVENING):
            self.updates.clear()
            self.app._noses_start = None
            self.set_time(t)
            self.tick(3)
            self.assertEqual(self.updates, [], t)

    def test_a_running_session_silences_the_start_nag(self):
        self.tick(3)
        self.assertTrue(self.updates)
        self.app.toggle_session()
        self.updates.clear(); self.stopped.clear()
        self.tick(3)
        self.assertEqual(self.updates, [])
        self.assertTrue(self.stopped)

    def test_pausing_nags_you_to_resume_at_level_one_or_more(self):
        self.app.toggle_session()
        self.app.toggle_pause()
        self.updates.clear()
        self.tick(2)
        self.assertEqual(self.updates[0][2], "RESUME YOUR SESSION")
        self.assertGreaterEqual(self.updates[0][1], 1)

    def test_resuming_stops_the_pause_nag(self):
        self.app.toggle_session()
        self.app.toggle_pause()
        self.tick(2)
        self.stopped.clear()
        self.app.toggle_pause()
        self.assertTrue(self.stopped)
        self.assertIsNone(self.app._pause_start)

    def test_nag_stops_and_resets_when_nothing_to_nag_about(self):
        self.tick(3)
        self.st["snooze_until"] = MORNING + 9999
        self.stopped.clear()
        self.tick(1)
        self.assertTrue(self.stopped)
        self.assertIsNone(self.app._noses_start)
        self.assertIsNone(self.app._last_nag_at)

    def test_transient_alerts_are_left_to_finish(self):
        self.st["snooze_until"] = MORNING + 9999
        self.app._play_until = self.fake.now + 100
        self.stopped.clear()
        self.tick(1)
        self.assertEqual(self.stopped, [])
        self.fake.now += 200
        self.tick(1)
        self.assertTrue(self.stopped)

    def test_start_lines_are_used(self):
        seen = {}
        real = self.app.notifier.update
        self.app.notifier.update = lambda level, head, sub, voice_lines=None: seen.update(v=voice_lines)
        self.tick(1)
        self.assertEqual(seen["v"], self.app.START_LINES)
        self.app.notifier.update = real

    def test_nag_start_button_begins_a_session_and_raises_the_window(self):
        with mock.patch.object(self.app, "_bring_to_front") as front:
            self.app._nag_start_session()
        self.assertTrue(self.app.session_active)
        front.assert_called_once()
        self.app._nag_start_session()                                # already running: no toggle-off
        self.assertTrue(self.app.session_active)


@both
class NotifierWindows(AppCase):
    def setUp(self):
        super().setUp()
        self.n = self.app.notifier
        self.real_alarm = self.n.alarm
        self.alarm = mock.Mock()
        self.n.alarm = self.alarm
        self.n.strobe_enabled = True
        self.n.max_voices = 4
        self.n.voice = None
        self.n.nag_own = False
        self.n.own_lines = []

    def tearDown(self):
        self.n.stop()
        self.n.alarm = self.real_alarm
        super().tearDown()

    def size(self):
        self.n.win.update_idletasks()
        return self.n.win.geometry().split("+")[0]

    def test_window_grows_with_the_level(self):
        for level, want in ((0, "420x186"), (1, "420x186"), (2, "600x360"), (3, "700x430"),
                            (4, "700x430"), (5, "700x430")):
            self.n.update(level, "H", "S")
            self.assertEqual(self.size(), want, level)

    def test_text_and_icon(self):
        self.n.update(3, "HEADLINE", "sub text")
        self.assertEqual(self.n._t.cget("text"), "HEADLINE")
        self.assertEqual(self.n._s.cget("text"), "sub text")
        self.assertEqual(self.n._icon.cget("text"), fa.Notifier.ICONS[3])
        self.n.update(99, "H", "S")
        self.assertEqual(self.n._icon.cget("text"), fa.Notifier.ICONS[-1])

    def test_accent_colours_and_bounds(self):
        self.assertEqual(self.n._accent(0), fa.Notifier.ACCENTS[0])
        self.assertEqual(self.n._accent(99), fa.Notifier.ACCENTS[-1])

    def test_decoy_windows_only_at_the_top_levels(self):
        for level, want in ((0, 0), (3, 0), (4, 2), (5, 4)):
            self.n.stop()
            self.n.update(level, "H", "S")
            self.assertEqual(len(self.n.decoys), want, level)

    def test_alarm_follows_the_level(self):
        self.n.update(2, "H", "S")
        self.alarm.set_level.assert_called_with(2)
        self.n.stop()
        self.alarm.stop.assert_called()

    def test_stop_cleans_everything_up(self):
        self.n.update(5, "H", "S")
        win, decoys = self.n.win, list(self.n.decoys)
        self.n.stop()
        self.assertIsNone(self.n.win)
        self.assertEqual(self.n.decoys, [])
        self.assertEqual(self.n.level, -1)
        self.assertIsNone(self.n._strobe_job)
        self.assertFalse(win.winfo_exists())
        self.assertTrue(all(not d.winfo_exists() for d in decoys))

    def test_stop_when_nothing_is_showing(self):
        self.n.stop()
        self.n.stop()

    def test_strobe_only_when_enabled_and_level_two_plus(self):
        self.n.update(1, "H", "S")
        self.assertIsNone(self.n._strobe_job)
        self.n.update(3, "H", "S")
        self.assertIsNotNone(self.n._strobe_job)
        self.n.stop()
        self.n.strobe_enabled = False
        self.n.update(5, "H", "S")
        self.assertIsNone(self.n._strobe_job)

    def test_strobe_cycles_colours_and_stops_when_the_window_is_gone(self):
        self.n.update(5, "H", "S")
        seen = set()
        for _ in range(8):
            self.n._strobe()
            seen.add(str(self.n._top.cget("bg")))
        self.assertGreater(len(seen), 3)
        self.n.win = None
        self.n._strobe_job = "x"
        self.n._strobe()
        self.assertIsNone(self.n._strobe_job)

    def test_strobe_speed_never_drops_below_ninety_ms(self):
        self.n.update(5, "H", "S")
        with mock.patch.object(self.n.root, "after") as after:
            self.n._strobe()
        self.assertGreaterEqual(after.call_args[0][0], 90)

    def test_the_strobe_never_repaints_the_card_text(self):
        """Measured: recolouring the big card cost up to half a second a frame and froze the window.
        Only the thin accent bars and the decoy boxes may change colour while strobing."""
        self.n.update(5, "H", "S")
        card = (self.n.win, self.n._inner, self._icon_of(), self.n._t, self.n._s, self.n._btns)
        before = [str(w.cget("bg")) for w in card]
        for _ in range(30):
            self.n._strobe()
        self.assertEqual([str(w.cget("bg")) for w in card], before)
        self.assertNotEqual(str(self.n._top.cget("bg")), str(self.n._bot.cget("bg")))

    def _icon_of(self):
        return self.n._icon

    def test_strobe_calls_do_not_touch_the_text_labels(self):
        self.n.update(5, "H", "S")
        with mock.patch.object(self.n._t, "configure") as t, mock.patch.object(self.n._s, "configure") as s, \
                mock.patch.object(self.n._icon, "configure") as icon:
            for _ in range(20):
                self.n._strobe()
        t.assert_not_called(); s.assert_not_called(); icon.assert_not_called()

    def test_the_bars_are_thicker_at_the_top_levels(self):
        self.n.update(2, "H", "S")
        self.assertEqual(int(self.n._top.cget("height")), self.n.BAR_THIN)
        self.n.update(4, "H", "S")
        self.assertEqual(int(self.n._top.cget("height")), self.n.BAR_THICK)
        self.assertEqual(int(self.n._bot.cget("height")), self.n.BAR_THICK)
        self.n.update(3, "H", "S")
        self.assertEqual(int(self.n._top.cget("height")), self.n.BAR_THIN)

    def test_the_strobe_slows_down_when_the_window_cannot_keep_up(self):
        self.n.update(5, "H", "S")
        n = self.n
        base = n._strobe_base_delay()
        n._strobe()
        self.assertEqual(n._strobe_delay, base)
        speeds = []
        for _ in range(6):
            n._strobe_due = real_time.perf_counter() - 0.2                  # every frame arrives 200 ms late
            n._strobe()
            speeds.append(n._strobe_delay)
        self.assertEqual(speeds, sorted(speeds))                       # keeps backing off
        self.assertGreater(speeds[-1], base * 4)
        self.assertLessEqual(max(speeds), 600)                         # but never to a crawl

    def test_the_strobe_speeds_back_up_once_the_window_recovers(self):
        self.n.update(5, "H", "S")
        n = self.n
        n._strobe()
        n._strobe_delay = 400
        for _ in range(40):
            n._strobe_due = real_time.perf_counter()                   # on time
            n._strobe()
        self.assertEqual(n._strobe_delay, n._strobe_base_delay())

    def test_the_strobe_rate_is_always_capped(self):
        self.n.update(5, "H", "S")
        for lvl in (2, 3, 4, 5):
            self.n.level = lvl
            self.assertGreaterEqual(self.n._strobe_base_delay(), 90)

    def test_an_unchanged_card_is_not_repainted_every_second(self):
        self.n.update(5, "SAME", "same")
        with mock.patch.object(self.n._t, "configure") as t, mock.patch.object(self.n._icon, "configure") as icon, \
                mock.patch.object(self.n._inner, "configure") as inner:
            for _ in range(10):
                self.n.update(5, "SAME", "same")
        t.assert_not_called(); icon.assert_not_called(); inner.assert_not_called()

    def test_a_changed_headline_is_repainted(self):
        self.n.update(5, "ONE", "x")
        self.n.update(5, "TWO", "x")
        self.assertEqual(self.n._t.cget("text"), "TWO")
        self.n.update(5, "TWO", "changed")
        self.assertEqual(self.n._s.cget("text"), "changed")

    def test_stop_resets_the_strobe_pacing(self):
        self.n.update(5, "H", "S")
        self.n._strobe_delay = 500
        self.n.stop()
        self.assertEqual((self.n._strobe_delay, self.n._strobe_due, self.n._shown), (0, None, None))

    def test_decoys_still_flash(self):
        self.n.update(5, "H", "S")
        self.assertEqual(len(self.n.decoys), 4)
        seen = set()
        for _ in range(12):
            self.n._strobe()
            seen.add(str(self.n.decoys[0].cget("bg")))
        self.assertGreater(len(seen), 2)

    def voices(self, level, **kw):
        self.overlaps.clear()
        self.n._last_voice = -1e9            # the burst throttle has its own tests below
        self.n.update(level, "H", "S", **kw)
        return self.overlaps[-1] if self.overlaps else None

    def test_no_voices_below_level_two(self):
        self.assertIsNone(self.voices(0))
        self.assertIsNone(self.voices(1))

    def test_voice_count_grows_but_is_capped(self):
        self.assertEqual(self.voices(2)[1], 1)
        self.assertEqual(self.voices(3)[1], 2)
        self.assertEqual(self.voices(5)[1], 4)
        self.n.max_voices = 2
        self.assertEqual(self.voices(5)[1], 2)

    def test_line_selection(self):
        n = fa.Notifier
        self.assertEqual(self.voices(3)[0], n.NAG_LINES)
        self.assertEqual(self.voices(5)[0], n.MAD_LINES)                    # the rude lines only at the top
        self.assertEqual(self.voices(3, voice_lines=["a"])[0], ["a"])
        self.assertEqual(self.voices(5, voice_lines=["a"])[0], ["a"] + n.MAD_LINES)
        self.n.nag_own, self.n.own_lines = True, ["mine"]
        self.assertEqual(self.voices(3)[0], ["mine"])
        self.assertEqual(self.voices(3, voice_lines=["ctx"])[0], ["ctx"])     # context lines win
        self.assertEqual(self.voices(5)[0], ["mine"] + n.MAD_LINES)

    def test_chosen_voice_is_passed_through(self):
        self.n.voice = "Voice A"
        self.assertEqual(self.voices(3)[2], "Voice A")

    def test_custom_recordings_at_level_three_plus(self):
        self.customs.clear()
        self.n.update(2, "H", "S")
        self.assertEqual(self.customs, [])
        self.n._last_voice = -1e9
        self.n.update(3, "H", "S")
        self.n._last_voice = -1e9
        self.n.update(5, "H", "S")
        self.assertEqual(self.customs, [1, 3])

    def test_voice_bursts_are_throttled_however_often_the_card_refreshes(self):
        self.overlaps.clear(); self.customs.clear()
        self.n._last_voice = -1e9
        for _ in range(10):
            self.n.update(5, "H", "S")                       # ten updates, no time passing
        self.assertEqual((len(self.overlaps), len(self.customs)), (1, 1))
        self.fake.advance(self.n.VOICE_MIN_GAP - 0.1)
        self.n.update(5, "H", "S")
        self.assertEqual(len(self.overlaps), 1)               # still inside the gap
        self.fake.advance(0.2)
        self.n.update(5, "H", "S")
        self.assertEqual((len(self.overlaps), len(self.customs)), (2, 2))

    def test_throttled_updates_still_refresh_the_card(self):
        self.n._last_voice = -1e9
        self.n.update(5, "FIRST", "a")
        self.n.update(5, "SECOND", "b")                       # voices throttled, card not
        self.assertEqual(self.n._t.cget("text"), "SECOND")
        self.assertEqual(self.n._s.cget("text"), "b")

    def test_a_new_alert_after_stop_speaks_straight_away(self):
        self.n._last_voice = -1e9
        self.n.update(3, "H", "S")
        self.n.stop()
        self.overlaps.clear()
        self.n.update(3, "H", "S")                            # stop() resets the throttle
        self.assertEqual(len(self.overlaps), 1)

    def test_the_window_is_not_re_laid_out_every_second_at_a_steady_level(self):
        self.n.update(5, "H", "S")
        with mock.patch.object(self.n.win, "geometry") as geo, \
                mock.patch.object(self.n.win, "attributes") as attrs:
            for _ in range(5):
                self.n.update(5, "H", "S")
            geo.assert_not_called()
            attrs.assert_not_called()
            self.n.update(4, "H", "S")                        # a level change does re-style it
            geo.assert_called()

    def test_the_small_corner_card_still_jiggles(self):
        self.n.update(1, "H", "S")
        with mock.patch.object(self.n.win, "geometry") as geo:
            self.n.update(1, "H", "S")
            geo.assert_called()

    def test_action_buttons_call_back_and_close(self):
        got = []
        self.n.on_start = lambda: got.append("start")
        self.n.on_snooze = lambda: got.append("snooze")
        self.n.update(2, "H", "S")
        self.n._do_start()
        self.assertIsNone(self.n.win)
        self.n.update(2, "H", "S")
        self.n._do_snooze()
        self.assertEqual(got, ["start", "snooze"])

    def test_a_failing_callback_never_breaks_the_notifier(self):
        self.n.on_start = lambda: 1 / 0
        self.n.on_snooze = None
        self.n.update(2, "H", "S")
        self.n._do_start()
        self.n.update(2, "H", "S")
        self.n._do_snooze()

    def test_window_closed_behind_our_back_is_rebuilt(self):
        self.n.update(2, "H", "S")
        self.n.win.destroy()
        self.n.update(2, "H", "S")
        self.assertTrue(self.n.win.winfo_exists())

    def test_repeated_updates_reuse_the_window(self):
        self.n.update(2, "H", "S")
        first = self.n.win
        self.n.update(3, "H2", "S2")
        self.assertIs(self.n.win, first)

    def test_test_notification_shows_then_auto_dismisses(self):
        with mock.patch.object(self.app.root, "after") as after:
            self.app.test_notification()
        self.assertIsNotNone(self.n.win)
        self.assertEqual(after.call_args[0][0], 5000)
        self.assertEqual(self.overlaps[-1][0], ["This is a test.", "Notifications are working."])


@both
class BackgroundEnforcement(AppCase):
    def setUp(self):
        super().setUp()
        self.calls, self.threads, self.refreshes = [], [], []
        self.gate = threading.Event()
        self.gate.set()

        def slow_apply(st, now=None):
            self.threads.append(threading.get_ident())
            self.calls.append(1)
            self.gate.wait(2)
        p1 = mock.patch.object(core, "apply_enforcement", slow_apply)
        p2 = mock.patch.object(core, "refresh_hosts_block", lambda st: self.refreshes.append(1))
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        self.real = types.MethodType(type(self).real_enforce_async, self.app)

    def settle(self):
        self.assertTrue(self.wait_for(lambda: not self.app._enforce_busy))

    def test_runs_off_the_ui_thread(self):
        self.real()
        self.settle()
        self.assertEqual(len(self.calls), 1)
        self.assertNotEqual(self.threads[0], threading.get_ident())

    def test_a_burst_of_requests_is_coalesced(self):
        self.gate.clear()
        for _ in range(10):
            self.real()
        self.gate.set()
        self.settle()
        self.assertLessEqual(len(self.calls), 2)
        self.assertGreaterEqual(len(self.calls), 1)

    def test_the_caller_never_waits(self):
        self.gate.clear()
        t = real_time.perf_counter()
        for _ in range(20):
            self.real()
        self.assertLess(real_time.perf_counter() - t, 0.5)
        self.gate.set()
        self.settle()

    def test_refresh_flag_forces_a_hosts_rewrite(self):
        self.real(refresh=True)
        self.settle()
        self.assertEqual(len(self.refreshes), 1)
        self.real()
        self.settle()
        self.assertEqual(len(self.refreshes), 1)

    def test_errors_are_swallowed_and_the_worker_recovers(self):
        with mock.patch.object(core, "apply_enforcement", side_effect=RuntimeError):
            self.real()
            self.settle()
        self.assertFalse(self.app._enforce_busy)
        self.real()
        self.settle()
        self.assertEqual(len(self.calls), 1)

    def test_loop_kicks_enforcement_and_reschedules(self):
        spy = []
        self.app._enforce_async = lambda refresh=False: spy.append(1)
        with mock.patch.object(self.app.root, "after") as after:
            type(self).real_enforce_loop(self.app)
        self.assertEqual(spy, [1])
        after.assert_called_once_with(3000, self.app._enforce_loop)


class Startup(unittest.TestCase):
    def test_non_admin_on_windows_relaunches_elevated(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch.object(core, "is_admin", return_value=False), \
                mock.patch.object(core, "relaunch_as_admin") as re, mock.patch.object(fa, "FocusApp") as app:
            fa.main()
        re.assert_called_once()
        app.assert_not_called()

    def test_second_copy_exits_quietly(self):
        with mock.patch.object(core, "is_admin", return_value=True), \
                mock.patch.object(core, "claim_app_instance", return_value=False), \
                mock.patch.object(core, "apply_enforcement") as ap, mock.patch.object(fa, "FocusApp") as app:
            fa.main()
        ap.assert_not_called()
        app.assert_not_called()

    def test_normal_start_enforces_then_runs(self):
        with mock.patch.object(core, "is_admin", return_value=True), \
                mock.patch.object(core, "claim_app_instance", return_value=True), \
                mock.patch.object(core, "scrub_state_file"), \
                mock.patch.object(core, "load_state", return_value={"x": 1}), \
                mock.patch.object(core, "apply_enforcement") as ap, mock.patch.object(fa, "FocusApp") as app:
            fa.main()
        ap.assert_called_once_with({"x": 1})
        app.return_value.run.assert_called_once()

    def test_start_cleans_the_state_file_before_enforcing(self):
        order = []
        with mock.patch.object(core, "is_admin", return_value=True), \
                mock.patch.object(core, "claim_app_instance", return_value=True), \
                mock.patch.object(core, "scrub_state_file", side_effect=lambda: order.append("scrub")), \
                mock.patch.object(core, "load_state", return_value={}), \
                mock.patch.object(core, "apply_enforcement", side_effect=lambda st: order.append("enforce")), \
                mock.patch.object(fa, "FocusApp"):
            fa.main()
        self.assertEqual(order, ["scrub", "enforce"])

    def test_a_second_copy_never_touches_the_state_file(self):
        with mock.patch.object(core, "is_admin", return_value=True), \
                mock.patch.object(core, "claim_app_instance", return_value=False), \
                mock.patch.object(core, "scrub_state_file") as scrub, mock.patch.object(fa, "FocusApp"):
            fa.main()
        scrub.assert_not_called()

    def test_non_windows_without_root_still_runs_with_a_warning(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "is_admin", return_value=False), \
                mock.patch.object(core, "claim_app_instance", return_value=True), \
                mock.patch.object(core, "load_state", return_value={}), \
                mock.patch.object(core, "apply_enforcement"), mock.patch.object(fa, "FocusApp") as app, \
                mock.patch("builtins.print") as pr:
            fa.main()
        app.return_value.run.assert_called_once()
        self.assertIn("sudo", pr.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
