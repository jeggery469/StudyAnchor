"""FocusApp behaviour: sessions, every kind of break, nuclear, settings, blocklist, reminders.
Every test class runs twice: on customtkinter and on the plain-tkinter fallback."""
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from appsupport import AppCase
from support import MORNING, EVENING, NIGHT, ts, SAT_EARLY
import core
import focusapp as fa


def both(cls):
    """Also run this test class on the plain-tkinter path."""
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


@both
class Construction(AppCase):
    def test_windows_exist_and_start_as_the_mini_popout(self):
        self.assertTrue(self.app.is_mini)
        self.assertEqual(self.app.root.state(), "withdrawn")
        self.assertNotEqual(self.app.popout.state(), "withdrawn")

    def test_only_the_popout_is_always_on_top(self):
        self.assertFalse(bool(int(self.app.root.attributes("-topmost"))))
        self.assertTrue(bool(int(self.app.popout.attributes("-topmost"))))

    def test_widget_toolkit_matches_the_mode(self):
        self.assertEqual(hasattr(self.app, "tabs"), self.CTK)

    def test_settings_form_has_every_field(self):
        self.assertEqual(set(self.app.set_entries),
                         {"session_length_min", "snooze_min", "daily_study_cap_min",
                          "steam_break_min", "steam_cooldown_min"})
        self.assertEqual(set(self.app.slider_widgets), {"nag_frequency", "alarm_speed", "max_voices"})

    def test_initial_state_is_idle(self):
        self.assertFalse(self.app.session_active)
        self.assertFalse(self.app.session_manual_paused)
        self.assertIsNone(self.app.secret)
        self.assertEqual(self.app._tick_errors, 0)

    def test_first_run_saves_todays_cheat_day(self):
        self.assertEqual(self.st["cheat_day"], datetime.now().strftime("%Y-%m-%d"))


@both
class Sessions(AppCase):
    def test_start_sets_the_timer_clears_breaks_and_enforces(self):
        self.st["unlock_until"] = MORNING + 999
        self.app.toggle_session()
        self.assertTrue(self.app.session_active)
        self.assertEqual(self.app.session_remaining, 45 * 60)
        self.assertEqual(self.st["unlock_until"], 0)
        self.assertEqual(self.enforced, [False])

    def test_stop_ends_the_session_without_a_reward(self):
        self.app.toggle_session()
        self.app.toggle_session()
        self.assertFalse(self.app.session_active)
        self.assertEqual(self.st["time_bank_minutes"], 0)

    def test_countdown_uses_real_elapsed_time(self):
        self.app.toggle_session()
        self.tick(10)
        self.assertAlmostEqual(self.app.session_remaining, 45 * 60 - 10)

    def test_a_long_gap_is_capped_so_sleep_does_not_finish_the_session(self):
        self.app.toggle_session()
        self.tick(1)
        self.fake.advance(3600)                  # laptop slept for an hour
        self.app._tick_body()
        self.assertAlmostEqual(self.app.session_remaining, 45 * 60 - 1 - 3)
        self.assertTrue(self.app.session_active)

    def test_a_slow_tick_still_counts_its_real_length(self):
        self.app.toggle_session()
        self.tick(1)
        self.tick(1, dt=2.5)
        self.assertAlmostEqual(self.app.session_remaining, 45 * 60 - 3.5)

    def test_pause_freezes_the_timer_and_resume_continues(self):
        self.app.toggle_session()
        self.tick(5)
        self.app.toggle_pause()
        self.assertTrue(self.app.session_manual_paused)
        left = self.app.session_remaining
        self.tick(30)
        self.assertEqual(self.app.session_remaining, left)
        self.app.toggle_pause()
        self.tick(5)
        self.assertAlmostEqual(self.app.session_remaining, left - 5)

    def test_pause_without_a_session_does_nothing(self):
        self.app.toggle_pause()
        self.assertFalse(self.app.session_manual_paused)

    def test_finishing_rewards_the_bank_cheats_and_study_time(self):
        self.st["cheat_index"] = 4
        self.st["session_length_min"] = 1
        self.app.toggle_session()
        self.tick(60)
        self.assertFalse(self.app.session_active)
        self.assertEqual(self.st["time_bank_minutes"], core.SESSION_REWARD_MIN)
        self.assertEqual(self.st["cheat_index"], 0)
        self.assertEqual(self.st["studied_today_min"], 1)
        self.assertIn("Session complete! 🎉", self.popup_titles())
        self.assertIn(("beeps", 3, 1100, 160), self.beeped)

    def test_rewards_stack_across_sessions(self):
        self.st["session_length_min"] = 1
        for _ in range(3):
            self.app.toggle_session()
            self.tick(60)
        self.assertEqual(self.st["time_bank_minutes"], 3 * core.SESSION_REWARD_MIN)

    def test_crossing_the_daily_cap_tells_you_to_rest(self):
        self.st["daily_study_cap_min"] = 1
        self.st["session_length_min"] = 1
        self.app.toggle_session()
        self.tick(60)
        self.assertIn("🌿 That's enough for today", self.popup_titles())
        self.assertEqual(self.chimes, [1])
        self.assertTrue(core.burnout(self.st))

    def test_no_rest_message_when_already_over_the_cap(self):
        self.st["daily_study_cap_min"] = 1
        self.st["studied_today_min"] = 5
        self.st["session_length_min"] = 1
        self.app.toggle_session()
        self.tick(60)
        self.assertNotIn("🌿 That's enough for today", self.popup_titles())

    def test_state_is_persisted(self):
        self.st["session_length_min"] = 1
        self.app.toggle_session()
        self.tick(60)
        self.assertEqual(core.load_state()["time_bank_minutes"], core.SESSION_REWARD_MIN)

    def test_new_day_resets_cheats_and_study_counter(self):
        self.st.update(cheat_day="1999-01-01", cheat_index=4, studied_today_min=100)
        self.app._maybe_reset_cheat_day()
        self.assertEqual((self.st["cheat_index"], self.st["studied_today_min"]), (0, 0))
        self.assertEqual(self.st["cheat_day"], datetime.now().strftime("%Y-%m-%d"))

    def test_same_day_does_not_reset(self):
        self.st.update(cheat_index=3, studied_today_min=50)
        self.app._maybe_reset_cheat_day()
        self.assertEqual((self.st["cheat_index"], self.st["studied_today_min"]), (3, 50))


