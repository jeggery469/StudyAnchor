"""The learning break in the app: starting it, every refusal, the YouTube-tab rule with its grace
period, the approved-video list, and the screens. Runs on customtkinter and on plain tkinter."""
import unittest
from unittest import mock

from appsupport import AppCase
from support import MORNING, EVENING, NIGHT, SAT_MORNING, ts
import core
import focusapp as fa

DELAY = core.LEARNING_APPROVAL_DELAY_MIN * 60
GRACE = core.LEARNING_GRACE_SEC
CHROME = "chrome.exe"


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


def button_text(widget):
    if not hasattr(widget, "invoke"):
        return None
    try:
        return widget.cget("text")
    except Exception:
        return None


def label_texts(widget):
    out = []
    for w in walk(widget):
        if hasattr(w, "invoke"):
            continue
        try:
            t = w.cget("text")
        except Exception:
            continue
        if t:
            out.append(t)
    return out


class LearningCase(AppCase):
    def approve(self, *phrases, ready=True):
        """Put approvals straight into the state (ready=False: still inside the waiting period)."""
        added = MORNING - DELAY - 10 if ready else MORNING - 10
        self.st["learning_approved"] = [{"phrase": p, "added": added} for p in phrases]

    def start(self, *phrases):
        self.approve(*(phrases or ("cs50 lecture",)))
        self.app.learning_break()
        self.popups.clear()
        self.enforced.clear()


@both
class StartingALearningBreak(LearningCase):
    def test_starts_for_the_configured_time_and_uses_one(self):
        self.approve("cs50 lecture")
        self.app.learning_break()
        self.assertEqual(self.st["learning_until"], MORNING + core.LEARNING_BREAK_MIN * 60)
        self.assertEqual(self.st["learning_used"], 1)
        self.assertEqual(self.enforced, [False])                         # hosts file updated right away
        self.assertEqual(self.popup_titles(), ["📚 Learning break"])
        self.assertIn("1 left today", self.popups[0][1])
        self.assertTrue(core.learning_active(self.st, MORNING + 1))

    def test_it_is_persisted(self):
        self.approve("cs50 lecture")
        self.app.learning_break()
        got = core.load_state()
        self.assertEqual((got["learning_until"], got["learning_used"]),
                         (MORNING + core.LEARNING_BREAK_MIN * 60, 1))

    def test_youtube_is_what_it_opens_and_nothing_else(self):
        self.approve("cs50 lecture")
        self.app.learning_break()
        eff = core.effective_blocklist(self.st, MORNING + 1)
        self.assertNotIn("youtube.com", eff)
        self.assertIn("instagram.com", eff)
        self.assertEqual(self.st["unlock_until"], 0)                     # not a general break
        self.assertEqual(self.st["steam_break_until"], 0)

    def test_the_daily_limit(self):
        self.approve("cs50 lecture")
        for n in range(core.LEARNING_BREAKS_PER_DAY):
            self.popups.clear()
            self.app.learning_break()
            self.assertEqual(self.popup_titles(), ["📚 Learning break"], n)
            self.fake.advance(core.LEARNING_BREAK_MIN * 60 + 1)
        self.popups.clear()
        before = dict(self.st)
        self.app.learning_break()
        self.assertEqual(self.popup_titles(), ["No learning breaks left today"])
        self.assertEqual(self.st["learning_until"], before["learning_until"])
        self.assertEqual(self.st["learning_used"], core.LEARNING_BREAKS_PER_DAY)

    def test_they_come_back_the_next_day(self):
        self.approve("cs50 lecture")
        self.st["learning_used"] = core.LEARNING_BREAKS_PER_DAY
        self.st["cheat_day"] = "1999-01-01"
        self.app.learning_break()
        self.assertEqual(self.popup_titles(), ["📚 Learning break"])
        self.assertEqual(self.st["learning_used"], 1)

    def test_the_reset_is_part_of_the_daily_reset(self):
        self.st.update(cheat_day="1999-01-01", learning_used=2)
        self.app._maybe_reset_cheat_day()
        self.assertEqual(self.st["learning_used"], 0)

    def test_works_on_weekends_too(self):
        self.set_time(SAT_MORNING)
        self.st["learning_approved"] = [{"phrase": "cs50 lecture", "added": SAT_MORNING - DELAY - 10}]
        self.app.learning_break()
        self.assertEqual(self.popup_titles(), ["📚 Learning break"])


