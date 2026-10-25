"""core: learning break rules, approved-video list, and the diagnostics log."""
import json
import os
import unittest
from unittest import mock

from support import IsolatedCore, MORNING, EVENING, NIGHT, SAT_MORNING
import core


def approval(phrase, added):
    return {"phrase": phrase, "added": added}


READY = MORNING - core.LEARNING_APPROVAL_DELAY_MIN * 60 - 1     # old enough to count at MORNING


class NormalizePhrase(unittest.TestCase):
    def test_cleans_case_and_whitespace(self):
        self.assertEqual(core.normalize_phrase("  CS50   Lecture\t3 "), "cs50 lecture 3")

    def test_accepts_normal_phrases(self):
        for p in ("python", "cs50", "Python for Beginners", "3blue1brown", "SICP"):
            self.assertIsNotNone(core.normalize_phrase(p), p)

    def test_too_short_is_rejected(self):
        for p in ("", " ", "a", "ab", "abc", "a b c", "x  y"):
            self.assertIsNone(core.normalize_phrase(p), repr(p))

    def test_digits_only_is_rejected(self):
        self.assertIsNone(core.normalize_phrase("2026"))
        self.assertIsNone(core.normalize_phrase("12345"))

    def test_phrases_that_appear_in_every_browser_title_are_rejected(self):
        """Approving one of these would approve every tab, which defeats the whole feature."""
        for p in ("youtube", "YouTube", "chrome", "google chrome", "microsoft edge", "firefox",
                  "mozilla firefox", "profile 1", "audio playing", "more pages", "new tab",
                  "google", "microsoft", "youtube - google chrome"):
            self.assertIsNone(core.normalize_phrase(p), p)

    def test_a_phrase_that_merely_contains_a_generic_word_is_fine(self):
        self.assertEqual(core.normalize_phrase("google cloud tutorial"), "google cloud tutorial")
        self.assertEqual(core.normalize_phrase("youtube algorithm explained"), "youtube algorithm explained")

    def test_non_strings_are_rejected(self):
        for bad in (None, 5, ["python"], {"a": 1}):
            self.assertIsNone(core.normalize_phrase(bad), repr(bad))


class CleanApprovals(unittest.TestCase):
    def test_keeps_good_entries_and_normalises(self):
        out = core.clean_approvals([approval("CS50  Lecture", 100), approval("python", 200)])
        self.assertEqual(out, [{"phrase": "cs50 lecture", "added": 100.0}, {"phrase": "python", "added": 200.0}])

    def test_drops_malformed_entries(self):
        raw = [None, "text", 5, {}, {"phrase": "python"}, {"added": 5}, {"phrase": 7, "added": 5},
               {"phrase": "python", "added": "yesterday"}, {"phrase": "python", "added": True},
               {"phrase": "python", "added": float("nan")}, {"phrase": "ab", "added": 5},
               approval("youtube", 5), approval("good phrase", 5)]
        self.assertEqual(core.clean_approvals(raw), [{"phrase": "good phrase", "added": 5.0}])

    def test_non_lists_give_nothing(self):
        for bad in (None, "x", 5, {"a": 1}):
            self.assertEqual(core.clean_approvals(bad), [])

    def test_duplicates_keep_the_earliest_so_re_adding_cannot_restart_the_wait(self):
        out = core.clean_approvals([approval("python", 500), approval("PYTHON", 100), approval("python", 900)])
        self.assertEqual(out, [{"phrase": "python", "added": 100.0}])


class ApprovedPhrases(unittest.TestCase):
    def st(self, *entries):
        s = core.default_state()
        s["learning_approved"] = list(entries)
        return s

    def test_a_new_approval_does_not_count_yet(self):
        st = self.st(approval("python", MORNING - 60))
        self.assertEqual(core.approved_phrases(st, MORNING), [])

    def test_counts_exactly_after_the_delay(self):
        added = MORNING
        st = self.st(approval("python", added))
        wait = core.LEARNING_APPROVAL_DELAY_MIN * 60
        self.assertEqual(core.approved_phrases(st, added + wait - 1), [])
        self.assertEqual(core.approved_phrases(st, added + wait), ["python"])

    def test_only_ready_ones_are_returned(self):
        st = self.st(approval("old one", READY), approval("fresh one", MORNING - 10))
        self.assertEqual(core.approved_phrases(st, MORNING), ["old one"])

    def test_approval_ready_at(self):
        self.assertEqual(core.approval_ready_at(approval("python", 1000)),
                         1000 + core.LEARNING_APPROVAL_DELAY_MIN * 60)

    def test_missing_key_is_empty(self):
        self.assertEqual(core.approved_phrases({}, MORNING), [])