@both
class CheatBreaks(AppCase):
    def test_a_cheat_gives_five_minutes_and_uses_one(self):
        self.app.cheat_break()
        self.assertEqual(self.st["unlock_until"], MORNING + 300)
        self.assertEqual(self.st["cheat_index"], 1)
        self.assertEqual(self.enforced, [False])
        self.assertFalse(core.sites_blocked(self.st, MORNING + 1))
        self.assertTrue(core.sites_blocked(self.st, MORNING + 301))

    def test_exactly_the_ladders_cheats_then_none(self):
        for i in range(len(core.CHEAT_LADDER) - 1):
            self.app.cheat_break()
            self.assertEqual(self.st["cheat_index"], i + 1, i)
            self.fake.advance(301)
        self.popups.clear()
        before = self.st["unlock_until"]
        self.app.cheat_break()
        self.assertEqual(self.st["unlock_until"], before)
        self.assertEqual(self.popup_titles(), ["No cheats left today"])

    def test_the_sixth_cheat_never_advances_past_the_ladder(self):
        for _ in range(9):
            self.app.cheat_break()
            self.fake.advance(301)
        self.assertLessEqual(self.st["cheat_index"], len(core.CHEAT_LADDER) - 1)

    def test_cannot_burn_a_second_cheat_during_a_break(self):
        self.app.cheat_break()
        self.popups.clear()
        self.app.cheat_break()
        self.assertEqual(self.st["cheat_index"], 1)
        self.assertEqual(self.popup_titles(), ["Already on a break"])

    def test_finishing_a_session_gives_them_back(self):
        for _ in range(len(core.CHEAT_LADDER) - 1):
            self.app.cheat_break()
            self.fake.advance(301)
        self.st["session_length_min"] = 1
        self.app.toggle_session()
        self.tick(60)
        self.popups.clear()
        self.app.cheat_break()
        self.assertEqual(self.st["cheat_index"], 1)

    def test_refused_during_a_session(self):
        self.app.toggle_session()
        self.app.cheat_break()
        self.assertEqual(self.st["cheat_index"], 0)
        self.assertEqual(self.st["unlock_until"], 0)
        self.assertEqual(self.popup_titles(), ["You're in a session"])

    def test_refused_during_nuclear(self):
        self.st["nuclear_until"] = MORNING + 100
        self.app.cheat_break()
        self.assertEqual(self.st["cheat_index"], 0)
        self.assertEqual(self.popup_titles(), ["☢ Nuclear lockdown"])

    def test_refused_when_sites_are_already_free(self):
        for t in (NIGHT, EVENING):
            self.set_time(t)
            self.popups.clear()
            self.app.cheat_break()
            self.assertEqual(self.popup_titles(), ["Nothing to cheat"])
            self.assertEqual(self.st["cheat_index"], 0)

    def test_plays_the_callout_so_a_cheat_never_feels_free(self):
        self.app.cheat_break()
        self.assertEqual(len(self.overlaps), 1)
        self.assertEqual(self.overlaps[0][0], self.app.CHEAT_LINES)
        self.assertGreater(self.app._play_until, MORNING)


