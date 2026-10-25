"""No-time-limit "audiobook" approvals, and all-words phrase matching."""
import unittest

from appsupport import AppCase
from support import IsolatedCore, MORNING, ts
import core
import focusapp as fa

DELAY = core.LEARNING_APPROVAL_DELAY_MIN * 60
GRACE = core.LEARNING_GRACE_SEC
READY = MORNING - DELAY - 10
CHROME = "chrome.exe"


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


def book(phrase="dune audiobook", added=READY, always=True):
    e = {"phrase": phrase, "added": added}
    if always:
        e["always"] = True
    return e


def state(*entries, **kw):
    st = core.default_state()
    st["learning_approved"] = list(entries)
    st.update(kw)
    return st


class PhraseMatching(unittest.TestCase):
    def test_every_word_must_appear_in_any_order(self):
        m = core.phrase_in_title
        self.assertTrue(m("dune audiobook", "Dune (Audiobook) - Frank Herbert - YouTube"))
        self.assertTrue(m("dune audiobook", "DUNE - Full Audiobook | Part 1"))
        self.assertTrue(m("dune audiobook", "Audiobook: Dune Messiah"))
        self.assertFalse(m("dune audiobook", "Dune Part Two Official Trailer"))
        self.assertFalse(m("dune audiobook", "Minecraft Audiobook"))
        self.assertFalse(m("dune audiobook", "YouTube"))

    def test_single_words_and_case(self):
        self.assertTrue(core.phrase_in_title("cs50", "CS50 Lecture 3"))
        self.assertTrue(core.phrase_in_title("CS50", "cs50 lecture 3"))
        self.assertFalse(core.phrase_in_title("cs50", "cs60 lecture"))

    def test_an_empty_phrase_matches_nothing(self):
        for p in ("", "   ", None):
            self.assertFalse(core.phrase_in_title(p or "", "anything at all"), repr(p))

    def test_extra_whitespace_in_the_phrase_is_fine(self):
        self.assertTrue(core.phrase_in_title("  dune    audiobook ", "dune audiobook"))

    def test_words_match_as_substrings_so_plurals_and_punctuation_work(self):
        self.assertTrue(core.phrase_in_title("python tutorial", "Python Tutorials for beginners"))
        self.assertTrue(core.phrase_in_title("dune audiobook", "Dune:Audiobook"))


LINKS = ("https://www.youtube.com/watch?v=qtwk9zmq4e0", "http://youtu.be/abc123", "www.youtube.com/watch?v=x",
         "youtube.com/watch?v=abcdefghijk", "youtu.be/abcdefghijk", "HTTPS://WWW.YOUTUBE.COM/Playlist?list=PL1",
         "https://example.org/some/page")


class Links(unittest.TestCase):
    def test_links_are_recognised(self):
        for link in LINKS:
            self.assertTrue(core.looks_like_link(link), link)

    def test_ordinary_phrases_are_not_links(self):
        for phrase in ("dune audiobook", "cs50 lecture 3", "atomic habits", "how to use youtube.com effectively",
                       "python 3.11 tutorial", "what is www", "the x.y problem"):
            self.assertFalse(core.looks_like_link(phrase), phrase)

    def test_a_link_can_never_become_an_approval(self):
        for link in LINKS:
            self.assertIsNone(core.normalize_phrase(link), link)
        out = core.clean_approvals([{"phrase": LINKS[0], "added": READY}, book("dune audiobook")])
        self.assertEqual([e["phrase"] for e in out], ["dune audiobook"])           # old junk is dropped on load