class TitleApproved(unittest.TestCase):
    def setUp(self):
        self.st = core.default_state()
        self.st["learning_approved"] = [approval("cs50 lecture", READY), approval("python tutorial", READY),
                                        approval("pending thing", MORNING - 5)]

    def test_matches_a_phrase_anywhere_in_the_title_case_insensitively(self):
        for t in ("CS50 Lecture 3 - YouTube - Google Chrome", "learn python tutorial fast - youtube",
                  "my cs50 lecture notes - youtube"):
            self.assertTrue(core.title_approved(self.st, t, MORNING), t)

    def test_other_titles_do_not_match(self):
        for t in ("minecraft hardcore - youtube", "youtube", "python memes - youtube", ""):
            self.assertFalse(core.title_approved(self.st, t, MORNING), t)

    def test_a_pending_approval_does_not_match_yet(self):
        self.assertFalse(core.title_approved(self.st, "pending thing - youtube", MORNING))
        self.assertTrue(core.title_approved(self.st, "pending thing - youtube",
                                            MORNING + core.LEARNING_APPROVAL_DELAY_MIN * 60))

    def test_a_search_for_an_approved_topic_is_allowed(self):
        """'python tutorial - YouTube' is the title of the search results page."""
        self.assertTrue(core.title_approved(self.st, "python tutorial - youtube - google chrome", MORNING))

    def test_no_approvals_means_nothing_matches(self):
        self.assertFalse(core.title_approved(core.default_state(), "anything - youtube", MORNING))


class LearningActive(unittest.TestCase):
    def test_active_until_the_end_time(self):
        st = {"learning_until": MORNING + 60}
        self.assertTrue(core.learning_active(st, MORNING))
        self.assertTrue(core.learning_active(st, MORNING + 59))
        self.assertFalse(core.learning_active(st, MORNING + 60))
        self.assertFalse(core.learning_active({}, MORNING))

    def test_nuclear_overrides_it(self):
        st = {"learning_until": MORNING + 600, "nuclear_until": MORNING + 60}
        self.assertFalse(core.learning_active(st, MORNING))
        self.assertTrue(core.learning_active(st, MORNING + 61))      # lockdown over, break still has time

    def test_constants_are_sensible(self):
        self.assertGreaterEqual(core.LEARNING_BREAKS_PER_DAY, 1)
        self.assertGreater(core.LEARNING_BREAK_MIN, 0)
        self.assertGreater(core.LEARNING_APPROVAL_DELAY_MIN, 0)
        self.assertGreater(core.LEARNING_GRACE_SEC, 2)                # a page needs time to load its title
        self.assertEqual(sorted(core.LEARNING_UNBLOCKS), ["youtu.be", "youtube.com"])


class EffectiveBlocklist(unittest.TestCase):
    def test_full_list_when_not_learning(self):
        st = core.default_state()
        self.assertEqual(core.effective_blocklist(st, MORNING), st["blocklist"])

    def test_youtube_is_removed_while_learning_and_nothing_else(self):
        st = core.default_state()
        st["learning_until"] = MORNING + 600
        eff = core.effective_blocklist(st, MORNING)
        self.assertNotIn("youtube.com", eff)
        self.assertNotIn("youtu.be", eff)
        self.assertEqual(sorted(set(st["blocklist"]) - set(eff)), ["youtu.be", "youtube.com"])
        for keep in ("instagram.com", "reddit.com", "tiktok.com", "netflix.com", "twitch.tv"):
            self.assertIn(keep, eff)

    def test_subdomains_of_youtube_go_too_but_lookalikes_stay(self):
        st = core.default_state()
        st["blocklist"] = ["music.youtube.com", "notyoutube.com", "youtube.com.evil.org", "reddit.com"]
        st["learning_until"] = MORNING + 600
        self.assertEqual(core.effective_blocklist(st, MORNING), ["notyoutube.com", "youtube.com.evil.org", "reddit.com"])

    def test_a_nuclear_lockdown_puts_youtube_straight_back(self):
        st = core.default_state()
        st["learning_until"] = MORNING + 600
        st["nuclear_until"] = MORNING + 60
        self.assertIn("youtube.com", core.effective_blocklist(st, MORNING))

    def test_does_not_modify_the_state(self):
        st = core.default_state()
        st["learning_until"] = MORNING + 600
        before = list(st["blocklist"])
        core.effective_blocklist(st, MORNING)
        self.assertEqual(st["blocklist"], before)


