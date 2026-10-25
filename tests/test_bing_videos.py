"""Bing video search plays YouTube inline (a loophole around the YouTube rules), so its tab is closed."""
import unittest

from appsupport import AppCase
from support import IsolatedCore, MORNING, EVENING, NIGHT
import core

EDGE = "msedge.exe"
BING = "how to play a clarinet - search videos and 1 more page - personal - microsoft​ edge"
BING_PLAIN = "how to play a clarinet - search videos"


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


class Keywords(IsolatedCore):
    def test_the_video_search_fragments_are_always_included(self):
        kws = core.blocked_title_keywords(core.default_state(), MORNING)
        for frag in core.VIDEO_SEARCH_TITLES:
            self.assertIn(frag, kws)

    def test_the_blocklist_keywords_are_still_there(self):
        kws = core.blocked_title_keywords(core.default_state(), MORNING)
        self.assertIn("instagram", kws)
        self.assertIn("reddit", kws)

    def test_no_duplicates_and_sorted(self):
        kws = core.blocked_title_keywords(core.default_state(), MORNING)
        self.assertEqual(kws, sorted(set(kws)))

    def test_google_videos_titles_are_included(self):
        kws = core.blocked_title_keywords(core.default_state(), MORNING)
        self.assertTrue(any(k in "google videos - google chrome" for k in kws))

    def test_ordinary_google_search_is_not_matched(self):
        kws = core.blocked_title_keywords(core.default_state(), MORNING)
        self.assertFalse(any(k in "how to play a clarinet - google search - google chrome" for k in kws))

    def test_ordinary_bing_search_is_not_matched(self):
        kws = core.blocked_title_keywords(core.default_state(), MORNING)
        for t in ("how to play a clarinet - search - microsoft edge", "bing", "clarinet lessons - bing images",
                  "bing search results - microsoft edge"):
            self.assertFalse(any(k in t for k in kws), t)


@both
class ClosingBingVideos(AppCase):
    def test_closed_during_work_hours(self):
        self.set_fg(EDGE, BING)
        self.tick(3)
        self.assertGreaterEqual(len(self.ctrl_w), 1)

    def test_plain_title_closed_too(self):
        self.set_fg(EDGE, BING_PLAIN)
        self.tick(3)
        self.assertGreaterEqual(len(self.ctrl_w), 1)

    def test_a_normal_bing_search_is_left_alone(self):
        self.set_fg(EDGE, "how to play a clarinet - search - personal - microsoft edge")
        self.tick(5)
        self.assertEqual(self.ctrl_w, [])

    def test_still_closed_during_a_learning_break(self):
        self.st["learning_until"] = self.fake.now + 600
        self.set_fg(EDGE, BING)
        self.tick(3)
        self.assertGreaterEqual(len(self.ctrl_w), 1)

    def test_still_closed_in_audiobook_mode(self):
        self.st["learning_approved"] = [{"phrase": "dune audiobook", "added": self.fake.now - 99999,
                                         "always": True}]
        self.set_fg(EDGE, BING)
        self.tick(3)
        self.assertGreaterEqual(len(self.ctrl_w), 1)

    def test_free_time_leaves_it_alone(self):
        for when in (EVENING, NIGHT):
            self.ctrl_w.clear()
            self.set_time(when)
            self.set_fg(EDGE, BING)
            self.tick(3)
            self.assertEqual(self.ctrl_w, [], when)

    def test_a_break_leaves_it_alone(self):
        self.st["unlock_until"] = self.fake.now + 600
        self.set_fg(EDGE, BING)
        self.tick(3)
        self.assertEqual(self.ctrl_w, [])

    def test_only_browsers_are_touched(self):
        self.set_fg("notepad.exe", BING)
        self.tick(3)
        self.assertEqual(self.ctrl_w, [])


if __name__ == "__main__":
    unittest.main()
