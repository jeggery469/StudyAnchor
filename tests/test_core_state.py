"""core: state file, domain parsing, title keywords."""
import json
import os
import unittest
from unittest import mock

from support import IsolatedCore, MORNING
import core


class NormalizeDomain(unittest.TestCase):
    def test_accepts_and_cleans(self):
        cases = {
            "youtube.com": "youtube.com",
            "  YouTube.COM  ": "youtube.com",
            "www.youtube.com": "youtube.com",
            "https://www.Example-Site.com/path?x=1#frag": "example-site.com",
            "http://old.reddit.com/r/all": "old.reddit.com",
            "sub.domain.example.co.uk": "sub.domain.example.co.uk",
            "example.com:8080/x": "example.com",
            "9gag.com": "9gag.com",
            "https://archive.org/details/the-cat-returns_202508/All_Movies/": "archive.org",
            "x.com": "x.com",
            "trailing.dot.com.": "trailing.dot.com",
        }
        for raw, want in cases.items():
            self.assertEqual(core.normalize_domain(raw), want, raw)

    def test_rejects_junk(self):
        for bad in ("", "   ", "localhost", "not a site", "a@b.com", "192.168.0.1", "1.2.3.4",
                    ".com", "-bad.com", "bad-.com", "a..b.com", "a b.com", "exa_mple.com",
                    "http://", "?query", "x" * 64 + ".com", None):
            self.assertIsNone(core.normalize_domain(bad), repr(bad))

    def test_idn_becomes_punycode(self):
        self.assertEqual(core.normalize_domain("例子.com"), "xn--fsqu00a.com")

    def test_length_limit(self):
        self.assertIsNone(core.normalize_domain(".".join(["a" * 60] * 5) + ".com"))


class TitleKeywords(unittest.TestCase):
    def test_uses_the_site_name_not_subdomains(self):
        kws = core.title_keywords(["search.bilibili.com", "space.bilibili.com", "gateway.example.com"])
        self.assertIn("bilibili", kws)
        self.assertIn("example", kws)
        for word in ("search", "space", "gateway"):
            self.assertNotIn(word, kws)

    def test_short_names_are_skipped(self):
        self.assertEqual(core.title_keywords(["x.com", "b23.tv", "t.co"]), [])

    def test_ambiguous_words_need_a_specific_phrase(self):
        kws = core.title_keywords(["amazon.com", "archive.org"])
        self.assertEqual(sorted(kws), ["amazon.com", "internet archive"])

    def test_dedupes_and_sorts(self):
        kws = core.title_keywords(["youtube.com", "www.youtube.com", "youtu.be"])
        self.assertEqual(kws, sorted(set(kws)))

    def test_handles_odd_input(self):
        self.assertEqual(core.title_keywords([]), [])
        self.assertEqual(core.title_keywords(["localhost", ""]), [])

    def test_real_world_titles(self):
        kws = core.title_keywords(core.DEFAULT_BLOCKLIST + ["archive.org"])
        hit = ["(2) instagram", "youtube - watch stuff", "reddit - front page", "minecraft wiki",
               "naruto wiki | fandom", "bilibili - watch", "amazon.com : headphones",
               "all studio ghibli's movies : internet archive - google chrome",
               "netflix", "twitch", "(3) facebook"]
        safe = ["laotzu - google search - google chrome", "desmos | graphing calculator",
                "my playlist #2 - playlist by jeff | spotify", "amazon rainforest - wikipedia",
                "national archives - research", "archive of our own",
                "momentum and collisions (practice) | khan academy", "space - nasa",
                "search results", "gmail - inbox", "github - pull requests"]
        for t in hit:
            self.assertTrue(any(k in t for k in kws), t)
        for t in safe:
            self.assertFalse(any(k in t for k in kws), t)