@both
class RefusedLearningBreaks(LearningCase):
    def setUp(self):
        super().setUp()
        self.approve("cs50 lecture")

    def refused(self, title):
        self.assertEqual(self.popup_titles(), [title])
        self.assertEqual(self.st["learning_until"], 0)
        self.assertEqual(self.st["learning_used"], 0)
        self.assertEqual(self.enforced, [])

    def test_during_a_study_session(self):
        self.app.toggle_session()
        self.popups.clear(); self.enforced.clear()
        self.app.learning_break()
        self.refused("You're in a session")

    def test_during_nuclear_lockdown(self):
        self.st["nuclear_until"] = MORNING + 600
        self.app.learning_break()
        self.refused("☢ Nuclear lockdown")

    def test_when_everything_is_already_free(self):
        for t in (NIGHT, EVENING):
            self.popups.clear()
            self.set_time(t)
            self.app.learning_break()
            self.refused("YouTube already free")

    def test_during_an_ordinary_break(self):
        self.st["unlock_until"] = MORNING + 100
        self.app.learning_break()
        self.refused("Already on a break")

    def test_while_one_is_already_running(self):
        self.app.learning_break()
        used = self.st["learning_used"]
        self.popups.clear(); self.enforced.clear()
        self.fake.advance(60)
        self.app.learning_break()
        self.assertEqual(self.popup_titles(), ["Learning break running"])
        self.assertEqual(self.st["learning_used"], used)                 # no second one burned
        self.assertEqual(self.enforced, [])

    def test_with_nothing_approved(self):
        self.st["learning_approved"] = []
        self.app.learning_break()
        self.refused("Nothing approved yet")
        self.assertIn("Learning tab", self.popups[0][1])

    def test_with_only_approvals_that_are_still_waiting(self):
        self.approve("cs50 lecture", ready=False)
        self.app.learning_break()
        self.refused("Nothing approved yet")
        self.assertIn("waiting period", self.popups[0][1])

    def test_a_nuclear_lockdown_that_started_after_it_ends_it(self):
        self.app.learning_break()
        self.st["nuclear_until"] = MORNING + 600
        self.assertFalse(core.learning_active(self.st, MORNING + 5))
        self.assertIn("youtube.com", core.effective_blocklist(self.st, MORNING + 5))


@both
class EndingALearningBreak(LearningCase):
    def test_starting_a_study_session_ends_it(self):
        self.start()
        self.app.toggle_session()
        self.assertEqual(self.st["learning_until"], 0)
        self.assertIn("youtube.com", core.effective_blocklist(self.st, MORNING + 1))

    def test_lock_in_ends_it_and_does_not_refund_it(self):
        self.start()
        self.app.end_all_breaks()
        self.assertEqual(self.st["learning_until"], 0)
        self.assertEqual(self.st["learning_used"], 1)
        self.assertEqual(self.popup_titles(), ["🔒 Locked back in"])
        self.assertEqual(self.enforced, [False])

    def test_lock_in_with_nothing_running_still_says_so(self):
        self.app.end_all_breaks()
        self.assertEqual(self.popup_titles(), ["Already locked in"])

    def test_it_runs_out_by_itself_and_youtube_is_blocked_again(self):
        self.start()
        self.tick(core.LEARNING_BREAK_MIN * 60 - 1)
        self.assertTrue(core.learning_active(self.st, self.fake.now))
        self.enforced.clear()
        self.tick(2)
        self.assertFalse(core.learning_active(self.st, self.fake.now))
        self.assertIn(False, self.enforced)                              # re-block kicked off at once
        self.assertIn("youtube.com", core.effective_blocklist(self.st, self.fake.now))

    def test_the_end_gets_its_own_alert(self):
        self.start()
        seen = []
        real = self.app.notifier.update
        self.app.notifier.update = lambda level, head, sub, voice_lines=None: seen.append((level, head))
        try:
            self.tick(core.LEARNING_BREAK_MIN * 60 + 2)
        finally:
            self.app.notifier.update = real
        self.assertIn((3, "⏰ LEARNING OVER"), seen)

    def test_no_end_alert_if_you_started_a_session_instead(self):
        self.start()
        self.app.toggle_session()
        seen = []
        real = self.app.notifier.update
        self.app.notifier.update = lambda level, head, sub, voice_lines=None: seen.append(head)
        try:
            self.tick(core.LEARNING_BREAK_MIN * 60 + 5)
        finally:
            self.app.notifier.update = real
        self.assertFalse(any("OVER" in h for h in seen))