class AlwaysApprovals(unittest.TestCase):
    def test_the_flag_survives_cleaning_and_is_omitted_otherwise(self):
        out = core.clean_approvals([book("dune audiobook"), book("python tutorial", always=False)])
        self.assertEqual(out[0], {"phrase": "dune audiobook", "added": READY, "always": True})
        self.assertEqual(out[1], {"phrase": "python tutorial", "added": READY})
        self.assertNotIn("always", out[1])

    def test_only_a_real_true_counts(self):
        for junk in ("yes", 1, "True", [], {}, None):
            out = core.clean_approvals([{"phrase": "dune audiobook", "added": READY, "always": junk}])
            self.assertNotIn("always", out[0], repr(junk))

    def test_a_short_phrase_cannot_be_unlimited(self):
        out = core.clean_approvals([book("dune"), book("cs50 x")])         # 4 and 5 characters
        self.assertTrue(all("always" not in e for e in out))

    def test_the_phrase_just_long_enough_can(self):
        p = "x" * core.LEARNING_MIN_PHRASE_ALWAYS
        self.assertTrue(core.clean_approvals([book(p)])[0].get("always"))
        self.assertNotIn("always", core.clean_approvals([book(p[:-1])])[0])

    def test_there_is_a_cap_even_if_the_file_is_edited_by_hand(self):
        entries = [book(f"audiobook number {i}", added=READY + i) for i in range(core.LEARNING_MAX_ALWAYS + 3)]
        out = core.clean_approvals(entries)
        self.assertEqual(sum(1 for e in out if e.get("always")), core.LEARNING_MAX_ALWAYS)
        self.assertEqual(len(out), len(entries))                         # extras are kept, just not unlimited
        self.assertTrue(out[0].get("always"))                            # the oldest ones keep it

    def test_re_adding_the_same_phrase_cannot_upgrade_it(self):
        out = core.clean_approvals([book("dune audiobook", added=500, always=False),
                                    book("dune audiobook", added=900, always=True)])
        self.assertEqual(out, [{"phrase": "dune audiobook", "added": 500.0}])


class YouTubeOpen(unittest.TestCase):
    def test_an_active_audiobook_opens_youtube_without_a_learning_break(self):
        st = state(book())
        self.assertTrue(core.youtube_open(st, MORNING))
        self.assertEqual(core.always_phrases(st, MORNING), ["dune audiobook"])
        self.assertFalse(core.learning_active(st, MORNING))

    def test_it_does_not_count_until_the_wait_is_over(self):
        st = state(book(added=MORNING - 60))
        self.assertFalse(core.youtube_open(st, MORNING))
        self.assertTrue(core.youtube_open(st, MORNING - 60 + DELAY))

    def test_an_ordinary_approval_does_not_open_youtube_by_itself(self):
        st = state(book("python tutorial", always=False))
        self.assertFalse(core.youtube_open(st, MORNING))
        self.assertEqual(core.always_phrases(st, MORNING), [])

    def test_nuclear_closes_it(self):
        st = state(book(), nuclear_until=MORNING + 100)
        self.assertFalse(core.youtube_open(st, MORNING))
        self.assertEqual(core.allowed_phrases(st, MORNING), [])
        self.assertTrue(core.youtube_open(st, MORNING + 101))

    def test_a_learning_break_alone_opens_it_too(self):
        st = state(book("python tutorial", always=False), learning_until=MORNING + 60)
        self.assertTrue(core.youtube_open(st, MORNING))

    def test_nothing_approved_nothing_open(self):
        self.assertFalse(core.youtube_open(core.default_state(), MORNING))

    def test_youtube_is_dropped_from_the_hosts_list_only_while_open(self):
        st = state(book())
        eff = core.effective_blocklist(st, MORNING)
        self.assertNotIn("youtube.com", eff)
        self.assertNotIn("youtu.be", eff)
        self.assertIn("instagram.com", eff)
        self.assertIn("youtube.com", core.effective_blocklist(st, MORNING - DELAY))   # before it counts