@both
class BankBreaks(AppCase):
    def test_grant_spends_minutes_and_opens_the_sites(self):
        self.st["time_bank_minutes"] = 40
        self.assertTrue(self.app._grant_bank(15))
        self.assertEqual(self.st["time_bank_minutes"], 25)
        self.assertEqual(self.st["unlock_until"], MORNING + 900)
        self.assertEqual(self.enforced, [False])

    def test_never_spends_more_than_the_balance(self):
        self.st["time_bank_minutes"] = 7
        self.assertTrue(self.app._grant_bank(30))
        self.assertEqual(self.st["time_bank_minutes"], 0)
        self.assertEqual(self.st["unlock_until"], MORNING + 7 * 60)

    def test_empty_or_negative_bank_grants_nothing(self):
        for bank in (0, -5):
            self.st["time_bank_minutes"] = bank
            self.assertFalse(self.app._grant_bank(10))
            self.assertEqual(self.st["unlock_until"], 0)
            self.assertEqual(self.st["time_bank_minutes"], bank)

    def test_zero_or_negative_request_grants_nothing(self):
        self.st["time_bank_minutes"] = 10
        self.assertFalse(self.app._grant_bank(0))
        self.assertFalse(self.app._grant_bank(-5))
        self.assertEqual(self.st["time_bank_minutes"], 10)

    def test_cannot_stack_or_shorten_an_existing_break(self):
        self.st["time_bank_minutes"] = 40
        self.st["unlock_until"] = MORNING + 1800
        self.assertFalse(self.app._grant_bank(5))
        self.assertEqual(self.st["unlock_until"], MORNING + 1800)
        self.assertEqual(self.st["time_bank_minutes"], 40)

    def test_refused_in_session_and_nuclear(self):
        self.st["time_bank_minutes"] = 40
        self.app.session_active = True
        self.assertFalse(self.app._grant_bank(5))
        self.app.session_active = False
        self.st["nuclear_until"] = MORNING + 60
        self.assertFalse(self.app._grant_bank(5))

    def test_cannot_chain_bank_breaks_back_to_back(self):
        """A break shorter than the cooldown (e.g. a custom 1-min grant) must not let you queue
        another the instant it ends — the cooldown is timed from when the break STARTED."""
        self.st["time_bank_minutes"] = 40
        self.assertTrue(self.app._grant_bank(1))
        self.fake.advance(61)                                # the 1-min break has ended
        self.assertFalse(self.app._grant_bank(5))            # but the cooldown hasn't
        self.assertEqual(self.st["time_bank_minutes"], 39)   # nothing extra was charged

    def test_bank_break_is_allowed_again_after_the_cooldown(self):
        self.st["time_bank_minutes"] = 40
        self.app._grant_bank(1)
        self.fake.advance(core.BANK_COOLDOWN_MIN * 60)
        self.assertTrue(self.app._grant_bank(5))
        self.assertEqual(self.st["time_bank_minutes"], 34)

    def test_cooldown_is_measured_from_the_start_of_the_last_break(self):
        """A break at least as long as the cooldown satisfies it by the time the break ends —
        the cooldown isn't extra time tacked on top of every break, just a floor under short ones."""
        self.st["time_bank_minutes"] = 100
        self.app._grant_bank(core.BANK_COOLDOWN_MIN)          # break length == cooldown
        self.fake.advance(core.BANK_COOLDOWN_MIN * 60 + 1)    # the break just ended
        self.assertTrue(self.app._grant_bank(5))

    def test_spend_dialog_reports_the_cooldown(self):
        self.st["time_bank_minutes"] = 40
        self.app._grant_bank(1)
        self.fake.advance(61)                     # the break itself has ended...
        self.app.spend_bank()
        self.assertEqual(self.popup_titles(), ["Bank on cooldown"])   # ...but the cooldown hasn't
        self.assertEqual(self.st["time_bank_minutes"], 39)            # nothing extra was charged

    def test_spend_dialog_popups(self):
        self.app.spend_bank()
        self.assertEqual(self.popup_titles(), ["Bank empty"])
        self.popups.clear()
        self.st["time_bank_minutes"] = 20
        self.st["unlock_until"] = MORNING + 100
        self.app.spend_bank()
        self.assertEqual(self.popup_titles(), ["Already on a break"])
        self.popups.clear()
        self.app.session_active = True
        self.app.spend_bank()
        self.assertEqual(self.popup_titles(), ["You're in a session"])

    def test_spend_dialog_opens_when_allowed(self):
        self.st["time_bank_minutes"] = 20
        before = len(self.app.root.winfo_children())
        self.app.spend_bank()
        self.assertEqual(self.popups, [])
        self.assertGreater(len(self.app.root.winfo_children()), before)

    def test_fractional_balance_under_one_minute_is_empty(self):
        self.st["time_bank_minutes"] = 0.9
        self.app.spend_bank()
        self.assertEqual(self.popup_titles(), ["Bank empty"])