@both
class StatusAndNagging(LearningCase):
    def head(self):
        return self.app._status()

    def test_status_shows_a_countdown(self):
        self.start()
        head, sub, _ = self.head()
        self.assertEqual(head, f"📚 LEARNING {core.LEARNING_BREAK_MIN:02d}:00")
        self.assertEqual(sub, "approved videos only")
        self.fake.advance(65)
        self.assertEqual(self.head()[0], f"📚 LEARNING {core.LEARNING_BREAK_MIN - 2:02d}:55")

    def test_status_precedence(self):
        self.start()
        self.st["snooze_until"] = MORNING + 99999
        self.assertTrue(self.head()[0].startswith("📚 LEARNING"))            # beats snooze
        self.st["unlock_until"] = MORNING + 5000
        self.assertTrue(self.head()[0].startswith("☕ BREAK"))               # a general break is shown first
        self.st["unlock_until"] = 0
        self.st["nuclear_until"] = MORNING + 5000
        self.assertTrue(self.head()[0].startswith("☢ NUCLEAR"))
        self.st["nuclear_until"] = 0
        self.app.session_active = True
        self.app.session_remaining = 60
        self.assertTrue(self.head()[0].startswith("📚 STUDY"))

    def test_no_start_a_session_nagging_during_a_learning_break(self):
        self.start()
        seen = []
        real = self.app.notifier.update
        self.app.notifier.update = lambda level, head, sub, voice_lines=None: seen.append(head)
        try:
            self.tick(30)
        finally:
            self.app.notifier.update = real
        self.assertEqual(seen, [])

    def test_the_popout_shows_the_status(self):
        self.start()
        self.app.refresh_ui()
        self.assertTrue(self.text_of(self.app.m_status).startswith("📚 LEARNING"))


@both
class TheYouTubeTabRule(LearningCase):
    def setUp(self):
        super().setUp()
        self.start("cs50 lecture", "python tutorial")

    def watch(self, title, seconds, proc=CHROME):
        self.set_fg(proc, title)
        self.tick(seconds)

    def test_an_unapproved_video_is_closed_only_after_the_grace_period(self):
        self.watch("funny cat compilation #12 - youtube - google chrome", GRACE - 1)
        self.assertEqual(self.ctrl_w, [])
        self.tick(1)
        self.assertEqual(self.ctrl_w, [])                                  # exactly at the limit: first moment
        self.tick(1)
        self.assertEqual(len(self.ctrl_w), 1)
        self.assertIn(("beeps", 2, 600, 120), self.beeped)                 # a short warning sound

    def test_an_approved_video_is_never_closed(self):
        self.watch("CS50 Lecture 3 - Algorithms - YouTube - Google Chrome", 120)
        self.assertEqual(self.ctrl_w, [])

    def test_a_search_for_an_approved_topic_is_allowed(self):
        self.watch("python tutorial - youtube - google chrome", 60)
        self.assertEqual(self.ctrl_w, [])

    def test_the_youtube_home_page_and_recommendations_are_closed(self):
        self.watch("youtube - google chrome", GRACE + 3)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_other_sites_are_left_alone_by_this_rule(self):
        self.watch("wikipedia - the free encyclopedia - google chrome", 60)
        self.watch("my notes - google docs - google chrome", 60)
        self.watch("how to learn python - google search - google chrome", 60)   # no 'youtube' in the title
        self.assertEqual(self.ctrl_w, [])

    def test_only_browsers_are_touched(self):
        self.watch("youtube downloader.py - visual studio code", 60, proc="code.exe")
        self.assertEqual(self.ctrl_w, [])

    def test_a_page_that_is_still_loading_gets_its_chance(self):
        """A freshly opened tab shows a placeholder title for a moment before the real one loads."""
        self.watch("www.youtube.com/watch?v=abc123 - google chrome", 4)
        self.assertEqual(self.ctrl_w, [])
        self.watch("CS50 Lecture 3 - YouTube - Google Chrome", 60)           # the real title arrives
        self.assertEqual(self.ctrl_w, [])

    def test_looking_at_an_approved_tab_resets_the_clock(self):
        self.watch("funny cats - youtube - google chrome", GRACE - 2)
        self.watch("cs50 lecture 1 - youtube - google chrome", 1)            # back to something approved
        self.watch("funny cats - youtube - google chrome", GRACE - 2)         # the clock starts over
        self.assertEqual(self.ctrl_w, [])

    def test_leaving_the_browser_resets_the_clock_too(self):
        self.watch("funny cats - youtube - google chrome", GRACE - 2)
        self.watch("notes.txt - notepad", 1, proc="notepad.exe")
        self.watch("funny cats - youtube - google chrome", GRACE - 2)
        self.assertEqual(self.ctrl_w, [])

    def test_after_closing_a_tab_the_next_bad_tab_gets_a_fresh_grace_period(self):
        self.watch("funny cats - youtube - google chrome", GRACE + 2)
        self.assertEqual(len(self.ctrl_w), 1)
        self.watch("cat fails shorts - youtube - google chrome", GRACE - 2)
        self.assertEqual(len(self.ctrl_w), 1)                                # not closed again immediately
        self.tick(5)
        self.assertEqual(len(self.ctrl_w), 2)

    def test_autoplay_into_an_unapproved_video_gets_closed(self):
        self.watch("cs50 lecture 4 - youtube - google chrome", 30)
        self.watch("top 10 fails 2026 - youtube - google chrome", GRACE + 3)   # autoplay moved on
        self.assertEqual(len(self.ctrl_w), 1)

    def test_a_pending_approval_does_not_protect_a_video_yet(self):
        self.approve("cs50 lecture", ready=False)
        self.st["learning_approved"].append({"phrase": "python tutorial", "added": MORNING - DELAY - 10})
        self.watch("cs50 lecture 3 - youtube - google chrome", GRACE + 3)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_removing_an_approval_takes_effect_immediately(self):
        self.watch("cs50 lecture 3 - youtube - google chrome", 30)
        self.assertEqual(self.ctrl_w, [])
        self.app._show_full()
        self.app.remove_approval("cs50 lecture")
        self.watch("cs50 lecture 3 - youtube - google chrome", GRACE + 3)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_nothing_happens_once_the_break_is_over(self):
        self.st["learning_until"] = 0
        self.watch("funny cats - youtube - google chrome", 1)
        self.assertEqual(self.app._lt_bad_since, None)

    def test_the_rule_does_not_apply_outside_a_learning_break(self):
        self.st["learning_until"] = 0
        self.app._lt_bad_since = None
        self.fake.advance(1)
        self.app._learning_enforce(self.fake.now, CHROME, "funny cats - youtube - google chrome")
        self.assertIsNone(self.app._lt_bad_since)