class FreeTimeLeavesYouTubeAlone(unittest.TestCase):
    """Regression: after clock-out the tab rule kept closing non-approved YouTube tabs, even though
    nothing was being blocked any more."""

    def setUp(self):
        self.st = state(book(), learning_until=0)

    def test_open_only_while_sites_are_actually_blocked(self):
        from support import EVENING, NIGHT, EARLY
        self.assertTrue(core.youtube_open(self.st, MORNING))
        for t in (EVENING, NIGHT, EARLY):                          # clocked out / after hours / before hours
            self.assertFalse(core.youtube_open(self.st, t), t)
            self.assertEqual(core.allowed_phrases(self.st, t), [], t)

    def test_an_ordinary_break_frees_it_too(self):
        self.st["unlock_until"] = MORNING + 300
        self.assertFalse(core.youtube_open(self.st, MORNING))
        self.assertFalse(core.title_allowed(self.st, "dune audiobook", MORNING))     # nothing to enforce

    def test_a_learning_break_stops_mattering_at_clock_out(self):
        from support import EVENING
        st = state(book("python tutorial", always=False), learning_until=EVENING + 600)
        self.assertFalse(core.youtube_open(st, EVENING))

    def test_the_weekend_window_starts_at_its_own_time(self):
        from support import SAT_MORNING, SAT_EARLY, SAT_LATE
        st = state(book(added=SAT_EARLY - DELAY - 10))
        self.assertFalse(core.youtube_open(st, SAT_LATE))       # 19:00 Sat: after the weekend end
        self.assertTrue(core.youtube_open(st, SAT_MORNING))
        self.assertFalse(core.youtube_open(st, SAT_EARLY))      # 08:00 Sat: weekday hours would be open

    def test_nuclear_still_wins_over_free_time(self):
        from support import EVENING
        st = state(book(), nuclear_until=EVENING + 600)
        self.assertFalse(core.youtube_open(st, EVENING))                        # closed, as always
        self.assertTrue(core.sites_blocked(st, EVENING))


class WhichTitlesMayStayOpen(unittest.TestCase):
    def setUp(self):
        self.st = state(book("dune audiobook"), book("python tutorial", always=False))

    def test_audiobook_mode_allows_only_the_audiobook(self):
        self.assertEqual(core.allowed_phrases(self.st, MORNING), ["dune audiobook"])
        self.assertTrue(core.title_allowed(self.st, "dune audiobook - youtube", MORNING))
        self.assertFalse(core.title_allowed(self.st, "python tutorial - youtube", MORNING))

    def test_a_learning_break_allows_everything_approved(self):
        self.st["learning_until"] = MORNING + 600
        self.assertEqual(sorted(core.allowed_phrases(self.st, MORNING)), ["dune audiobook", "python tutorial"])
        self.assertTrue(core.title_allowed(self.st, "python tutorial - youtube", MORNING))
        self.assertTrue(core.title_allowed(self.st, "dune audiobook - youtube", MORNING))

    def test_nothing_is_allowed_when_youtube_is_not_open(self):
        st = state(book("python tutorial", always=False))
        self.assertEqual(core.allowed_phrases(st, MORNING), [])
        self.assertFalse(core.title_allowed(st, "python tutorial - youtube", MORNING))


class AudiobookHosts(IsolatedCore):
    def test_enforcement_leaves_youtube_open_for_an_audiobook_and_everything_else_blocked(self):
        core.apply_enforcement(self.state(learning_approved=[book()]), MORNING)
        text = self.hosts()
        self.assertIn(core.MARK_START, text)
        self.assertNotIn("youtube.com", text)
        self.assertIn("0.0.0.0 reddit.com", text)

    def test_it_does_not_use_up_a_learning_break(self):
        st = self.state(learning_approved=[book()])
        core.apply_enforcement(st, MORNING)
        self.assertEqual(st["learning_used"], 0)

    def test_nuclear_blocks_youtube_again_in_the_hosts_file(self):
        core.apply_enforcement(self.state(learning_approved=[book()], nuclear_until=MORNING + 60), MORNING)
        self.assertIn("0.0.0.0 youtube.com", self.hosts())