@both
class GamingBreaks(AppCase):
    def test_starts_a_break_and_the_cooldown(self):
        self.app.steam_break()
        self.assertEqual(self.st["steam_break_until"], MORNING + 30 * 60)
        self.assertEqual(self.st["steam_last_break"], MORNING)
        self.assertFalse(core.steam_blocked(self.st, MORNING + 10))
        self.assertTrue(core.steam_blocked(self.st, MORNING + 31 * 60))

    def test_a_gaming_break_does_not_unblock_websites(self):
        self.app.steam_break()
        self.assertTrue(core.sites_blocked(self.st, MORNING + 10))

    def test_already_open(self):
        self.app.steam_break()
        self.popups.clear()
        self.fake.advance(60)
        self.app.steam_break()
        self.assertEqual(self.popup_titles(), ["Games already open"])

    def test_cooldown_blocks_a_second_break(self):
        self.app.steam_break()
        self.fake.advance(31 * 60)            # break over, cooldown (90 min) still running
        self.popups.clear()
        self.app.steam_break()
        self.assertEqual(self.popup_titles(), ["Gaming on cooldown"])
        self.fake.advance(60 * 60)
        self.popups.clear()
        self.app.steam_break()
        self.assertEqual(self.popups, [])
        self.assertGreater(self.st["steam_break_until"], self.fake.now)

    def test_refused_in_session_nuclear_and_when_already_free(self):
        self.app.session_active = True
        self.app.steam_break()
        self.assertEqual(self.popup_titles(), ["You're in a session"])
        self.app.session_active = False
        self.popups.clear()
        self.st["nuclear_until"] = MORNING + 60
        self.app.steam_break()
        self.assertEqual(self.popup_titles(), ["☢ Nuclear lockdown"])
        self.st["nuclear_until"] = 0
        self.popups.clear()
        self.set_time(NIGHT)
        self.app.steam_break()
        self.assertEqual(self.popup_titles(), ["Games already free"])
        self.assertEqual(self.st["steam_break_until"], 0)
        self.assertEqual(self.st["steam_last_break"], 0)      # a refused break must not start the cooldown

    def test_uses_the_configured_length(self):
        self.st["steam_break_min"] = 10
        self.app.steam_break()
        self.assertEqual(self.st["steam_break_until"], MORNING + 600)

    def test_plays_the_callout(self):
        self.app.steam_break()
        self.assertEqual(len(self.overlaps), 1)


@both
class DayOffCode(AppCase):
    def test_right_guess_is_a_break_until_midnight(self):
        self.app.secret = "042"
        self.assertTrue(self.app._try_code(" 042 "))
        self.assertEqual(self.st["unlock_until"], core.next_midnight(MORNING))
        self.assertIsNone(self.app.secret)
        self.assertEqual(self.enforced, [False])
        self.assertFalse(core.sites_blocked(self.st, MORNING + 5))

    def test_wrong_guess_rerolls_the_code(self):
        self.app.secret = "042"
        seen = set()
        for _ in range(30):
            self.assertFalse(self.app._try_code("xyz"))
            self.assertRegex(self.app.secret, r"^\d{3}$")
            seen.add(self.app.secret)
        self.assertGreater(len(seen), 1)
        self.assertEqual(self.st["unlock_until"], 0)

    def test_no_code_means_no_free_pass(self):
        self.app.secret = None
        for guess in ("", "000", "None"):
            self.assertFalse(self.app._try_code(guess))
        self.assertEqual(self.st["unlock_until"], 0)

    def test_refused_in_session_and_nuclear_even_if_correct(self):
        self.app.secret = "111"
        self.app.session_active = True
        self.assertFalse(self.app._try_code("111"))
        self.app.session_active = False
        self.app.secret = "111"
        self.st["nuclear_until"] = MORNING + 60
        self.assertFalse(self.app._try_code("111"))
        self.assertEqual(self.st["unlock_until"], 0)

    def test_dialog_guards_and_opens(self):
        self.st["unlock_until"] = MORNING + 100
        self.app.disable_dialog()
        self.assertEqual(self.popup_titles(), ["Already on a break"])
        self.popups.clear()
        self.st["unlock_until"] = 0
        self.set_time(NIGHT)
        self.app.disable_dialog()
        self.assertEqual(self.popup_titles(), ["Already free"])
        self.popups.clear()
        self.set_time(MORNING)
        self.app.disable_dialog()
        self.assertEqual(self.popups, [])
        self.assertRegex(self.app.secret, r"^\d{3}$")

    def test_dialog_refused_in_session_and_nuclear(self):
        self.app.session_active = True
        self.app.disable_dialog()
        self.assertEqual(self.popup_titles(), ["You're in a session"])
        self.app.session_active = False
        self.popups.clear()
        self.st["nuclear_until"] = MORNING + 60
        self.app.disable_dialog()
        self.assertEqual(self.popup_titles(), ["☢ Nuclear lockdown"])