class DefaultState(unittest.TestCase):
    def test_shape(self):
        st = core.default_state()
        self.assertEqual(st["schedule_start"], "07:00")
        self.assertEqual(st["schedule_end"], "00:00")
        self.assertEqual(st["clockout_time"], "23:59")
        self.assertGreaterEqual(core.schedule_hours(st["schedule_start"], st["schedule_end"]),
                                core.SCHEDULE_MIN_HOURS)
        self.assertEqual(core.CHEAT_LADDER, [5, 5, 5, 0])
        self.assertEqual(core.SESSION_REWARD_MIN, 15)
        self.assertEqual(st["blocklist"], core.DEFAULT_BLOCKLIST)

    def test_each_call_is_independent(self):
        a, b = core.default_state(), core.default_state()
        a["blocklist"].append("zzz.com")
        self.assertNotIn("zzz.com", b["blocklist"])

    def test_default_blocklist_is_clean_and_covers_the_requested_sites(self):
        for d in core.DEFAULT_BLOCKLIST:
            self.assertEqual(core.normalize_domain(d), d, d)
        self.assertEqual(len(core.DEFAULT_BLOCKLIST), len(set(core.DEFAULT_BLOCKLIST)))
        joined = " ".join(core.DEFAULT_BLOCKLIST)
        for need in ("youtube", "instagram", "reddit", "twitter", "fandom", "minecraft",
                     "bilibili", "amazon"):
            self.assertIn(need, joined)
        self.assertNotIn("discord", joined)   # removed: blocking it also blocked the desktop app

    def test_launcher_lists(self):
        self.assertIn("steam.exe", core.GAME_LAUNCHER_PROCS)
        self.assertNotIn("Agent.exe", core.GAME_LAUNCHER_PROCS)      # too generic to kill blindly
        self.assertNotIn("origin", [n.lower() for n in core.GAME_LAUNCHER_UNIX_NAMES if " " in n])


