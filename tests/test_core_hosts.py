"""core: hosts-file editing (expand, strip, set/refresh/off, tamper healing, DNS flush)."""
import unittest
from unittest import mock

from support import IsolatedCore, MORNING
import core

USER_LINES = "127.0.0.1 localhost\n::1 localhost\n10.0.0.5 nas.home\n"


class Expand(unittest.TestCase):
    def test_adds_www_and_m_variants(self):
        self.assertEqual(core._expand(["a.com"]), ["a.com", "www.a.com", "m.a.com"])

    def test_dedupes_and_keeps_order(self):
        out = core._expand(["a.com", "www.a.com", "a.com"])
        self.assertEqual(len(out), len(set(out)))
        self.assertEqual(out[0], "a.com")

    def test_empty(self):
        self.assertEqual(core._expand([]), [])


class StripBlock(unittest.TestCase):
    def block(self, *entries):
        return "\n".join([core.MARK_START] + [f"0.0.0.0 {e}" for e in entries] + [core.MARK_END])

    def test_no_block_is_unchanged(self):
        self.assertEqual(core._strip_block(USER_LINES), USER_LINES)

    def test_removes_only_the_block(self):
        text = USER_LINES + self.block("a.com", "b.com") + "\n"
        out = core._strip_block(text)
        self.assertNotIn("a.com", out)
        self.assertNotIn(core.MARK_START, out)
        for line in USER_LINES.splitlines():
            self.assertIn(line, out)

    def test_block_in_the_middle_keeps_lines_after_it(self):
        text = "1.1.1.1 before\n" + self.block("a.com") + "\n2.2.2.2 after\n"
        out = core._strip_block(text)
        self.assertIn("1.1.1.1 before", out)
        self.assertIn("2.2.2.2 after", out)
        self.assertNotIn("a.com", out)

    def test_damaged_block_without_end_marker_only_drops_our_lines(self):
        text = "1.1.1.1 before\n" + core.MARK_START + "\n0.0.0.0 a.com\n0.0.0.0 b.com\n9.9.9.9 mine\n"
        out = core._strip_block(text)
        self.assertIn("9.9.9.9 mine", out)          # someone else's line survives
        self.assertIn("1.1.1.1 before", out)
        self.assertNotIn("a.com", out)

    def test_stray_end_marker_is_removed(self):
        out = core._strip_block("1.1.1.1 x\n" + core.MARK_END + "\n")
        self.assertNotIn(core.MARK_END, out)
        self.assertIn("1.1.1.1 x", out)

    def test_handles_crlf(self):
        text = USER_LINES.replace("\n", "\r\n") + self.block("a.com").replace("\n", "\r\n") + "\r\n"
        out = core._strip_block(text)
        self.assertNotIn("a.com", out)
        self.assertIn("nas.home", out)

    def test_no_trailing_blank_line_pileup(self):
        out = core._strip_block(USER_LINES + "\n\n" + self.block("a.com") + "\n\n\n")
        self.assertFalse(out.endswith("\n\n"))


class BlockText(IsolatedCore):
    def test_desired_block_shape(self):
        text = core._desired_block(self.state(blocklist=["a.com"]))
        self.assertEqual(text.splitlines(), [core.MARK_START, "0.0.0.0 a.com", "0.0.0.0 www.a.com",
                                             "0.0.0.0 m.a.com", core.MARK_END])
        self.assertTrue(text.endswith("\n"))

    def test_extract_block_roundtrip(self):
        st = self.state(blocklist=["a.com"])
        want = core._desired_block(st)
        self.assertEqual(core._extract_block(USER_LINES + want + "tail\n"), want)

    def test_extract_incomplete_block_is_empty(self):
        self.assertEqual(core._extract_block(core.MARK_START + "\n0.0.0.0 a.com\n"), "")
        self.assertEqual(core._extract_block(USER_LINES), "")