@both
class EndBreaksAndSnooze(AppCase):
    def test_end_all_breaks_relocks_immediately(self):
        self.st.update(unlock_until=MORNING + 900, steam_break_until=MORNING + 900)
        self.app.end_all_breaks()
        self.assertEqual((self.st["unlock_until"], self.st["steam_break_until"]), (0, 0))
        self.assertEqual(self.enforced, [False])
        self.assertEqual(self.popup_titles(), ["🔒 Locked back in"])

    def test_end_all_breaks_when_locked_in_already(self):
        self.app.end_all_breaks()
        self.assertEqual(self.popup_titles(), ["Already locked in"])
        self.assertEqual(self.enforced, [])

    def test_ends_either_kind_alone(self):
        self.st["steam_break_until"] = MORNING + 900
        self.app.end_all_breaks()
        self.assertEqual(self.st["steam_break_until"], 0)

    def test_snooze_pauses_nudges_for_the_configured_time(self):
        self.st["snooze_min"] = 7
        self.app.snooze()
        self.assertEqual(self.st["snooze_until"], MORNING + 420)
        self.assertEqual(self.popup_titles(), ["😴 Snoozed 7 min"])
        self.assertTrue(core.sites_blocked(self.st, MORNING + 5))          # sites stay blocked

    def test_snooze_refused_during_nuclear(self):
        self.st["nuclear_until"] = MORNING + 60
        self.app.snooze()
        self.assertEqual(self.st["snooze_until"], 0)
        self.assertEqual(self.popup_titles(), ["☢ Nuclear lockdown"])

    def test_snooze_stops_a_running_nag(self):
        self.app.notifier.update(2, "x", "y")
        self.app.snooze()
        self.assertIsNone(self.app.notifier.win)


@both
class Nuclear(AppCase):
    def test_arm_for_a_duration(self):
        until = self.app._arm_nuclear(60)
        self.assertEqual(until, MORNING + 3600)
        self.assertTrue(core.nuclear(self.st, MORNING + 1))
        self.assertEqual(self.enforced, [False])
        self.assertEqual(core.load_state()["nuclear_until"], MORNING + 3600)

    def test_rest_of_the_day_is_next_midnight(self):
        self.assertEqual(self.app._arm_nuclear(0, rest=True), core.next_midnight(MORNING))

    def test_can_only_ever_extend(self):
        self.app._arm_nuclear(240)
        self.app._arm_nuclear(30)                     # a stale second dialog must not shorten it
        self.assertEqual(self.st["nuclear_until"], MORNING + 4 * 3600)
        self.app._arm_nuclear(0, rest=True)
        self.assertEqual(self.st["nuclear_until"], core.next_midnight(MORNING))

    def test_uses_the_time_of_the_click_not_of_the_dialog(self):
        self.fake.advance(600)
        self.assertEqual(self.app._arm_nuclear(30), MORNING + 600 + 1800)

    def test_blocks_every_escape(self):
        self.app._arm_nuclear(60)
        self.st["time_bank_minutes"] = 99
        for action in (self.app.cheat_break, self.app.spend_bank, self.app.steam_break,
                       self.app.disable_dialog, self.app.snooze):
            self.popups.clear()
            action()
            self.assertEqual(self.popup_titles(), ["☢ Nuclear lockdown"], action.__name__)
        self.assertEqual(self.st["unlock_until"], 0)
        self.assertEqual(self.st["time_bank_minutes"], 99)

    def test_blocks_even_outside_hours(self):
        self.app._arm_nuclear(60)
        self.set_time(MORNING)
        self.assertTrue(core.sites_blocked(self.st, MORNING + 10))

    def test_expires(self):
        self.app._arm_nuclear(30)
        self.assertFalse(core.nuclear(self.st, MORNING + 1801))

    def test_go_nuclear_when_already_armed_only_reports(self):
        self.app._arm_nuclear(30)
        self.popups.clear()
        before = len(self.app.root.winfo_children())
        self.app.go_nuclear()
        self.assertEqual(self.popup_titles(), ["☢ Already nuclear"])
        self.assertEqual(len(self.app.root.winfo_children()), before)

    def test_dialog_opens_when_idle(self):
        before = len(self.app.root.winfo_children())
        self.app.go_nuclear()
        self.assertGreater(len(self.app.root.winfo_children()), before)
        self.assertEqual(self.popups, [])

    def test_guard_message_names_the_end_time(self):
        self.st["nuclear_until"] = ts(2026, 9, 23, 14, 5)
        self.assertTrue(self.app._nuke_guard())
        self.assertIn("14:05", self.popups[-1][1])

    def test_session_guard(self):
        self.assertFalse(self.app._session_guard())
        self.app.session_active = True
        self.assertTrue(self.app._session_guard())