class LoadSaveState(IsolatedCore):
    def write_state(self, obj):
        with open(core.STATE_PATH, "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj))

    def test_missing_file_gives_defaults(self):
        self.assertEqual(core.load_state(), core.default_state())

    def test_corrupt_or_wrong_shape_gives_defaults(self):
        for junk in ("{not json", "", "[1,2,3]", "null", '"text"', "42"):
            self.write_state(junk)
            self.assertEqual(core.load_state(), core.default_state(), junk)

    def test_roundtrip(self):
        st = core.default_state()
        st["time_bank_minutes"] = 33.5
        st["reminders"] = "- don’t quit"
        self.assertTrue(core.save_state(st))
        got = core.load_state()
        self.assertEqual(got["time_bank_minutes"], 33.5)
        self.assertEqual(got["reminders"], "- don’t quit")

    def test_save_leaves_no_temp_files(self):
        core.save_state(core.default_state())
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith(".tmp")], [])

    def test_failed_save_cleans_up_and_reports_false(self):
        with mock.patch("os.replace", side_effect=OSError("boom")):
            self.assertFalse(core.save_state(core.default_state()))
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith(".tmp")], [])

    def test_unserializable_state_reports_false(self):
        st = core.default_state()
        st["bad"] = object()
        self.assertFalse(core.save_state(st))
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith(".tmp")], [])

    def test_schedule_cannot_come_from_the_file(self):
        self.write_state({"schedule_start": "13:00", "schedule_end": "14:00", "clockout_time": "09:00"})
        st = core.load_state()
        self.assertEqual((st["schedule_start"], st["schedule_end"], st["clockout_time"]),
                         ("07:00", "00:00", "23:59"))

    def test_wrong_types_fall_back_to_defaults(self):
        self.write_state({"unlock_until": "abc", "time_bank_minutes": None, "strobe_enabled": "yes",
                          "reminders": 5, "session_length_min": True, "nuclear_until": float("nan"),
                          "snooze_min": 25})
        st = core.load_state()
        d = core.default_state()
        for k in ("unlock_until", "time_bank_minutes", "strobe_enabled", "reminders",
                  "session_length_min", "nuclear_until"):
            self.assertEqual(st[k], d[k], k)
        self.assertEqual(st["snooze_min"], 25)               # valid values are kept

    def test_the_session_floor_is_twenty_minutes(self):
        self.assertEqual(core.MIN_SESSION_MIN, 20)
        self.assertGreaterEqual(core.default_state()["session_length_min"], core.MIN_SESSION_MIN)

    def test_a_saved_session_length_below_the_floor_is_raised(self):
        for short in (0, 1, 5, 19, -30, 19.9):
            self.write_state({"session_length_min": short})
            self.assertEqual(core.load_state()["session_length_min"], 20, short)

    def test_a_saved_session_length_at_or_above_the_floor_is_kept(self):
        for ok in (20, 45, 90, 1440):
            self.write_state({"session_length_min": ok})
            self.assertEqual(core.load_state()["session_length_min"], ok, ok)

    def test_a_junk_session_length_gives_the_default_not_the_floor(self):
        for junk in ("5", None, True, [3], float("nan")):
            self.write_state({"session_length_min": junk})
            self.assertEqual(core.load_state()["session_length_min"],
                             core.default_state()["session_length_min"], junk)

    def test_the_session_length_is_always_a_whole_number(self):
        self.write_state({"session_length_min": 33.7})
        got = core.load_state()["session_length_min"]
        self.assertIsInstance(got, int)
        self.assertEqual(got, 33)

    def test_infinity_in_file_is_rejected(self):
        self.write_state('{"unlock_until": Infinity}')
        self.assertEqual(core.load_state()["unlock_until"], 0.0)

    def test_valid_values_survive(self):
        self.write_state({"unlock_until": 123.0, "cheat_index": 3, "strobe_enabled": False})
        st = core.load_state()
        self.assertEqual((st["unlock_until"], st["cheat_index"], st["strobe_enabled"]), (123.0, 3, False))

    def test_scrubbing_rewrites_a_file_that_still_holds_removed_data(self):
        self.write_state({"cheat_index": 2, "usage": {"2026-09-23": {"khan academy": 5}}})
        self.assertTrue(core.scrub_state_file())
        with open(core.STATE_PATH, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("khan academy", text)
        self.assertNotIn('"usage"', text)
        self.assertEqual(core.load_state()["cheat_index"], 2)             # the rest is untouched
        self.assertFalse(core.scrub_state_file())                          # and a second pass has nothing to do

    def test_scrubbing_leaves_a_clean_file_alone(self):
        self.write_state({"cheat_index": 2})
        with open(core.STATE_PATH, "rb") as f:
            before = f.read()
        self.assertFalse(core.scrub_state_file())
        with open(core.STATE_PATH, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_scrubbing_copes_with_a_missing_or_broken_file(self):
        if os.path.exists(core.STATE_PATH):
            os.remove(core.STATE_PATH)
        self.assertFalse(core.scrub_state_file())
        self.write_state("{ not json")
        self.assertFalse(core.scrub_state_file())
        self.write_state("[1, 2]")
        self.assertFalse(core.scrub_state_file())

    def test_scrubbing_covers_every_removed_key(self):
        self.write_state({**{k: 1 for k in core.OBSOLETE_KEYS}, "cheat_index": 4})
        self.assertTrue(core.scrub_state_file())
        with open(core.STATE_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        for k in core.OBSOLETE_KEYS:
            self.assertNotIn(k, saved, k)
        self.assertEqual(saved["cheat_index"], 4)

    def test_old_usage_history_is_dropped_and_never_written_back(self):
        self.write_state({"cheat_index": 2, "usage": {"2026-09-23": {"\U0001f310 khan academy": 5}}})
        st = core.load_state()
        self.assertNotIn("usage", st)
        self.assertEqual(st["cheat_index"], 2)                     # everything else is kept
        self.assertTrue(core.save_state(st))
        with open(core.STATE_PATH, encoding="utf-8") as f:
            self.assertNotIn("khan academy", f.read())
        self.assertIn("usage", core.OBSOLETE_KEYS)
        self.assertNotIn("usage", core.default_state())

    def test_keys_from_removed_features_are_dropped(self):
        old = {"market": {"x": 1}, "enabled": False, "day_off_until": 5, "go_outside_after_min": 180,
               "go_outside_lock_min": 20, "screen_on_min": 12.5, "account": {"u": 1}, "sync": True,
               "time_bank_minutes": 7}
        self.write_state(old)
        st = core.load_state()
        for k in core.OBSOLETE_KEYS:
            self.assertNotIn(k, st, k)
        self.assertEqual(st["time_bank_minutes"], 7)                # real data survives
        core.save_state(st)
        with open(core.STATE_PATH, encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertNotIn("market", on_disk)

    def test_default_state_has_no_dead_keys(self):
        for k in core.OBSOLETE_KEYS:
            self.assertNotIn(k, core.default_state(), k)
        self.assertFalse(hasattr(core, "day_off"))

    def test_unknown_keys_are_preserved(self):
        self.write_state({"future_feature": {"a": 1}})
        self.assertEqual(core.load_state()["future_feature"], {"a": 1})

    def test_blocklist_merges_defaults_and_keeps_custom_sites(self):
        self.write_state({"blocklist": ["custom.org", "youtube.com"]})
        bl = core.load_state()["blocklist"]
        self.assertEqual(bl[0], "custom.org")
        for d in core.DEFAULT_BLOCKLIST:
            self.assertIn(d, bl)
        self.assertEqual(len(bl), len(set(bl)))

    def test_blocklist_cannot_be_emptied_from_the_file(self):
        for shrunk in ([], None, "youtube.com", 5, {"a": 1}):
            self.write_state({"blocklist": shrunk})
            bl = core.load_state()["blocklist"]
            for d in core.DEFAULT_BLOCKLIST:
                self.assertIn(d, bl, repr(shrunk))

    def test_discord_was_removed_and_cannot_come_back_even_from_saved_state(self):
        self.write_state({"blocklist": ["discord.com", "discord.gg", "gateway.discord.gg",
                                        "discordapp.com", "cdn.discordapp.com", "youtube.com"]})
        bl = core.load_state()["blocklist"]
        self.assertFalse(any("discord" in d for d in bl), bl)
        self.assertIn("youtube.com", bl)          # unrelated saved entries are untouched
        for d in core.MISTAKENLY_BLOCKED:
            self.assertNotIn(d, core.DEFAULT_BLOCKLIST)

    def test_the_internet_archive_is_released_from_saved_state(self):
        self.write_state({"blocklist": ["archive.org", "https://www.archive.org/details/x/", "reddit.com"]})
        bl = core.load_state()["blocklist"]
        self.assertNotIn("archive.org", bl)
        self.assertIn("reddit.com", bl)
        self.assertNotIn("archive.org", core.DEFAULT_BLOCKLIST)

    def test_the_internet_archive_is_not_in_the_hosts_block(self):
        self.write_state({"blocklist": ["archive.org"]})
        st = core.load_state()
        self.assertNotIn("archive.org", core.effective_blocklist(st, MORNING))

    def test_blocklist_entries_are_normalized(self):
        self.write_state({"blocklist": ["https://example.org/details/x/", "WWW.Foo.com", "bad entry", 7, None]})
        bl = core.load_state()["blocklist"]
        self.assertIn("example.org", bl)
        self.assertIn("foo.com", bl)
        self.assertNotIn("bad entry", bl)
        self.assertTrue(all(isinstance(d, str) and core.normalize_domain(d) == d for d in bl))


class EnsureDir(IsolatedCore):
    def test_creates_data_dir(self):
        target = os.path.join(self.tmp, "nested", "dir")
        core.DATA_DIR = target
        core._ensure_dir()
        self.assertTrue(os.path.isdir(target))

    def test_never_raises(self):
        with mock.patch("os.makedirs", side_effect=PermissionError):
            core._ensure_dir()


if __name__ == "__main__":
    unittest.main()