class HostsDuringLearning(IsolatedCore):
    def test_enforcement_leaves_youtube_out_of_the_hosts_file_during_a_learning_break(self):
        st = self.state(learning_until=MORNING + 600)
        core.apply_enforcement(st, MORNING)
        text = self.hosts()
        self.assertIn(core.MARK_START, text)
        self.assertNotIn("youtube.com", text)
        self.assertNotIn("youtu.be", text)
        self.assertIn("0.0.0.0 instagram.com", text)          # everything else stays blocked
        self.assertIn("0.0.0.0 www.reddit.com", text)

    def test_youtube_is_blocked_again_when_the_break_ends(self):
        st = self.state(learning_until=MORNING + 600)
        core.apply_enforcement(st, MORNING)
        self.assertNotIn("youtube.com", self.hosts())
        core.apply_enforcement(st, MORNING + 601)
        self.assertIn("0.0.0.0 youtube.com", self.hosts())
        self.assertIn("0.0.0.0 www.youtube.com", self.hosts())
        self.assertIn("0.0.0.0 youtu.be", self.hosts())

    def test_the_block_is_rewritten_when_a_learning_break_starts(self):
        st = self.state()
        core.apply_enforcement(st, MORNING)
        self.assertIn("youtube.com", self.hosts())
        st["learning_until"] = MORNING + 600
        with mock.patch.object(core, "flush_dns") as flush:
            core.apply_enforcement(st, MORNING + 1)
            flush.assert_called_once()                         # DNS flushed so the change takes effect now
        self.assertNotIn("youtube.com", self.hosts())

    def test_unchanged_state_does_not_rewrite_the_file(self):
        st = self.state(learning_until=MORNING + 600)
        core.apply_enforcement(st, MORNING)
        with mock.patch.object(core, "_write_hosts") as w:
            core.apply_enforcement(st, MORNING + 5)
            w.assert_not_called()

    def test_a_learning_break_never_unblocks_anything_when_outside_hours_logic_says_free(self):
        st = self.state(learning_until=NIGHT + 600)
        core.apply_enforcement(st, NIGHT)
        self.assertNotIn(core.MARK_START, self.hosts())         # off-hours: nothing is blocked at all

    def test_nuclear_beats_a_learning_break_in_the_hosts_file(self):
        st = self.state(learning_until=MORNING + 600, nuclear_until=MORNING + 300)
        core.apply_enforcement(st, MORNING)
        self.assertIn("0.0.0.0 youtube.com", self.hosts())

    def test_refresh_hosts_block_honours_the_learning_break(self):
        st = self.state(learning_until=MORNING + 600)
        core.refresh_hosts_block(st, MORNING)                  # a fixed time: this must not depend on when the tests run
        self.assertNotIn("youtube.com", self.hosts())

    def test_set_hosts_block_takes_an_explicit_domain_list(self):
        core.set_hosts_block(self.state(), True, domains=["only.example.com"])
        self.assertIn("0.0.0.0 only.example.com", self.hosts())
        self.assertNotIn("youtube", self.hosts())
        core.set_hosts_block(self.state(), True, domains=[])          # empty list is a valid (empty) block
        self.assertNotIn("only.example.com", self.hosts())

    def test_weekend_learning_break_works_the_same(self):
        st = self.state(learning_until=SAT_MORNING + 600)
        core.apply_enforcement(st, SAT_MORNING)
        self.assertNotIn("youtube.com", self.hosts())
        self.assertIn("0.0.0.0 reddit.com", self.hosts())

    def test_steam_gating_is_untouched_by_a_learning_break(self):
        st = self.state(learning_until=MORNING + 600)
        self.assertTrue(core.steam_blocked(st, MORNING))
        self.assertTrue(core.sites_blocked(st, MORNING))                # sites are still "blocked" overall