@both
class Settings(AppCase):
    def fill(self, **values):
        for k, v in values.items():
            self.app._set_entry(self.app.set_entries[k], str(v))

    def setUp(self):
        super().setUp()
        self.app._show_full()
        self.popups.clear()

    def msg(self):
        return self.text_of(self.app.set_msg)

    def test_form_shows_the_saved_values(self):
        for k, e in self.app.set_entries.items():
            self.assertEqual(e.get(), str(self.st[k]))

    def test_valid_save_persists_and_pushes_to_the_notifier(self):
        self.app.strobe_var.set(0)
        self.app.slider_widgets["max_voices"][0].set(2)
        self.app.slider_widgets["alarm_speed"][0].set(5)
        self.app.slider_widgets["nag_frequency"][0].set(4)
        self.fill(session_length_min=60, snooze_min=5, daily_study_cap_min=300,
                  steam_break_min=20, steam_cooldown_min=120)
        self.app.save_settings()
        self.assertEqual(self.msg(), "Saved.")
        got = core.load_state()
        self.assertEqual((got["session_length_min"], got["snooze_min"], got["daily_study_cap_min"],
                          got["steam_break_min"], got["steam_cooldown_min"]), (60, 5, 300, 20, 120))
        self.assertFalse(got["strobe_enabled"])
        n = self.app.notifier
        self.assertEqual((n.max_voices, n.alarm.speed, n.strobe_enabled), (2, 5, False))
        self.assertEqual(self.app.nag_frequency, 4)

    def test_only_tightening_is_allowed(self):
        rules = {"session_length_min": ("up", 45), "daily_study_cap_min": ("up", 240),
                 "steam_cooldown_min": ("up", 90), "snooze_min": ("down", 10),
                 "steam_break_min": ("down", 30)}
        for key, (way, cur) in rules.items():
            worse = cur - 5 if way == "up" else cur + 5
            better = cur + 5 if way == "up" else cur - 5
            self.fill(**{key: worse})
            self.app.save_settings()
            self.assertIn("Locked", self.msg(), key)
            self.assertEqual(self.st[key], cur, key)
            self.assertEqual(self.app.set_entries[key].get(), str(cur), key)   # field restored
            self.fill(**{key: better})
            self.app.save_settings()
            self.assertEqual(self.st[key], better, key)
            self.assertEqual(self.msg(), "Saved.", key)

    def test_unchanged_values_save_fine(self):
        self.app.save_settings()
        self.assertEqual(self.msg(), "Saved.")

    def test_daily_cap_zero_means_no_cap_which_is_strictest(self):
        self.fill(daily_study_cap_min=0)
        self.app.save_settings()
        self.assertEqual(self.st["daily_study_cap_min"], 0)
        self.fill(daily_study_cap_min=100)                # putting a cap back would loosen it
        self.app.save_settings()
        self.assertIn("Locked", self.msg())
        self.assertEqual(self.st["daily_study_cap_min"], 0)

    def test_loosens_table(self):
        L = self.app._loosens
        self.assertTrue(L("session_length_min", 45, 44))
        self.assertFalse(L("session_length_min", 45, 45))
        self.assertFalse(L("session_length_min", 45, 46))
        self.assertTrue(L("snooze_min", 10, 11))
        self.assertFalse(L("snooze_min", 10, 9))
        self.assertTrue(L("daily_study_cap_min", 240, 100))
        self.assertFalse(L("daily_study_cap_min", 240, 0))
        self.assertTrue(L("daily_study_cap_min", 0, 240))
        self.assertFalse(L("something_else", 5, 1))

    def test_bad_input_is_rejected_atomically(self):
        for bad in ("abc", "", "1e999", "-5", "99999", "nan", "1441"):
            before = dict(self.st)
            self.fill(session_length_min=bad, snooze_min=3)      # snooze 3 would be a valid change
            self.app.save_settings()
            self.assertIn("Bad value", self.msg(), bad)
            self.assertEqual(self.st["snooze_min"], before["snooze_min"], bad)   # nothing applied
            self.app._show_full()
            self.popups.clear()

    def test_sessions_shorter_than_twenty_minutes_are_refused(self):
        for short in ("19", "5", "1", "0"):
            before = dict(self.st)
            self.fill(session_length_min=short, snooze_min=3)
            self.app.save_settings()
            self.assertIn("at least 20 minutes", self.msg(), short)
            self.assertEqual(self.st["session_length_min"], before["session_length_min"], short)
            self.assertEqual(self.st["snooze_min"], before["snooze_min"], short)    # nothing else applied either
            self.assertEqual(self.app.set_entries["session_length_min"].get(), str(before["session_length_min"]))
            self.app._show_full()

    def test_the_settings_label_says_twenty(self):
        self.app._show_full()
        labels = []

        def walk(w):
            for c in w.winfo_children():
                try:
                    labels.append(c.cget("text"))
                except Exception:
                    pass
                walk(c)
        walk(self.app.tab_set)
        self.assertTrue(any("20 or more" in str(t) for t in labels), labels)

    def test_lengthening_a_session_is_still_allowed(self):
        self.fill(session_length_min=60)
        self.app.save_settings()
        self.assertEqual(self.st["session_length_min"], 60)
        self.assertEqual(core.load_state()["session_length_min"], 60)

    def test_upper_bound_is_inclusive(self):
        self.fill(session_length_min=1440)
        self.app.save_settings()
        self.assertEqual(self.st["session_length_min"], 1440)

    def test_decimal_input_is_truncated(self):
        self.fill(snooze_min="7.9")
        self.app.save_settings()
        self.assertEqual(self.st["snooze_min"], 7)

    def test_save_never_touches_the_schedule_or_blocklist(self):
        before = (self.st["schedule_start"], self.st["schedule_end"], list(self.st["blocklist"]))
        self.app.save_settings()
        self.assertEqual((self.st["schedule_start"], self.st["schedule_end"], self.st["blocklist"]), before)

    def test_save_asks_for_a_hosts_refresh_only_while_blocking(self):
        self.enforced.clear()
        self.app.save_settings()
        self.assertEqual(self.enforced, [True])
        self.set_time(NIGHT)
        self.enforced.clear()
        self.app.save_settings()
        self.assertEqual(self.enforced, [False])


