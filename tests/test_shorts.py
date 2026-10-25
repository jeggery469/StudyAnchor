"""YouTube Shorts is blocked completely, through the browsers' URL-blocklist policy.
Every test works on a throwaway key under HKEY_CURRENT_USER (see support.py) - never the real policies."""
import unittest
from unittest import mock

from support import IsolatedCore, MORNING, EVENING, NIGHT, SAT_LATE
import core

WIN = core.IS_WIN
if WIN:
    import winreg

CHROME = "Google\\Chrome\\URLBlocklist"
EDGE = "Microsoft\\Edge\\URLBlocklist"
BRAVE = "BraveSoftware\\Brave\\URLBlocklist"
FIREFOX = "Mozilla\\Firefox\\WebsiteFilter\\Block"


def wipe():
    """Remove everything under the scratch policy root."""
    def tree(path):
        try:
            with winreg.OpenKey(core._policy_hive(), path, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    tree(path + "\\" + sub)
            winreg.DeleteKey(core._policy_hive(), path)
        except OSError:
            pass
    tree(core.POLICY_ROOT)


def put(sub, name, value, kind=None):
    with winreg.CreateKeyEx(core._policy_hive(), core._policy_path(sub), 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, kind or winreg.REG_SZ, value)


@unittest.skipUnless(WIN, "the policy lives in the Windows registry")
class PolicyCase(IsolatedCore):
    def setUp(self):
        super().setUp()
        wipe()
        core._policy_warned = False
        self.addCleanup(wipe)


class TestsAreSandboxed(unittest.TestCase):
    @unittest.skipUnless(WIN, "Windows")
    def test_the_policy_location_is_the_scratch_key_not_the_machine_policies(self):
        self.assertEqual(core.POLICY_HIVE, "HKCU")
        self.assertIn("FocusToolTests", core.POLICY_ROOT)
        self.assertEqual(core._policy_hive(), winreg.HKEY_CURRENT_USER)

    def test_the_real_defaults_are_the_machine_wide_policy_keys(self):
        from support import REAL_POLICY_HIVE, REAL_POLICY_ROOT
        if WIN:
            self.assertEqual(REAL_POLICY_HIVE, "HKLM")
            self.assertEqual(REAL_POLICY_ROOT, "SOFTWARE\\Policies")


class Patterns(unittest.TestCase):
    def test_chromium_blocks_the_shorts_path_only(self):
        self.assertEqual(core.SHORTS_PATTERNS_CHROMIUM, ["youtube.com/shorts"])

    def test_firefox_patterns_cover_the_bare_and_subdomain_hosts(self):
        self.assertIn("*://youtube.com/shorts/*", core.SHORTS_PATTERNS_FIREFOX)
        self.assertIn("*://*.youtube.com/shorts/*", core.SHORTS_PATTERNS_FIREFOX)

    def test_nothing_that_would_block_the_rest_of_youtube(self):
        for _sub, patterns in core.POLICY_TARGETS:
            for p in patterns:
                self.assertIn("shorts", p)
                self.assertNotEqual(p.rstrip("/*"), "youtube.com")

    def test_the_supported_browsers(self):
        subs = [sub for sub, _p in core.POLICY_TARGETS]
        self.assertEqual(subs, [CHROME, EDGE, BRAVE, FIREFOX])


class SettingIt(PolicyCase):
    def test_every_browser_gets_the_block(self):
        self.assertTrue(core.set_shorts_block(True))
        for sub, patterns in core.POLICY_TARGETS:
            vals = core._policy_values(sub)
            for p in patterns:
                self.assertIn(p, vals.values(), sub)
        self.assertTrue(core.shorts_block_in_place())

    def test_values_are_numbered_from_one(self):
        core.set_shorts_block(True)
        self.assertEqual(core._policy_values(CHROME), {"1": "youtube.com/shorts"})
        self.assertEqual(set(core._policy_values(FIREFOX)), {"1", "2"})

    def test_it_is_idempotent(self):
        core.set_shorts_block(True)
        before = {sub: core._policy_values(sub) for sub, _p in core.POLICY_TARGETS}
        for _ in range(5):
            self.assertTrue(core.set_shorts_block(True))
        after = {sub: core._policy_values(sub) for sub, _p in core.POLICY_TARGETS}
        self.assertEqual(before, after)

    def test_it_logs_once_when_it_first_blocks_and_not_on_every_check(self):
        with mock.patch.object(core, "log_event") as log:
            core.set_shorts_block(True)
            first = log.call_count
            core.set_shorts_block(True)
            core.set_shorts_block(True)
        self.assertEqual(first, len(core.POLICY_TARGETS))
        self.assertEqual(log.call_count, first)

    def test_not_in_place_before_it_is_set(self):
        self.assertFalse(core.shorts_block_in_place())

    def test_partly_in_place_is_not_in_place(self):
        core.set_shorts_block(True)
        with winreg.OpenKey(core._policy_hive(), core._policy_path(EDGE), 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "1")
        self.assertFalse(core.shorts_block_in_place())
        self.assertTrue(core.set_shorts_block(True))                    # and it repairs it
        self.assertTrue(core.shorts_block_in_place())

    def test_a_removed_entry_comes_back(self):
        core.set_shorts_block(True)
        wipe()
        self.assertFalse(core.shorts_block_in_place())
        core.set_shorts_block(True)
        self.assertTrue(core.shorts_block_in_place())


class LeavesOtherEntriesAlone(PolicyCase):
    def test_existing_entries_are_kept_and_ours_goes_in_a_free_slot(self):
        put(CHROME, "1", "example.com/private")
        put(CHROME, "2", "other.org")
        core.set_shorts_block(True)
        vals = core._policy_values(CHROME)
        self.assertEqual(vals["1"], "example.com/private")
        self.assertEqual(vals["2"], "other.org")
        self.assertIn("youtube.com/shorts", vals.values())
        self.assertEqual(len(vals), 3)

    def test_a_gap_in_the_numbering_is_filled_not_overwritten(self):
        put(CHROME, "1", "keep.me")
        put(CHROME, "3", "keep.me.too")
        core.set_shorts_block(True)
        vals = core._policy_values(CHROME)
        self.assertEqual(vals["1"], "keep.me")
        self.assertEqual(vals["3"], "keep.me.too")
        self.assertEqual(vals["2"], "youtube.com/shorts")

    def test_removing_ours_leaves_theirs(self):
        put(CHROME, "1", "example.com/private")
        core.set_shorts_block(True)
        self.assertTrue(core.set_shorts_block(False))
        self.assertEqual(core._policy_values(CHROME), {"1": "example.com/private"})

    def test_removing_when_we_were_never_there_does_nothing(self):
        put(CHROME, "1", "example.com/private")
        self.assertTrue(core.set_shorts_block(False))
        self.assertEqual(core._policy_values(CHROME), {"1": "example.com/private"})

    def test_non_string_values_are_ignored_and_kept(self):
        put(CHROME, "9", 5, winreg.REG_DWORD)
        core.set_shorts_block(True)
        self.assertEqual(core._policy_values(CHROME), {"1": "youtube.com/shorts"})
        core.set_shorts_block(False)
        with winreg.OpenKey(core._policy_hive(), core._policy_path(CHROME)) as k:
            self.assertEqual(winreg.QueryValueEx(k, "9")[0], 5)

    def test_someone_elses_identical_pattern_is_not_duplicated(self):
        put(CHROME, "1", "youtube.com/shorts")
        core.set_shorts_block(True)
        self.assertEqual(core._policy_values(CHROME), {"1": "youtube.com/shorts"})


class RemovingIt(PolicyCase):
    def test_off_removes_the_block_everywhere(self):
        core.set_shorts_block(True)
        core.off()
        for sub, _p in core.POLICY_TARGETS:
            self.assertEqual(core._policy_values(sub), {}, sub)
        self.assertFalse(core.shorts_block_in_place())

    def test_off_also_clears_the_hosts_block(self):
        core.set_hosts_block(core.default_state(), True)
        core.off()
        self.assertNotIn(core.MARK_START, self.hosts())


class AlwaysOn(PolicyCase):
    def test_apply_enforcement_blocks_shorts_during_work_hours(self):
        core.apply_enforcement(core.default_state(), MORNING)
        self.assertTrue(core.shorts_block_in_place())

    def test_and_in_free_time_too(self):
        st = core.default_state()
        for when in (EVENING, NIGHT, SAT_LATE):
            wipe()
            self.assertFalse(core.sites_blocked(st, when), when)
            core.apply_enforcement(st, when)
            self.assertTrue(core.shorts_block_in_place(), when)

    def test_and_during_a_break(self):
        st = core.default_state()
        st["unlock_until"] = MORNING + 600
        core.apply_enforcement(st, MORNING + 1)
        self.assertTrue(core.shorts_block_in_place())

    def test_and_during_a_learning_break_and_audiobook_mode(self):
        st = core.default_state()
        st["learning_until"] = MORNING + 600
        st["learning_approved"] = [{"phrase": "dune audiobook", "added": MORNING - 99999, "always": True}]
        core.apply_enforcement(st, MORNING + 1)
        self.assertTrue(core.shorts_block_in_place())

    def test_a_removed_block_is_restored_on_the_next_enforcement(self):
        st = core.default_state()
        core.apply_enforcement(st, MORNING)
        wipe()
        core.apply_enforcement(st, MORNING + 3)
        self.assertTrue(core.shorts_block_in_place())

    def test_the_rest_of_youtube_is_unaffected(self):
        st = core.default_state()
        st["learning_until"] = MORNING + 600
        core.apply_enforcement(st, MORNING + 1)
        self.assertTrue(core.youtube_open(st, MORNING + 1))
        self.assertNotIn("youtube.com", core.effective_blocklist(st, MORNING + 1))
        self.assertNotIn("shorts", self.hosts())


class WhenItCannotWrite(PolicyCase):
    def test_no_admin_rights_is_reported_not_raised(self):
        with mock.patch.object(winreg, "CreateKeyEx", side_effect=PermissionError("denied")):
            self.assertFalse(core.set_shorts_block(True))
        self.assertFalse(core.shorts_block_in_place())

    def test_the_failure_is_logged_once_only(self):
        with mock.patch.object(winreg, "CreateKeyEx", side_effect=PermissionError("denied")), \
                mock.patch.object(core, "log_event") as log:
            for _ in range(4):
                core.set_shorts_block(True)
        self.assertEqual(log.call_count, 1)
        self.assertIn("could not set the Shorts block", log.call_args[0][0])

    def test_a_failure_does_not_stop_the_hosts_file_being_updated(self):
        with mock.patch.object(winreg, "CreateKeyEx", side_effect=PermissionError("denied")):
            core.apply_enforcement(core.default_state(), MORNING)
        self.assertIn(core.MARK_START, self.hosts())

    def test_one_browser_failing_does_not_stop_the_others(self):
        real = winreg.CreateKeyEx

        def flaky(hive, path, *a, **k):
            if "Edge" in path:
                raise PermissionError("denied")
            return real(hive, path, *a, **k)
        with mock.patch.object(winreg, "CreateKeyEx", flaky):
            self.assertFalse(core.set_shorts_block(True))
        self.assertIn("youtube.com/shorts", core._policy_values(CHROME).values())
        self.assertIn("youtube.com/shorts", core._policy_values(BRAVE).values())
        self.assertEqual(core._policy_values(EDGE), {})


class NotWindows(unittest.TestCase):
    def test_everything_is_a_quiet_no_op(self):
        with mock.patch.object(core, "IS_WIN", False):
            self.assertFalse(core.set_shorts_block(True))
            self.assertFalse(core.set_shorts_block(False))
            self.assertFalse(core.shorts_block_in_place())


if __name__ == "__main__":
    unittest.main()