class LoadStateApprovals(IsolatedCore):
    def write_state(self, obj):
        with open(core.STATE_PATH, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj))

    def test_defaults(self):
        st = core.default_state()
        self.assertEqual((st["learning_until"], st["learning_used"], st["learning_approved"]), (0.0, 0, []))
        self.assertEqual(core.load_state()["learning_approved"], [])

    def test_valid_approvals_survive_a_roundtrip(self):
        st = core.default_state()
        st["learning_approved"] = [approval("cs50 lecture", 123.0)]
        core.save_state(st)
        self.assertEqual(core.load_state()["learning_approved"], [{"phrase": "cs50 lecture", "added": 123.0}])

    def test_junk_in_the_file_is_cleaned_on_load(self):
        self.write_state({"learning_approved": ["x", {"phrase": "ok phrase", "added": 5},
                                                {"phrase": "youtube", "added": 5}, None]})
        self.assertEqual(core.load_state()["learning_approved"], [{"phrase": "ok phrase", "added": 5.0}])

    def test_wrong_types_fall_back(self):
        for bad in ("a string", 5, {"a": 1}, None):
            self.write_state({"learning_approved": bad, "learning_until": "soon", "learning_used": None})
            st = core.load_state()
            self.assertEqual(st["learning_approved"], [])
            self.assertEqual((st["learning_until"], st["learning_used"]), (0.0, 0))

    def test_hand_editing_the_added_time_is_still_just_data(self):
        """The state file is editable by an admin, like everything else here; what matters is that
        garbage can't crash anything."""
        self.write_state({"learning_approved": [{"phrase": "python", "added": -1e18}]})
        st = core.load_state()
        self.assertEqual(core.approved_phrases(st, MORNING), ["python"])


class LogEvent(IsolatedCore):
    def read(self):
        with open(core.log_path(), encoding="utf-8") as f:
            return f.read()

    def test_writes_timestamped_lines_to_the_data_dir(self):
        core.log_event("hello world")
        core.log_event("second line")
        lines = self.read().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d hello world$")
        self.assertTrue(core.log_path().startswith(self.tmp))

    def test_multiline_messages_are_kept_together(self):
        core.log_event("stack:\n  File x\n  File y")
        self.assertIn("  File y", self.read())

    def test_rotates_instead_of_growing_forever(self):
        with mock.patch.object(core, "LOG_MAX_BYTES", 200):
            for i in range(30):
                core.log_event(f"line number {i} " + "x" * 20)
        self.assertTrue(os.path.exists(core.log_path() + ".1"))
        total = os.path.getsize(core.log_path()) + os.path.getsize(core.log_path() + ".1")
        self.assertLess(total, 200 * 3)

    def test_never_raises(self):
        with mock.patch("builtins.open", side_effect=OSError("disk full")):
            core.log_event("anything")
        with mock.patch.object(core, "_ensure_dir", side_effect=RuntimeError):
            core.log_event("anything")
        core.log_event(None)
        core.log_event("unicode ✓ ☢ 🎯")

    def test_is_safe_from_many_threads(self):
        import threading
        ts = [threading.Thread(target=lambda i=i: [core.log_event(f"t{i} msg{j}") for j in range(20)])
              for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        lines = self.read().splitlines()
        self.assertEqual(len(lines), 160)
        self.assertTrue(all(" t" in ln and " msg" in ln for ln in lines))      # no torn lines


class ReleaseAppInstance(unittest.TestCase):
    def test_noop_when_nothing_is_held_or_off_windows(self):
        with mock.patch.object(core, "_app_mutex", None):
            core.release_app_instance()
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "_app_mutex", 123):
            core.release_app_instance()

    @unittest.skipUnless(core.IS_WIN, "named mutex")
    def test_releases_so_another_instance_can_claim_it(self):
        name, held = core.APP_MUTEX, core._app_mutex
        core.APP_MUTEX = f"Local\\FocusReleaseTest_{os.getpid()}"
        try:
            self.assertTrue(core.claim_app_instance())
            self.assertTrue(core.app_running())
            core.release_app_instance()
            self.assertIsNone(core._app_mutex)
            self.assertFalse(core.app_running())
            self.assertTrue(core.claim_app_instance())
            core.release_app_instance()
        finally:
            core.APP_MUTEX, core._app_mutex = name, held


if __name__ == "__main__":
    unittest.main()