@both
class OtherBlockedSitesDuringLearning(LearningCase):
    def setUp(self):
        super().setUp()
        self.start("cs50 lecture")

    def test_other_blocked_sites_are_still_closed_immediately(self):
        for title in ("(2) instagram - google chrome", "reddit - front page - google chrome",
                      "naruto | fandom - google chrome", "netflix - google chrome"):
            self.ctrl_w.clear()
            self.app._last_tabclose = 0
            self.set_fg(CHROME, title)
            self.tick(1)
            self.assertEqual(len(self.ctrl_w), 1, title)

    def test_the_generic_closer_does_not_fight_the_learning_rule_over_youtube(self):
        self.set_fg(CHROME, "cs50 lecture 3 - youtube - google chrome")
        self.tick(20)
        self.assertEqual(self.ctrl_w, [])

    def test_after_the_break_youtube_is_closed_immediately_again(self):
        self.tick(core.LEARNING_BREAK_MIN * 60 + 2)
        self.ctrl_w.clear()
        self.app._last_tabclose = 0
        self.set_fg(CHROME, "cs50 lecture 3 - youtube - google chrome")
        self.tick(1)
        self.assertEqual(len(self.ctrl_w), 1)                               # no grace, no approvals: just blocked

    def test_nuclear_closes_youtube_even_mid_learning_break(self):
        self.st["nuclear_until"] = self.fake.now + 600
        self.set_fg(CHROME, "cs50 lecture 3 - youtube - google chrome")
        self.tick(1)
        self.assertEqual(len(self.ctrl_w), 1)


