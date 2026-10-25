"""focusapp: module-level helpers (no windows): audio, alarm, hooks, foreground, formatting."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

from support import ROOT
import core
import focusapp as fa

WIN = core.IS_WIN


class Fmt(unittest.TestCase):
    def test_minutes_seconds(self):
        self.assertEqual(fa.fmt(0), "00:00")
        self.assertEqual(fa.fmt(5), "00:05")
        self.assertEqual(fa.fmt(65), "01:05")
        self.assertEqual(fa.fmt(45 * 60), "45:00")
        self.assertEqual(fa.fmt(3599), "59:59")

    def test_hours(self):
        self.assertEqual(fa.fmt(3600), "1:00:00")
        self.assertEqual(fa.fmt(3661), "1:01:01")
        self.assertEqual(fa.fmt(10 * 3600 + 5), "10:00:05")

    def test_negative_and_float_inputs(self):
        self.assertEqual(fa.fmt(-30), "00:00")
        self.assertEqual(fa.fmt(59.9), "00:59")
        self.assertEqual(fa.fmt(0.4), "00:00")


class BrowserNames(unittest.TestCase):
    def test_browser_set(self):
        for b in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "opera_gx.exe"):
            self.assertIn(b, fa.BROWSERS)
        self.assertNotIn("spotify.exe", fa.BROWSERS)


class PsQuote(unittest.TestCase):
    def test_straight_and_curly_quotes_are_doubled(self):
        self.assertEqual(fa._ps_quote("it's"), "it''s")
        self.assertEqual(fa._ps_quote("don’t"), "don’’t")
        self.assertEqual(fa._ps_quote("‘x’"), "‘‘x’’")
        self.assertEqual(fa._ps_quote("plain"), "plain")
        self.assertEqual(fa._ps_quote(""), "")

    def test_injection_attempt_stays_inside_the_string(self):
        evil = "'; Remove-Item C:\\ -Recurse; '"
        quoted = fa._ps_quote(evil)
        # every single quote is doubled, so none can terminate the literal early
        self.assertEqual(quoted.count("'"), 2 * evil.count("'"))


class AudioSlots(unittest.TestCase):
    def setUp(self):
        fa._audio_procs.clear()

    tearDown = setUp

    def proc(self, running=True):
        p = mock.Mock()
        p.poll.return_value = None if running else 0
        return p

    def test_prunes_finished_processes(self):
        fa._audio_procs.extend([self.proc(False), self.proc(True)])
        fa._prune_audio()
        self.assertEqual(len(fa._audio_procs), 1)

    def test_cap(self):
        for _ in range(fa.MAX_CONCURRENT_AUDIO):
            fa._register_audio(self.proc(True))
        self.assertFalse(fa._audio_slot_free())
        fa._audio_procs[0].poll.return_value = 0          # one finishes
        self.assertTrue(fa._audio_slot_free())

    def test_stop_speech_terminates_everything(self):
        procs = [self.proc(True) for _ in range(3)]
        fa._audio_procs.extend(procs)
        fa.stop_speech()
        for p in procs:
            p.terminate.assert_called_once()
        self.assertEqual(fa._audio_procs, [])

    def test_stop_speech_survives_a_failing_terminate(self):
        p = self.proc(True)
        p.terminate.side_effect = OSError
        fa._audio_procs.append(p)
        fa.stop_speech()
        self.assertEqual(fa._audio_procs, [])


class Say(unittest.TestCase):
    def setUp(self):
        fa._audio_procs.clear()

    tearDown = setUp

    def test_windows_command_quotes_text_and_voice(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.Popen") as popen:
            fa.say("don't stop", voice="Bob's Voice", rate=2)
            fa.drain_audio()
        script = popen.call_args[0][0][-1]
        self.assertIn("$s.Speak('don''t stop')", script)
        self.assertIn("SelectVoice('Bob''s Voice')", script)
        self.assertIn("$s.Rate=2", script)

    def test_no_voice_means_no_selectvoice(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.Popen") as popen:
            fa.say("hi")
            fa.drain_audio()
        self.assertNotIn("SelectVoice", popen.call_args[0][0][-1])

    def test_empty_text_is_ignored(self):
        with mock.patch("subprocess.Popen") as popen:
            fa.say("")
            fa.say(None)
        popen.assert_not_called()

    def test_respects_the_concurrency_cap(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.Popen") as popen:
            popen.return_value.poll.return_value = None
            for _ in range(fa.MAX_CONCURRENT_AUDIO + 10):
                fa.say("x")
                fa.drain_audio()          # let each launch finish so the next sees the real slot count
        self.assertEqual(popen.call_count, fa.MAX_CONCURRENT_AUDIO)

    def test_mac_and_linux_commands(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", True), \
                mock.patch("subprocess.Popen") as popen:
            fa.say("hello")
            fa.drain_audio()
            self.assertEqual(popen.call_args[0][0], ["say", "hello"])
        fa._audio_procs.clear()
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", False), \
                mock.patch("subprocess.Popen") as popen:
            fa.say("hello")
            fa.drain_audio()
            self.assertEqual(popen.call_args[0][0], ["spd-say", "hello"])

    def test_spawn_failure_is_swallowed(self):
        with mock.patch("subprocess.Popen", side_effect=OSError):
            fa.say("hello")
            self.assertTrue(fa.drain_audio())
        with mock.patch("subprocess.Popen") as popen:        # and the audio thread keeps working afterwards
            fa.say("again")
            fa.drain_audio()
            popen.assert_called_once()

    def test_say_returns_immediately_even_if_launching_is_slow(self):
        """The whole point of the audio thread: the caller (the window) never waits for a launch."""
        started, release = threading.Event(), threading.Event()

        def slow_popen(*a, **k):
            started.set()
            release.wait(3)
            return mock.Mock(poll=lambda: None)
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.Popen", side_effect=slow_popen):
            t = time.perf_counter()
            fa.say("one"); fa.say("two"); fa.say("three")
            self.assertLess(time.perf_counter() - t, 0.2)
            self.assertTrue(started.wait(2))
            release.set()
            fa.drain_audio()

    def test_a_full_queue_drops_sounds_instead_of_blocking(self):
        gate = threading.Event()
        ran = []
        with mock.patch.object(core, "IS_WIN", True), \
                mock.patch.object(fa, "_audio_slot_free", lambda: True):
            fa._enqueue_audio(lambda: gate.wait(3))           # occupies the worker
            time.sleep(0.05)
            t = time.perf_counter()
            for i in range(fa.AUDIO_QUEUE_MAX + 20):
                fa._enqueue_audio(lambda i=i: ran.append(i))
            self.assertLess(time.perf_counter() - t, 0.2)     # never blocked, even though it overflowed
            gate.set()
            fa.drain_audio()
        self.assertEqual(len(ran), fa.AUDIO_QUEUE_MAX)         # the overflow was dropped

    def test_stop_speech_discards_sounds_that_have_not_started(self):
        gate = threading.Event()
        ran = []
        with mock.patch.object(fa, "_audio_slot_free", lambda: True):
            fa._enqueue_audio(lambda: gate.wait(3))
            time.sleep(0.05)
            for i in range(3):
                fa._enqueue_audio(lambda i=i: ran.append(i))
            fa.stop_speech()
            gate.set()
            fa.drain_audio()
        self.assertEqual(ran, [])

    def test_a_failing_job_does_not_kill_the_audio_thread(self):
        ran = []
        with mock.patch.object(fa, "_audio_slot_free", lambda: True):
            fa._enqueue_audio(lambda: 1 / 0)
            fa._enqueue_audio(lambda: ran.append("ok"))
            fa.drain_audio()
        self.assertEqual(ran, ["ok"])

    def test_overlap_fires_n_voices(self):
        with mock.patch.object(fa, "say") as say:
            fa.say_overlap(["a", "b"], 3)
            self.assertEqual(say.call_count, 3)
            voices = [c[0][1] for c in say.call_args_list]
            self.assertEqual(voices, fa.VOICES[:3])

    def test_overlap_uses_the_chosen_voice_for_all(self):
        with mock.patch.object(fa, "say") as say:
            fa.say_overlap(["a"], 3, voice="Zira")
            self.assertTrue(all(c[0][1] == "Zira" for c in say.call_args_list))

    def test_overlap_with_no_lines_is_a_noop(self):
        with mock.patch.object(fa, "say") as say:
            fa.say_overlap([], 3)
            say.assert_not_called()

    def test_overlap_minimum_one_voice(self):
        with mock.patch.object(fa, "say") as say:
            fa.say_overlap(["a"], 0)
            self.assertEqual(say.call_count, 1)


class ListVoices(unittest.TestCase):
    def test_parses_output(self):
        out = mock.Mock(stdout="Microsoft Zira Desktop\r\n\r\n  Microsoft David Desktop \r\n")
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.run", return_value=out):
            self.assertEqual(fa.list_voices(),
                             ["Microsoft Zira Desktop", "Microsoft David Desktop"])

    def test_failure_and_non_windows_give_empty(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.run", side_effect=OSError):
            self.assertEqual(fa.list_voices(), [])
        with mock.patch.object(core, "IS_WIN", False):
            self.assertEqual(fa.list_voices(), [])


class Beep(unittest.TestCase):
    def test_a_failing_beep_still_takes_its_time(self):
        """No sound device must not turn the alarm threads into a 100% CPU spin loop."""
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", False), \
                mock.patch("subprocess.run", side_effect=FileNotFoundError):
            t = time.perf_counter()
            fa._platform_beep(440, 150)
            self.assertGreaterEqual(time.perf_counter() - t, 0.14)

    @unittest.skipUnless(WIN, "winsound")
    def test_windows_clamps_frequency(self):
        import winsound
        with mock.patch.object(winsound, "Beep") as beep:
            fa._platform_beep(5, 1)
            fa._platform_beep(999999, 1)
            fa._platform_beep(880, 1)
        self.assertEqual([c[0][0] for c in beep.call_args_list], [37, 32767, 880])

    def test_mac_plays_a_system_sound(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", True), \
                mock.patch("subprocess.run") as run:
            fa._platform_beep(440, 1)
            self.assertEqual(run.call_args[0][0][0], "afplay")

    def test_linux_falls_back_from_paplay_to_aplay(self):
        calls = []
        def run(cmd, **k):
            calls.append(cmd[0])
            if cmd[0] == "paplay":
                raise FileNotFoundError
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", False), \
                mock.patch("subprocess.run", side_effect=run):
            fa._platform_beep(440, 1)
        self.assertEqual(calls, ["paplay", "aplay"])

    def test_beeps_runs_count_times_in_the_background(self):
        seen = []
        with mock.patch.object(fa, "_platform_beep", side_effect=lambda f, d: seen.append((f, d))):
            fa.beeps(3, 700, 10)
            deadline = time.time() + 2
            while len(seen) < 3 and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(seen, [(700, 10)] * 3)

    def test_chime_never_raises(self):
        with mock.patch.object(fa, "_platform_beep"):
            fa.play_chime()
            time.sleep(0.05)


class Alarm(unittest.TestCase):
    def setUp(self):
        self.beeps = []
        self.lock = threading.Lock()
        def fake_beep(freq, dur):
            with self.lock:
                self.beeps.append((freq, dur))
            time.sleep(0.02)
        self.patch = mock.patch.object(fa.Alarm, "_beep", staticmethod(fake_beep))
        self.patch.start()
        self.alarm = fa.Alarm()

    def tearDown(self):
        self.alarm.close()
        time.sleep(0.2)
        self.patch.stop()

    def test_close_ends_every_thread_it_started(self):
        self.alarm.set_level(5)
        time.sleep(0.2)
        mine = [self.alarm._thread] + self.alarm._chord_threads
        self.assertTrue(all(t.is_alive() for t in mine))
        self.alarm.close()
        deadline = time.time() + 3
        while any(t.is_alive() for t in mine) and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(any(t.is_alive() for t in mine))

    def test_a_closed_alarm_stays_silent(self):
        self.alarm.close()
        self.alarm.set_level(5)
        time.sleep(0.3)
        self.assertEqual(self.beeps, [])

    def test_idle_chord_voices_do_not_poll(self):
        """They used to wake ten times a second each, forever, even when nothing was sounding."""
        self.alarm.set_level(2)                              # starts the threads, but below the cluster level
        time.sleep(0.3)
        self.beeps.clear()
        wakeups = []
        orig = self.alarm._high.wait

        def counting_wait(timeout=None):
            wakeups.append(timeout)
            return orig(timeout)
        self.alarm._high.wait = counting_wait
        time.sleep(1.5)
        self.assertLessEqual(len(wakeups), 3 * 3)            # each of the 3 voices wakes about once a second at most

    def test_the_cluster_only_sounds_at_the_top_levels(self):
        self.alarm.set_level(3)
        time.sleep(0.4)
        low = len(self.beeps)
        self.alarm.set_level(5)
        time.sleep(0.4)
        high = len(self.beeps) - low
        self.assertGreater(high, low)                        # the extra voices joined in
        self.alarm.set_level(3)
        time.sleep(0.4)                                      # let them settle
        before = len(self.beeps)
        time.sleep(0.5)
        calm = len(self.beeps) - before
        self.assertLess(calm, high)                          # and left again when the level dropped

    def test_starts_idle(self):
        self.assertEqual(self.alarm.level, -1)
        time.sleep(0.1)
        self.assertEqual(self.beeps, [])

    def test_beeps_once_a_level_is_set_and_stops_when_cleared(self):
        self.alarm.set_level(0)
        time.sleep(0.4)
        self.assertGreater(len(self.beeps), 0)
        self.alarm.stop()
        time.sleep(1.3)
        n = len(self.beeps)
        time.sleep(0.5)
        self.assertEqual(len(self.beeps), n)

    def test_thread_count_is_bounded(self):
        before = threading.active_count()
        for lvl in (0, 1, 2, 3, 4, 5, 5, 5):
            self.alarm.set_level(lvl)
            time.sleep(0.05)
        self.assertLessEqual(threading.active_count() - before, 1 + fa.Alarm.CHORD_VOICES)

    def test_high_levels_use_the_extra_voices(self):
        self.alarm.set_level(5)
        time.sleep(0.5)
        self.assertGreater(len(self.beeps), 5)

    def test_tone_durations_grow_with_level(self):
        self.alarm.set_level(4)
        time.sleep(0.3)
        self.assertTrue(all(dur >= 110 + 4 * 25 for _f, dur in self.beeps))

    def test_restart_after_stop(self):
        self.alarm.set_level(1); time.sleep(0.3); self.alarm.stop(); time.sleep(1.4)
        n = len(self.beeps)
        self.alarm.set_level(1); time.sleep(0.4)
        self.assertGreater(len(self.beeps), n)

    def test_speed_setting_is_clamped(self):
        self.alarm.speed = 99
        self.alarm.set_level(2)
        time.sleep(0.3)
        self.alarm.speed = -5
        time.sleep(0.3)
        self.assertGreater(len(self.beeps), 0)


class CustomSounds(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.patch = mock.patch.object(fa, "SOUNDS_DIR", self.dir)
        self.patch.start()
        fa._audio_procs.clear()

    def tearDown(self):
        import shutil
        self.patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
        fa._audio_procs.clear()

    def touch(self, name):
        p = os.path.join(self.dir, name)
        open(p, "wb").close()
        return p

    def test_lists_only_wav_files_case_insensitively(self):
        a, b = self.touch("a.wav"), self.touch("B.WAV")
        self.touch("notes.txt")
        self.assertEqual(sorted(fa.list_customs()), sorted([a, b]))

    def test_missing_folder_is_empty(self):
        with mock.patch.object(fa, "SOUNDS_DIR", os.path.join(self.dir, "nope")):
            self.assertEqual(fa.list_customs(), [])

    def test_play_returns_false_without_files(self):
        self.assertFalse(fa.play_custom_overlap(2))

    def test_plays_up_to_n_recordings(self):
        for i in range(5):
            self.touch(f"r{i}.wav")
        with mock.patch.object(fa, "_play_wav") as play:
            self.assertTrue(fa.play_custom_overlap(3))
            self.assertEqual(play.call_count, 3)
            self.assertEqual(len({c[0][0] for c in play.call_args_list}), 3)     # all different

    def test_n_is_at_least_one_and_at_most_the_number_of_files(self):
        self.touch("only.wav")
        with mock.patch.object(fa, "_play_wav") as play:
            fa.play_custom_overlap(0)
            fa.play_custom_overlap(9)
            self.assertEqual(play.call_count, 2)

    def test_windows_playback_quotes_the_path(self):
        with mock.patch.object(core, "IS_WIN", True), mock.patch("subprocess.Popen") as popen:
            fa._play_wav(r"C:\my sounds\it's.wav")
            fa.drain_audio()
        self.assertIn("it''s.wav", popen.call_args[0][0][-1])
        self.assertIn("PlaySync", popen.call_args[0][0][-1])

    def test_playback_respects_the_cap_and_errors(self):
        with mock.patch("subprocess.Popen", side_effect=OSError):
            fa._play_wav("x.wav")
            fa.drain_audio()
        with mock.patch("subprocess.Popen") as popen:
            popen.return_value.poll.return_value = None
            for _ in range(fa.MAX_CONCURRENT_AUDIO + 5):
                fa._play_wav("x.wav")
                fa.drain_audio()
            self.assertEqual(popen.call_count, fa.MAX_CONCURRENT_AUDIO)

    def test_mac_and_linux_players(self):
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", True), \
                mock.patch("subprocess.Popen") as popen:
            fa._play_wav("x.wav")
            fa.drain_audio()
            self.assertEqual(popen.call_args[0][0][0], "afplay")
        fa._audio_procs.clear()
        with mock.patch.object(core, "IS_WIN", False), mock.patch.object(core, "IS_MAC", False), \
                mock.patch("subprocess.Popen") as popen:
            fa._play_wav("x.wav")
            fa.drain_audio()
            self.assertEqual(popen.call_args[0][0][0], "aplay")


class Recording(unittest.TestCase):
    def test_start_success_and_failure(self):
        with mock.patch.object(core, "IS_WIN", True), \
                mock.patch.object(fa, "_mci", return_value=(0, "")) as mci:
            self.assertTrue(fa.record_start())
            cmds = [c[0][0] for c in mci.call_args_list]
            self.assertTrue(any(c.startswith("open new type waveaudio") for c in cmds))
            self.assertTrue(any(c.startswith("record focusrec") for c in cmds))
        with mock.patch.object(core, "IS_WIN", True), mock.patch.object(fa, "_mci", return_value=(263, "")):
            self.assertFalse(fa.record_start())

    def test_not_available_off_windows(self):
        with mock.patch.object(core, "IS_WIN", False):
            self.assertFalse(fa.record_start())
            self.assertEqual(fa._mci("anything"), (-1, ""))

    def test_stop_save_needs_a_file_on_disk(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "rec.wav")
        with mock.patch.object(fa, "_mci", return_value=(0, "")):
            self.assertFalse(fa.record_stop_save(path))          # mci "saved" nothing
            open(path, "wb").close()
            self.assertTrue(fa.record_stop_save(path))
        with mock.patch.object(fa, "_mci", return_value=(1, "")):
            self.assertFalse(fa.record_stop_save(path))

    @unittest.skipUnless(WIN, "MCI")
    def test_mci_returns_error_code_for_a_bad_command(self):
        err, _ = fa._mci("this is not a command")
        self.assertNotEqual(err, 0)


@unittest.skipUnless(WIN, "global mouse hook")
class ScrollCounter(unittest.TestCase):
    def wait_for(self, cond, secs=2.0):
        end = time.time() + secs
        while time.time() < end and not cond():
            time.sleep(0.02)
        return cond()

    def test_hook_installs_counts_and_removes_itself(self):
        import ctypes
        sc = fa.ScrollCounter()
        sc.set_active(True)
        self.assertTrue(self.wait_for(lambda: sc._running and sc._tid))
        before = sc.count
        # a single injected event can be dropped when the machine is busy, so keep nudging the wheel
        for _ in range(8):
            ctypes.windll.user32.mouse_event(0x0800, 0, 0, 120, 0)     # one wheel notch
            if self.wait_for(lambda: sc.count > before, secs=0.4):
                break
        self.assertGreater(sc.count, before)
        sc.set_active(False)
        self.assertTrue(self.wait_for(lambda: not sc._running and sc._tid is None))
        before = sc.count
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, 120, 0)
        time.sleep(0.3)
        self.assertEqual(sc.count, before)                              # hook is gone

    def test_repeated_toggling_is_clean(self):
        sc = fa.ScrollCounter()
        for _ in range(4):
            sc.set_active(True)
            self.wait_for(lambda: sc._tid)
            sc.set_active(False)
            self.assertTrue(self.wait_for(lambda: not sc._running))

    def test_double_activation_makes_one_thread(self):
        sc = fa.ScrollCounter()
        n = threading.active_count()
        sc.set_active(True); sc.set_active(True); sc.set_active(True)
        self.wait_for(lambda: sc._tid)
        self.assertLessEqual(threading.active_count() - n, 1)
        sc.set_active(False)
        self.wait_for(lambda: not sc._running)

    def test_deactivating_when_idle_is_harmless(self):
        fa.ScrollCounter().set_active(False)

    def test_noop_off_windows(self):
        with mock.patch.object(core, "IS_WIN", False):
            sc = fa.ScrollCounter()
            sc.set_active(True)
            self.assertFalse(sc._running)


class Foreground(unittest.TestCase):
    def test_returns_a_lowercase_pair(self):
        proc, title = fa.foreground_raw()
        self.assertIsInstance(proc, str)
        self.assertIsInstance(title, str)
        self.assertEqual(proc, proc.lower())
        self.assertEqual(title, title.lower())

    def test_empty_off_windows(self):
        with mock.patch.object(core, "IS_WIN", False):
            self.assertEqual(fa.foreground_raw(), ("", ""))

    def test_errors_give_empty(self):
        if not WIN:
            self.skipTest("Windows only")
        with mock.patch.object(fa, "user32") as u:
            u.GetForegroundWindow.side_effect = OSError
            self.assertEqual(fa.foreground_raw(), ("", ""))
            u.GetForegroundWindow.side_effect = None
            u.GetForegroundWindow.return_value = 0
            self.assertEqual(fa.foreground_raw(), ("", ""))

    def test_pid_cache(self):
        fa._PID_CACHE.clear()
        with mock.patch.object(fa, "_pid_name_uncached", return_value="x.exe") as raw:
            self.assertEqual(fa._pid_name(4242), "x.exe")
            self.assertEqual(fa._pid_name(4242), "x.exe")
            self.assertEqual(raw.call_count, 1)
            fa._PID_CACHE[4242] = ("x.exe", time.time() - 31)             # expired
            fa._pid_name(4242)
            self.assertEqual(raw.call_count, 2)

    def test_pid_cache_is_bounded(self):
        fa._PID_CACHE.clear()
        with mock.patch.object(fa, "_pid_name_uncached", return_value="p"):
            for pid in range(600):
                fa._pid_name(pid)
        self.assertLessEqual(len(fa._PID_CACHE), 257)

    @unittest.skipUnless(WIN, "process query")
    def test_pid_name_of_this_process(self):
        name = fa._pid_name_uncached(os.getpid()).lower()
        self.assertTrue(name.startswith("python"), name)
        self.assertEqual(fa._pid_name_uncached(0), "")

    def test_send_ctrl_w_presses_ctrl_and_w(self):
        if not WIN:
            self.skipTest("Windows only")
        with mock.patch.object(fa, "user32") as u:
            fa.send_ctrl_w()
        keys = [(c[0][0], c[0][2]) for c in u.keybd_event.call_args_list]
        self.assertEqual(keys, [(0x11, 0), (0x57, 0), (0x57, 2), (0x11, 2)])

    def test_send_ctrl_w_noop_off_windows(self):
        with mock.patch.object(core, "IS_WIN", False):
            fa.send_ctrl_w()


class ThreadDump(unittest.TestCase):
    def test_the_main_thread_always_comes_first(self):
        stop = threading.Event()
        threads = [threading.Thread(target=stop.wait, name=f"aaa-{i}", daemon=True) for i in range(5)]
        [t.start() for t in threads]
        try:
            dump = fa.dump_threads()
        finally:
            stop.set()
        self.assertTrue(dump.startswith("--- thread MainThread"), dump[:80])

    def test_threads_parked_on_the_same_line_are_merged(self):
        stop = threading.Event()
        threads = [threading.Thread(target=stop.wait, name=f"idle-{i}", daemon=True) for i in range(30)]
        [t.start() for t in threads]
        try:
            dump = fa.dump_threads()
        finally:
            stop.set()
        self.assertIn("--- 30 threads (", dump)
        self.assertEqual(dump.count("--- thread idle-"), 0)               # not listed 30 separate times
        self.assertLess(len(dump), 8000)          # 30 separate listings would be tens of thousands of characters

    def test_a_pile_of_threads_cannot_push_the_main_thread_out(self):
        stop = threading.Event()
        threads = []
        for i in range(200):
            t = threading.Thread(target=lambda i=i: stop.wait(5 + i * 0.0), name=f"t{i}", daemon=True)
            t.start()
            threads.append(t)
        try:
            dump = fa.dump_threads(limit=600)
        finally:
            stop.set()
        self.assertIn("MainThread", dump)
        self.assertLessEqual(len(dump), 600)


class ImportSafety(unittest.TestCase):
    def test_missing_toolkit_is_not_pip_installed_unless_asked(self):
        real_import = __import__
        def no_ctk(name, *a, **k):
            if name == "customtkinter":
                raise ImportError(name)
            return real_import(name, *a, **k)
        with mock.patch("builtins.__import__", side_effect=no_ctk), mock.patch("subprocess.run") as run:
            self.assertFalse(fa._ensure_ctk(install=False))
            run.assert_not_called()

    def test_install_path_runs_pip_once_and_reports_failure(self):
        real_import = __import__
        def no_ctk(name, *a, **k):
            if name == "customtkinter":
                raise ImportError(name)
            return real_import(name, *a, **k)
        with mock.patch("builtins.__import__", side_effect=no_ctk), mock.patch("subprocess.run") as run:
            self.assertFalse(fa._ensure_ctk(install=True))
            self.assertEqual(run.call_count, 1)
            self.assertIn("pip", run.call_args[0][0])

    def test_module_only_installs_when_run_as_the_app(self):
        with open(fa.__file__, encoding="utf-8") as f:
            self.assertIn('_ensure_ctk(install=(__name__ == "__main__"))', f.read())


if __name__ == "__main__":
    unittest.main()