@both
class Schedule(AppCase):
    def test_tab_is_read_only_and_shows_the_hours(self):
        self.app._show_full()
        self.assertEqual(self.text_of(self.app.s_hours), "07:00  →  00:00")
        self.assertEqual(self.text_of(self.app.s_hours_weekend), "10:00  →  18:00")
        self.assertIn("23:59", self.text_of(self.app.s_clock))
        for name in ("save_schedule", "s_start", "s_end", "s_clockout"):
            self.assertFalse(hasattr(self.app, name), name)

    def test_blank_clockout_text(self):
        self.st["clockout_time"] = ""
        self.app._render_schedule()
        self.assertIn("off", self.text_of(self.app.s_clock))

    def test_weekend_hours_are_read_only_too(self):
        before = dict(self.st)
        self.app._show_full()
        self.assertEqual(self.st["weekend_schedule_start"], before["weekend_schedule_start"])
        self.assertEqual(self.st["weekend_schedule_end"], before["weekend_schedule_end"])

    def test_off_hours_message_reflects_the_weekend_window(self):
        self.set_time(SAT_EARLY)                          # 08:00 Saturday: before the 10:00 start
        self.assertIn("10:00", self.app._status()[1])


@both
class Blocklist(AppCase):
    def setUp(self):
        super().setUp()
        self.app._show_full()

    def shown(self):
        return self.app.set_block.get("1.0", "end").split()

    def add(self, text):
        self.app._set_entry(self.app.add_site, text)
        self.app.add_blocked_site()

    def msg(self):
        return self.text_of(self.app.set_msg)

    def test_shows_the_whole_list(self):
        self.assertEqual(self.shown(), self.st["blocklist"])

    def test_is_read_only(self):
        before = self.shown()
        self.app.set_block.insert("1.0", "hacked.com\n")
        self.app.set_block.delete("1.0", "end")
        self.assertEqual(self.shown(), before)

    def test_add_cleans_persists_and_shows(self):
        self.add("https://www.Example-Site.org/x?y=1")
        self.assertEqual(self.st["blocklist"][-1], "example-site.org")
        self.assertIn("example-site.org", self.shown())
        self.assertIn("example-site.org", core.load_state()["blocklist"])
        self.assertEqual(self.msg(), "Added example-site.org.")
        self.assertEqual(self.app.add_site.get(), "")

    def test_add_while_blocking_updates_the_hosts_file_pass(self):
        self.enforced.clear()
        self.add("newsite.io")
        self.assertEqual(self.enforced, [True])

    def test_add_while_free_does_not_force_a_refresh(self):
        self.set_time(NIGHT)
        self.enforced.clear()
        self.add("newsite.io")
        self.assertEqual(self.enforced, [])

    def test_duplicate_is_not_added(self):
        n = len(self.st["blocklist"])
        self.add("YouTube.com")
        self.add("https://www.youtube.com/watch?v=1")
        self.assertEqual(len(self.st["blocklist"]), n)
        self.assertIn("already blocked", self.msg())

    def test_junk_is_rejected(self):
        n = len(self.st["blocklist"])
        for junk in ("", "not a site", "localhost", "192.168.1.1", "a@b.com"):
            self.add(junk)
            self.assertIn("doesn't look like a site", self.msg(), junk)
        self.assertEqual(len(self.st["blocklist"]), n)

    def test_the_list_only_grows(self):
        n = len(self.st["blocklist"])
        self.add("one.com"); self.add("two.com")
        self.assertEqual(len(self.st["blocklist"]), n + 2)
        self.app.save_settings()
        self.assertEqual(len(self.st["blocklist"]), n + 2)