@both
class ApprovedVideoList(LearningCase):
    def setUp(self):
        super().setUp()
        self.app._show_full()
        self.popups.clear()

    def add(self, text):
        self.app._set_entry(self.app.l_entry, text)
        self.app.add_approval()

    def msg(self):
        return self.text_of(self.app.l_msg)

    def rows(self):
        # a customtkinter label wraps an inner tk label, so each text appears twice
        return list(dict.fromkeys(label_texts(self.app.l_list)))

    def test_adding_stores_the_cleaned_phrase_and_the_time(self):
        self.add("  CS50   Lecture 3 ")
        self.assertEqual(self.st["learning_approved"], [{"phrase": "cs50 lecture 3", "added": MORNING}])
        self.assertEqual(core.load_state()["learning_approved"], self.st["learning_approved"])
        self.assertEqual(self.app.l_entry.get(), "")
        self.assertIn("starts counting", self.msg())
        self.assertIn(f"{core.LEARNING_APPROVAL_DELAY_MIN} min", self.msg())

    def test_a_new_approval_shows_its_countdown(self):
        self.add("cs50 lecture")
        self.assertIn("cs50 lecture", self.rows())
        self.assertIn(f"active in {core.LEARNING_APPROVAL_DELAY_MIN}:00", self.rows())

    def test_the_countdown_runs_down_and_then_says_active(self):
        self.add("cs50 lecture")
        self.fake.advance(DELAY - 60)
        self.app._render_learning()
        self.assertIn("active in 01:00", self.rows())
        self.fake.advance(60)
        self.app._render_learning()
        self.assertIn("✓ active", self.rows())

    def test_it_really_does_not_count_until_the_delay_is_over(self):
        self.add("cs50 lecture")
        self.assertFalse(core.title_approved(self.st, "cs50 lecture 3 - youtube", self.fake.now))
        self.fake.advance(DELAY)
        self.assertTrue(core.title_approved(self.st, "cs50 lecture 3 - youtube", self.fake.now))

    def test_too_short_or_generic_phrases_are_rejected(self):
        for bad in ("", "  ", "ab", "yt", "youtube", "YouTube", "chrome", "1234"):
            self.add(bad)
            self.assertIn("at least", self.msg(), bad)
        self.assertEqual(self.st["learning_approved"], [])

    def test_duplicates_are_not_added_and_do_not_restart_the_wait(self):
        self.add("cs50 lecture")
        first = self.st["learning_approved"][0]["added"]
        self.fake.advance(600)
        self.add("CS50   Lecture")
        self.assertEqual(len(self.st["learning_approved"]), 1)
        self.assertEqual(self.st["learning_approved"][0]["added"], first)
        self.assertIn("already on the list", self.msg())

    def test_enter_key_adds(self):
        if self.CTK:
            self.app.tabs.set("Learning")                      # the entry must be on screen to get key presses
        else:
            self.app._nb.select(self.app.tab_learn)
        self.app.root.update()
        self.app._set_entry(self.app.l_entry, "python tutorial")
        inner = getattr(self.app.l_entry, "_entry", self.app.l_entry)
        inner.focus_force()
        self.app.root.update()
        inner.event_generate("<Return>", when="now")
        self.app.root.update()
        self.assertEqual([e["phrase"] for e in self.st["learning_approved"]], ["python tutorial"])

    def test_removing_is_instant_and_persisted(self):
        self.add("cs50 lecture")
        self.add("python tutorial")
        self.app.remove_approval("cs50 lecture")
        self.assertEqual([e["phrase"] for e in self.st["learning_approved"]], ["python tutorial"])
        self.assertEqual([e["phrase"] for e in core.load_state()["learning_approved"]], ["python tutorial"])
        self.assertNotIn("cs50 lecture", self.rows())
        self.assertIn("Removed", self.msg())

    def test_the_x_button_removes_a_row(self):
        self.add("cs50 lecture")
        x = [b for b in walk(self.app.l_list) if button_text(b) == "✕"]
        self.assertEqual(len(x), 1)
        x[0].invoke()
        self.assertEqual(self.st["learning_approved"], [])
        self.assertIn("Nothing approved yet.", self.rows())

    def test_rows_are_listed_oldest_first(self):
        self.add("first one")
        self.fake.advance(10)
        self.add("second one")
        self.fake.advance(10)
        self.add("third one")
        phrases = [t for t in self.rows() if t.endswith(" one")]
        self.assertEqual(phrases, ["first one", "second one", "third one"])

    def test_an_empty_list_says_so(self):
        self.app._render_learning()
        self.assertIn("Nothing approved yet.", self.rows())

    def test_very_long_phrases_do_not_break_the_row(self):
        self.add("x" * 200 + " tutorial")
        self.assertEqual(len(self.st["learning_approved"]), 1)
        self.app._render_learning()

    def test_the_status_line_tracks_breaks_left_and_the_running_countdown(self):
        status = lambda: self.text_of(self.app.l_status)
        self.app._render_learning()
        self.assertEqual(status(), f"{core.LEARNING_BREAKS_PER_DAY} learning breaks left today "
                                   f"({core.LEARNING_BREAK_MIN} min each)")
        self.st["learning_used"] = core.LEARNING_BREAKS_PER_DAY - 1
        self.app._render_learning()
        self.assertIn("1 learning break left today", status())
        self.st["learning_used"] = core.LEARNING_BREAKS_PER_DAY
        self.app._render_learning()
        self.assertIn("0 learning breaks left", status())
        self.st["learning_until"] = self.fake.now + 125
        self.app._render_learning()
        self.assertEqual(status(), "📚 Learning break running — 02:05 left")

    def test_rendering_survives_a_destroyed_window(self):
        with mock.patch.object(self.app.l_list, "winfo_children", side_effect=fa.tk.TclError):
            self.app._render_learning()