@both
class AudiobookInTheApp(AppCase):
    def setUp(self):
        super().setUp()
        self.st["learning_approved"] = [book()]

    def watch(self, title, seconds):
        self.set_fg(CHROME, title.lower())          # the real foreground query returns lower-case titles
        self.tick(seconds)

    def test_the_audiobook_plays_for_hours_without_a_learning_break(self):
        self.watch("Dune (Audiobook) - Frank Herbert - YouTube - Google Chrome", 3 * 3600 // 60)
        for _ in range(180):                                       # three hours, a minute at a time
            self.fake.advance(60)
            self.app._tick_body()
        self.assertEqual(self.ctrl_w, [])
        self.assertEqual(self.st["learning_used"], 0)
        self.assertEqual(self.st["learning_until"], 0)

    def test_anything_else_on_youtube_is_closed_after_the_grace_period(self):
        self.watch("funny cat compilation - youtube - google chrome", GRACE - 1)
        self.assertEqual(self.ctrl_w, [])
        self.tick(3)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_the_movie_trailer_does_not_sneak_in(self):
        self.watch("Dune Part Two - Official Trailer - YouTube - Google Chrome", GRACE + 3)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_it_keeps_working_during_a_study_session(self):
        self.app.toggle_session()
        self.watch("Dune (Audiobook) - YouTube - Google Chrome", 120)
        self.assertEqual(self.ctrl_w, [])
        self.assertTrue(self.app.session_active)

    def test_a_normal_approval_is_not_enough_outside_a_learning_break(self):
        self.st["learning_approved"] = [book(), book("python tutorial", always=False)]
        self.watch("python tutorial for beginners - youtube - google chrome", GRACE + 3)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_a_normal_approval_works_again_during_a_learning_break(self):
        self.st["learning_approved"] = [book(), book("python tutorial", always=False)]
        self.app.learning_break()
        self.watch("python tutorial for beginners - youtube - google chrome", 60)
        self.assertEqual(self.ctrl_w, [])
        self.assertEqual(self.st["learning_used"], 1)

    def test_nuclear_shuts_youtube_immediately_even_for_the_audiobook(self):
        self.st["nuclear_until"] = self.fake.now + 600
        self.watch("Dune (Audiobook) - YouTube - Google Chrome", 1)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_other_blocked_sites_are_still_closed_at_once(self):
        self.watch("(2) instagram - google chrome", 1)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_it_waits_for_the_approval_period_like_everything_else(self):
        self.st["learning_approved"] = [book(added=self.fake.now - 60)]
        self.watch("Dune (Audiobook) - YouTube - Google Chrome", 1)
        self.assertEqual(len(self.ctrl_w), 1)                      # still blocked: closed at once, no grace

    def test_removing_it_shuts_youtube_again_immediately(self):
        self.app._show_full()
        self.app.remove_approval("dune audiobook")
        self.assertFalse(core.youtube_open(self.st, self.fake.now))
        self.watch("Dune (Audiobook) - YouTube - Google Chrome", 1)
        self.assertEqual(len(self.ctrl_w), 1)


@both
class ClockOutWithAnAudiobook(AppCase):
    def setUp(self):
        super().setUp()
        self.st["learning_approved"] = [book()]

    def watch(self, title, seconds):
        self.set_fg(CHROME, title.lower())
        self.tick(seconds)

    def test_before_clock_out_other_youtube_tabs_are_closed(self):
        self.watch("funny cat compilation - YouTube - Google Chrome", GRACE + 3)
        self.assertEqual(len(self.ctrl_w), 1)

    def test_after_clock_out_nothing_on_youtube_is_closed(self):
        from support import EVENING
        self.set_time(EVENING)
        self.app._clocked_prev = True
        self.watch("funny cat compilation - YouTube - Google Chrome", 120)
        self.assertEqual(self.ctrl_w, [])
        self.assertIsNone(self.app._lt_bad_since)

    def test_crossing_clock_out_while_watching_stops_the_closing(self):
        from support import ts
        self.st["clockout_time"] = "20:00"
        self.set_time(ts(2026, 9, 23, 19, 59, 40))
        self.app._clocked_prev = False
        self.watch("funny cat compilation - YouTube - Google Chrome", 8)         # still 19:59 - clock running
        self.assertEqual(self.ctrl_w, [])
        self.tick(60)                                                            # 20:00 passes
        self.ctrl_w.clear()
        self.tick(120)
        self.assertEqual(self.ctrl_w, [])

    def test_after_hours_and_during_breaks_it_leaves_youtube_alone(self):
        from support import NIGHT
        self.set_time(NIGHT)
        self.watch("funny cat compilation - YouTube - Google Chrome", 60)
        self.assertEqual(self.ctrl_w, [])
        self.set_time(MORNING)
        self.st["unlock_until"] = MORNING + 600
        self.watch("funny cat compilation - YouTube - Google Chrome", 60)
        self.assertEqual(self.ctrl_w, [])

    def test_a_learning_break_running_at_clock_out_shows_clocked_out(self):
        from support import ts
        self.st["learning_until"] = ts(2026, 9, 24, 0, 30)
        self.set_time(ts(2026, 9, 23, 23, 59, 30))
        self.assertEqual(self.app._status()[0], "🕗 CLOCKED OUT")

    def test_the_morning_after_it_works_again(self):
        from support import ts
        self.set_time(ts(2026, 9, 24, 10, 0))
        self.st["learning_approved"] = [book(added=ts(2026, 9, 24, 10, 0) - DELAY - 10)]
        self.watch("funny cat compilation - YouTube - Google Chrome", GRACE + 3)
        self.assertEqual(len(self.ctrl_w), 1)


@both
class AudiobookInTheLearningTab(AppCase):
    def setUp(self):
        super().setUp()
        self.app._show_full()
        self.popups.clear()

    def add(self, text, always=True):
        self.app._set_entry(self.app.l_entry, text)
        self.app.l_always.set(1 if always else 0)
        self.app.add_approval()

    def msg(self):
        return self.text_of(self.app.l_msg)

    def test_ticking_the_box_makes_it_unlimited_and_resets_the_box(self):
        self.add("Dune Audiobook")
        self.assertEqual(self.st["learning_approved"],
                         [{"phrase": "dune audiobook", "added": self.fake.now, "always": True}])
        self.assertEqual(self.app.l_always.get(), 0)
        self.assertIn("no time limit", self.msg())

    def test_unticked_stays_an_ordinary_approval(self):
        self.add("Dune Audiobook", always=False)
        self.assertNotIn("always", self.st["learning_approved"][0])
        self.assertIn("for learning breaks", self.msg())

    def test_it_still_has_to_wait_before_it_counts(self):
        self.add("Dune Audiobook")
        self.assertFalse(core.youtube_open(self.st, self.fake.now))
        self.fake.advance(DELAY)
        self.assertTrue(core.youtube_open(self.st, self.fake.now))

    def test_a_short_phrase_is_refused_as_unlimited(self):
        self.add("dune")
        self.assertEqual(self.st["learning_approved"], [])
        self.assertIn("at least", self.msg())
        self.add("dune", always=False)                                # but fine as an ordinary approval
        self.assertEqual(len(self.st["learning_approved"]), 1)

    def test_the_cap(self):
        for i in range(core.LEARNING_MAX_ALWAYS):
            self.add(f"audiobook number {i}")
        self.add("one audiobook too many")
        self.assertEqual(len(self.st["learning_approved"]), core.LEARNING_MAX_ALWAYS)
        self.assertIn("at most", self.msg())
        self.app.remove_approval("audiobook number 0")
        self.add("one audiobook too many")
        self.assertEqual(len(self.st["learning_approved"]), core.LEARNING_MAX_ALWAYS)

    def test_the_list_marks_unlimited_entries(self):
        self.add("Dune Audiobook")
        self.add("python tutorial", always=False)
        rows = list(dict.fromkeys(label_texts(self.app.l_list)))
        self.assertIn("🎧 dune audiobook", rows)
        self.assertIn("python tutorial", rows)

    def test_the_status_line_announces_audiobook_mode_once_active(self):
        self.st["learning_approved"] = [book()]
        self.app._render_learning()
        self.assertIn("Audiobook mode", self.text_of(self.app.l_status))
        self.st["learning_approved"] = [book(added=self.fake.now - 30)]
        self.app._render_learning()
        self.assertNotIn("Audiobook mode", self.text_of(self.app.l_status))

    def test_pasting_a_link_explains_why_it_cannot_work_instead_of_silently_accepting_it(self):
        for link in LINKS[:3]:
            self.add(link)
            self.assertIn("That's a link", self.msg(), link)
        self.assertEqual(self.st["learning_approved"], [])

    def test_there_is_a_checkbox_that_explains_itself(self):
        texts = " ".join(label_texts(self.app.tab_learn))
        self.assertIn("no time limit", texts)
        self.assertIn(f"{core.LEARNING_MIN_PHRASE_ALWAYS}+ characters", texts)


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


def label_texts(widget):
    out = []
    for w in walk(widget):
        try:
            t = w.cget("text")
        except Exception:
            continue
        if t:
            out.append(t)
    return out


if __name__ == "__main__":
    unittest.main()