@both
class Reminders(AppCase):
    def setUp(self):
        super().setUp()
        self.app._show_full()
        self.popups.clear()

    def test_lines_strip_bullets_and_blanks(self):
        self.st["reminders"] = "- one\n\n  • two  \n* three\nfour\n   \n"
        self.assertEqual(self.app._reminder_lines(), ["one", "two", "three", "four"])

    def test_empty_notepad(self):
        self.st["reminders"] = ""
        self.assertEqual(self.app._reminder_lines(), [])

    def test_save_persists_everything_and_updates_the_nagger(self):
        self.app.rem_text.delete("1.0", "end")
        self.app.rem_text.insert("1.0", "- study\n- breathe")
        self.app._set_entry(self.app.rem_interval, "15")
        self.app.voice_var.set("Voice B")
        self.app.nag_own_var.set(0)
        self.app.save_reminders()
        got = core.load_state()
        self.assertEqual((got["reminders"], got["reminder_interval_min"], got["reminder_voice"],
                          got["nag_own_words"]), ("- study\n- breathe", 15, "Voice B", False))
        n = self.app.notifier
        self.assertEqual((n.own_lines, n.voice, n.nag_own), (["study", "breathe"], "Voice B", False))
        self.assertEqual(self.text_of(self.app.rem_msg), "Saved.")

    def test_default_voice_is_stored_as_empty(self):
        self.app.voice_var.set("(default)")
        self.app.save_reminders()
        self.assertEqual(self.st["reminder_voice"], "")
        self.assertIsNone(self.app._chosen_voice())

    def test_interval_is_clamped_and_validated(self):
        self.app._set_entry(self.app.rem_interval, "-5")
        self.app.save_reminders()
        self.assertEqual(self.st["reminder_interval_min"], 0)
        self.app._set_entry(self.app.rem_interval, "999999")
        self.app.save_reminders()
        self.assertEqual(self.st["reminder_interval_min"], fa.FocusApp.SETTING_MAX)
        self.app._set_entry(self.app.rem_interval, "")
        self.app.save_reminders()
        self.assertEqual(self.st["reminder_interval_min"], 0)
        self.app._set_entry(self.app.rem_interval, "abc")
        self.app.save_reminders()
        self.assertIn("Bad value", self.text_of(self.app.rem_msg))

    def test_read_all_joins_with_pauses_and_uses_the_chosen_voice(self):
        self.st["reminders"] = "one\ntwo"
        self.app.rem_text.delete("1.0", "end"); self.app.rem_text.insert("1.0", "one\ntwo")
        self.app.voice_var.set("Voice A")
        self.app.read_reminders("all")
        self.assertEqual(self.said[-1], ("one. two", "Voice A"))

    def test_read_one_picks_a_single_line(self):
        self.app.rem_text.delete("1.0", "end"); self.app.rem_text.insert("1.0", "one\ntwo\nthree")
        for _ in range(10):
            self.app.read_reminders("one")
            self.assertIn(self.said[-1][0], ("one", "two", "three"))

    def test_read_with_nothing_written(self):
        self.app.rem_text.delete("1.0", "end")
        self.app.read_reminders("all")
        self.assertEqual(self.said, [])
        self.assertIn("Nothing to read", self.text_of(self.app.rem_msg))

    def test_test_voice_speaks(self):
        self.app.voice_var.set("Voice A")
        self.app.test_voice()
        self.assertEqual(self.said[-1][1], "Voice A")


@both
class Recordings(AppCase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp()
        p = mock.patch.object(fa, "SOUNDS_DIR", self.dir)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.app._show_full()

    def msg(self):
        return self.text_of(self.app.rem_msg)

    def test_record_then_save(self):
        with mock.patch.object(fa, "record_start", return_value=True), \
                mock.patch.object(fa, "record_stop_save", side_effect=lambda p: open(p, "wb").close() or True):
            self.app.toggle_record()
            self.assertTrue(self.app._recording)
            self.assertIn("Recording", self.msg())
            self.app.toggle_record()
        self.assertFalse(self.app._recording)
        files = os.listdir(self.dir)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].startswith("rec_") and files[0].endswith(".wav"))
        self.assertIn("Saved", self.msg())

    def test_no_microphone(self):
        with mock.patch.object(fa, "record_start", return_value=False):
            self.app.toggle_record()
        self.assertFalse(self.app._recording)
        self.assertIn("microphone", self.msg())

    def test_failed_save_is_reported(self):
        with mock.patch.object(fa, "record_start", return_value=True), \
                mock.patch.object(fa, "record_stop_save", return_value=False):
            self.app.toggle_record(); self.app.toggle_record()
        self.assertIn("Save failed", self.msg())
        self.assertFalse(self.app._recording)

    def test_test_recordings(self):
        self.app.test_recordings()
        self.assertIn("No recordings", self.msg())
        open(os.path.join(self.dir, "a.wav"), "wb").close()
        with mock.patch.object(fa, "play_custom_overlap") as play:
            self.app.test_recordings()
            play.assert_called_once_with(1)
        self.assertIn("1 saved", self.msg())

    def test_clear_deletes_only_wavs(self):
        for n in ("a.wav", "b.wav", "keep.txt"):
            open(os.path.join(self.dir, n), "wb").close()
        self.app.clear_recordings()
        self.assertEqual(os.listdir(self.dir), ["keep.txt"])
        self.assertIn("Deleted 2", self.msg())


if __name__ == "__main__":
    unittest.main()