class SetHostsBlock(IsolatedCore):
    def test_block_and_unblock_preserve_user_lines(self):
        self.write_hosts(USER_LINES)
        st = self.state(blocklist=["a.com"])
        self.assertTrue(core.set_hosts_block(st, True))
        text = self.hosts()
        self.assertIn("0.0.0.0 www.a.com", text)
        for line in USER_LINES.splitlines():
            self.assertIn(line, text)
        self.assertTrue(core.set_hosts_block(st, False))
        self.assertEqual(self.hosts().strip(), USER_LINES.strip())

    def test_idempotent(self):
        st = self.state()
        self.assertTrue(core.set_hosts_block(st, True))
        self.assertFalse(core.set_hosts_block(st, True))
        self.assertTrue(core.set_hosts_block(st, False))
        self.assertFalse(core.set_hosts_block(st, False))

    def test_flushes_dns_only_on_a_real_change(self):
        st = self.state()
        with mock.patch.object(core, "flush_dns") as f:
            core.set_hosts_block(st, True)
            core.set_hosts_block(st, True)
            core.set_hosts_block(st, False)
            core.set_hosts_block(st, False)
            self.assertEqual(f.call_count, 2)

    def test_write_failure_reports_no_change_and_no_flush(self):
        with mock.patch.object(core, "_write_hosts", return_value=False), \
                mock.patch.object(core, "flush_dns") as f:
            self.assertFalse(core.set_hosts_block(self.state(), True))
            f.assert_not_called()

    def test_heals_a_block_someone_edited(self):
        st = self.state(blocklist=["a.com"])
        core.set_hosts_block(st, True)
        tampered = self.hosts().replace("0.0.0.0 a.com\n", "")       # delete one line, keep markers
        self.write_hosts(tampered)
        self.assertNotIn("0.0.0.0 a.com\n", self.hosts())
        self.assertTrue(core.set_hosts_block(st, True))
        self.assertIn("0.0.0.0 a.com\n", self.hosts())
        self.assertEqual(self.hosts().count(core.MARK_START), 1)

    def test_picks_up_a_grown_blocklist_without_a_manual_refresh(self):
        st = self.state(blocklist=["a.com"])
        core.set_hosts_block(st, True)
        st["blocklist"] = ["a.com", "b.com"]
        self.assertTrue(core.set_hosts_block(st, True))
        self.assertIn("0.0.0.0 b.com", self.hosts())
        self.assertEqual(self.hosts().count(core.MARK_START), 1)

    def test_recovers_from_a_half_written_block(self):
        self.write_hosts(USER_LINES + core.MARK_START + "\n0.0.0.0 old.com\n")   # no END marker
        self.assertTrue(core.set_hosts_block(self.state(blocklist=["a.com"]), True))
        text = self.hosts()
        self.assertEqual(text.count(core.MARK_START), 1)
        self.assertEqual(text.count(core.MARK_END), 1)
        self.assertNotIn("old.com", text)
        self.assertIn("nas.home", text)

    def test_unblock_when_only_a_stray_marker_remains(self):
        self.write_hosts(USER_LINES + core.MARK_START + "\n")
        self.assertTrue(core.set_hosts_block(self.state(), False))
        self.assertNotIn(core.MARK_START, self.hosts())

    def test_missing_hosts_file_is_created(self):
        import os
        os.remove(core.HOSTS_PATH)
        self.assertTrue(core.set_hosts_block(self.state(blocklist=["a.com"]), True))
        self.assertIn("0.0.0.0 a.com", self.hosts())

    def test_empty_blocklist_still_valid(self):
        self.assertTrue(core.set_hosts_block(self.state(blocklist=[]), True))
        self.assertFalse(core.set_hosts_block(self.state(blocklist=[]), True))

    def test_crlf_hosts_file(self):
        self.write_hosts(USER_LINES.replace("\n", "\r\n"))
        st = self.state(blocklist=["a.com"])
        core.set_hosts_block(st, True)
        core.set_hosts_block(st, False)
        self.assertIn("nas.home", self.hosts())
        self.assertNotIn("a.com", self.hosts())


class RefreshAndOff(IsolatedCore):
    def test_refresh_forces_the_block(self):
        st = self.state(blocklist=["a.com"])
        self.assertTrue(core.refresh_hosts_block(st))
        self.assertIn("0.0.0.0 a.com", self.hosts())
        self.assertFalse(core.refresh_hosts_block(st))       # already correct

    def test_off_removes_the_block(self):
        core.set_hosts_block(self.state(), True)
        self.assertTrue(core.off())
        self.assertNotIn(core.MARK_START, self.hosts())
        self.assertFalse(core.off())                         # nothing left to do


class ReadWriteHosts(IsolatedCore):
    def test_read_missing_returns_empty(self):
        import os
        os.remove(core.HOSTS_PATH)
        self.assertEqual(core._read_hosts(), "")

    def test_write_then_read(self):
        self.assertTrue(core._write_hosts("x y\n"))
        self.assertEqual(core._read_hosts(), "x y\n")

    def test_write_to_unwritable_path_is_false(self):
        core.HOSTS_PATH = self.tmp        # a directory: open() for writing fails
        self.assertFalse(core._write_hosts("x"))


class FlushDns(unittest.TestCase):
    def test_windows_prefers_in_process_call(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch.object(core, "IS_MAC", False), \
                mock.patch("subprocess.run") as run:
            fake = mock.MagicMock()
            fake.windll.dnsapi.DnsFlushResolverCache.return_value = 1
            with mock.patch.object(core, "ctypes", fake, create=True):
                core.flush_dns()
            run.assert_not_called()

    def test_windows_falls_back_to_ipconfig(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch.object(core, "IS_MAC", False), \
                mock.patch("subprocess.run") as run:
            fake = mock.MagicMock()
            fake.windll.dnsapi.DnsFlushResolverCache.side_effect = OSError("no dnsapi")
            with mock.patch.object(core, "ctypes", fake, create=True):
                core.flush_dns()
            self.assertEqual(run.call_args[0][0][0], "ipconfig")

    def test_mac_and_linux_commands(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", True), \
                mock.patch("subprocess.run") as run:
            core.flush_dns()
            self.assertEqual([c[0][0][0] for c in run.call_args_list], ["dscacheutil", "killall"])
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", False), \
                mock.patch("subprocess.run") as run:
            core.flush_dns()
            self.assertEqual(run.call_args[0][0][0], "resolvectl")

    def test_never_raises(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", False), \
                mock.patch("subprocess.run", side_effect=FileNotFoundError):
            core.flush_dns()


if __name__ == "__main__":
    unittest.main()