@both
class LearningScreens(LearningCase):
    def test_there_is_a_learning_tab(self):
        if self.CTK:
            self.assertIn("Learning", self.app.tabs._name_list)
        self.assertTrue(self.app.tab_learn.winfo_exists())

    def test_the_tab_explains_the_rules_with_the_real_numbers(self):
        self.app._show_full()
        text = " ".join(label_texts(self.app.tab_learn))
        self.assertIn(f"{core.LEARNING_BREAK_MIN} min", text)
        self.assertIn(f"{core.LEARNING_GRACE_SEC} seconds", text)
        self.assertIn(f"{core.LEARNING_APPROVAL_DELAY_MIN} minutes", text)
        self.assertIn("TITLE", text)

    def test_switching_to_the_tab_renders_it(self):
        self.app._show_full()
        self.st["learning_approved"] = [{"phrase": "fresh phrase", "added": MORNING - DELAY - 5}]
        self.app._on_tab_changed("Learning")
        self.assertIn("fresh phrase", label_texts(self.app.l_list))

    def test_the_start_button_on_the_tab(self):
        self.app._show_full()
        self.approve("cs50 lecture")
        start = [b for b in walk(self.app.tab_learn) if button_text(b) == "📚 Start learning break"]
        self.assertEqual(len(start), 1)
        start[0].invoke()
        self.assertTrue(core.learning_active(self.st, self.fake.now))

    def test_the_popout_and_dashboard_have_a_learn_button(self):
        self.app._show_full()
        for root in (self.app.popout, self.app.tab_dash):
            found = [b for b in walk(root) if button_text(b) == "📚 Learn"]
            self.assertEqual(len(found), 1, root)
        self.approve("cs50 lecture")
        [b for b in walk(self.app.popout) if button_text(b) == "📚 Learn"][0].invoke()
        self.assertTrue(core.learning_active(self.st, self.fake.now))

    def test_the_learn_button_explains_itself_when_nothing_is_approved(self):
        [b for b in walk(self.app.popout) if button_text(b) == "📚 Learn"][0].invoke()
        self.assertEqual(self.popup_titles(), ["Nothing approved yet"])

    def test_current_tab_reports_the_selected_tab(self):
        self.app._show_full()
        if self.CTK:
            self.app.tabs.set("Learning")
            self.assertEqual(self.app._current_tab(), "Learning")
        else:
            self.app._nb.select(self.app.tab_learn)
            self.assertEqual(self.app._current_tab(), "Learning")

    @unittest.skipUnless(fa.core.IS_WIN, "measures real window widths")
    def test_all_tab_buttons_fit_in_the_window(self):
        if not self.CTK:
            self.skipTest("only the customtkinter tab bar is a fixed-width strip")
        self.app._show_full()
        self.app.root.update()
        bar = self.app.tabs._segmented_button
        self.assertLessEqual(bar.winfo_reqwidth(), self.app.root.winfo_width(),
                             f"tab bar {bar.winfo_reqwidth()}px wider than the window {self.app.root.winfo_width()}px")

    def test_the_settings_save_button_is_reachable(self):
        """Settings is taller than the tab, so it scrolls: the important buttons must live inside the
        scroll area. (Where they land on screen once scrolled is measured in test_tabs.py.)"""
        self.app._show_full()
        sc = self.app._set_scroll
        for text in ("Save settings", "🔔 Test notification", "＋ Add site"):
            found = [b for b in walk(sc) if button_text(b) == text]
            self.assertEqual(len(found), 1, text)

    def test_wrapped_paragraphs_fit_the_window_width(self):
        self.app._show_full()
        self.app.root.update()
        for w in walk(self.app.tab_learn):
            try:
                if w.cget("wraplength"):
                    self.assertLessEqual(int(w.cget("wraplength")), self.app.root.winfo_width())
            except Exception:
                continue


if __name__ == "__main__":
    unittest.main()
