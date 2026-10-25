"""
Focus - an always-on study lockout app (Windows first; macOS/Linux run with sudo).

During your scheduled hours distraction sites are blocked and game launchers are closed.
The only way to get free time inside those hours is an actual break:
  * EARN  : finish a study session -> +15 min in your Time Bank (spend it anytime).
  * CHEAT : five 5-minute breaks a day; finishing a session gives them all back.
  * CODE  : guess a hidden 3-digit code (re-rolls on every miss) -> a break until midnight.
  * GAMES : a separate 30-minute gaming break with a cooldown.
Nuclear lockdown disables every escape for a chosen time. Breaks are refused during a
study session, and can't be stacked or used to shorten a lockdown.

UI: renders with customtkinter (modern, rounded) when available, and falls back to plain
tkinter if not. It tries to pip-install customtkinter on first launch.
"""

import os
import sys
import time
import queue
import random
import ctypes
import threading
import traceback
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core
import tutorial

# Windows-only input/foreground APIs — guarded so the app still imports on Mac/Linux
if core.IS_WIN:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
else:
    wintypes = None
    user32 = kernel32 = None

import tkinter as tk
from tkinter import ttk


# ----------------------------- optional modern toolkit -----------------------------
def _ensure_ctk(install=True):
    try:
        import customtkinter  # noqa
        return True
    except Exception:
        pass
    if not install:
        return False
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "customtkinter"],
                       capture_output=True, creationflags=core.CREATE_NO_WINDOW, timeout=120)
        import customtkinter  # noqa
        return True
    except Exception:
        return False

HAVE_CTK = _ensure_ctk(install=(__name__ == "__main__"))
if HAVE_CTK:
    import customtkinter as ctk


# ----------------------------- palette (coolors lavender/navy set) -----------------------------
C = {
    "bg":     "#0b3948",
    "panel":  "#224a54",
    "panel2": "#17424e",
    "chip":   "#113e4b",
    "border": "#667d84",
    "muted":  "#acb0bd",
    "cyan":   "#d0cdd7",
    "green":  "#12c99a",
    "green2": "#0a8f6e",
    "text":   "#d9dbf1",
    "danger": "#ef6b6b",
    "gold":   "#f5c451",
}
KIND = {   # (fill, text, hover)
    "primary": (C["green"], "#04241d", C["green2"]),
    "sec":     (C["panel2"], C["text"], C["border"]),
    "ghost":   (C["panel"], C["cyan"], C["panel2"]),
    "danger":  (C["danger"], "#2a0d0d", "#c85555"),
    "gold":    (C["gold"], "#3a2c07", "#e0b342"),
}


# ----------------------------- widget factories -----------------------------
def mkfont(size, bold=False):
    if HAVE_CTK:
        return ctk.CTkFont(family="Segoe UI", size=size, weight="bold" if bold else "normal")
    return ("Segoe UI", size, "bold" if bold else "normal")

def WFrame(master, color=C["panel"], radius=16, border=0):
    if HAVE_CTK:
        return ctk.CTkFrame(master, fg_color=color, corner_radius=radius,
                            border_width=border, border_color=C["border"])
    return tk.Frame(master, bg=color, highlightbackground=C["border"], highlightthickness=border)

def WLabel(master, text="", size=12, bold=False, color=C["text"], bg=C["bg"], wrap=0):
    """`wrap` > 0 wraps the text at that many pixels (left-aligned), for paragraphs."""
    if HAVE_CTK:
        return ctk.CTkLabel(master, text=text, font=mkfont(size, bold), text_color=color,
                            wraplength=wrap, justify="left" if wrap else "center")
    return tk.Label(master, text=text, font=mkfont(size, bold), fg=color, bg=bg,
                    wraplength=wrap, justify="left" if wrap else "center")

LOGO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")

def WLogo(master, size, bg):
    """The StudyAnchor logo as a small label: the same artwork as the window icon, so every place the
    app shows its logo shows this one. The image is tied to the given window (never "whichever window
    tkinter calls the default") and pre-scaled for the screen's DPI. Falls back to the anchor symbol if the
    image can't be loaded."""
    try:
        try:
            from PIL import Image, ImageTk
        except ImportError:
            Image = ImageTk = None
        if ImageTk is not None:
            try:
                scale = float(master._get_widget_scaling())          # customtkinter's DPI factor (1.25 on many laptops)
            except Exception:
                scale = 1.0
            px = max(8, round(size * (scale or 1.0)))
            img = ImageTk.PhotoImage(Image.open(LOGO_FILE).convert("RGBA").resize((px, px), Image.LANCZOS),
                                     master=master)
        else:                                                         # no Pillow: shrink the PNG by whole steps
            img = tk.PhotoImage(master=master, file=LOGO_FILE)
            img = img.subsample(max(1, round(img.width() / size)))
        lbl = tk.Label(master, image=img, bg=bg, bd=0, highlightthickness=0)
        lbl._logo = img                      # keep a reference so it isn't garbage-collected
        lbl.is_logo = True
        return lbl
    except Exception:
        return WLabel(master, "⚓", size=max(10, size // 2), color=C["green"], bg=bg)

def WButton(master, text, cmd, kind="primary", small=False, width=0):
    fill, fg, hover = KIND[kind]
    if HAVE_CTK:
        return ctk.CTkButton(master, text=text, command=cmd, fg_color=fill, hover_color=hover,
                             text_color=fg, corner_radius=11, font=mkfont(11 if small else 13, True),
                             height=30 if small else 40, width=width)
    return tk.Button(master, text=text, command=cmd, bg=fill, fg=fg, activebackground=hover,
                     activeforeground=fg, relief="flat", bd=0, cursor="hand2",
                     font=mkfont(9 if small else 10, True),
                     padx=8 if small else 12, pady=4 if small else 8)

def WEntry(master, width=8):
    if HAVE_CTK:
        return ctk.CTkEntry(master, width=width * 14, justify="center", fg_color=C["panel2"],
                            text_color=C["text"], border_color=C["border"], font=mkfont(14))
    return tk.Entry(master, width=width, justify="center", bg=C["panel2"], fg=C["text"],
                    insertbackground=C["text"], relief="flat", font=("Consolas", 13))

def WTextbox(master, height=7, width=40):
    if HAVE_CTK:
        return ctk.CTkTextbox(master, height=height * 20, width=width * 8, fg_color=C["panel2"],
                              text_color=C["text"], font=mkfont(11), corner_radius=8)
    return tk.Text(master, height=height, width=width, bg=C["panel2"], fg=C["text"],
                   insertbackground=C["text"], relief="flat", font=("Consolas", 10))

def WSlider(master, frm, to, var, command=None):
    if HAVE_CTK:
        return ctk.CTkSlider(master, from_=frm, to=to, number_of_steps=to - frm, variable=var,
                             command=command, progress_color=C["green"], button_color=C["cyan"],
                             fg_color=C["panel2"], width=180)
    return tk.Scale(master, from_=frm, to=to, orient="horizontal", variable=var,
                    command=command, bg=C["bg"], fg=C["text"], troughcolor=C["panel2"],
                    highlightthickness=0, showvalue=False, length=180, bd=0,
                    activebackground=C["cyan"])

def WAccent(master, color=C["green"], h=3):
    f = WFrame(master, color=color, radius=0)
    try:
        f.configure(height=h)
    except Exception:
        pass
    return f

def WOption(master, values, var):
    values = values or ["(default)"]
    if HAVE_CTK:
        return ctk.CTkOptionMenu(master, values=values, variable=var, fg_color=C["panel2"],
                                 button_color=C["green2"], button_hover_color=C["green"],
                                 text_color=C["text"], font=mkfont(10), dropdown_fg_color=C["panel"],
                                 dropdown_text_color=C["text"])
    om = tk.OptionMenu(master, var, *values)
    om.configure(bg=C["panel2"], fg=C["text"], activebackground=C["panel"], relief="flat",
                 highlightthickness=0, font=mkfont(9), bd=0)
    try:
        om["menu"].configure(bg=C["panel"], fg=C["text"])
    except Exception:
        pass
    return om

def WCheck(master, text, var):
    if HAVE_CTK:
        return ctk.CTkSwitch(master, text=text, variable=var, onvalue=1, offvalue=0,
                             progress_color=C["green"], text_color=C["text"], font=mkfont(11))
    return tk.Checkbutton(master, text=text, variable=var, bg=C["bg"], fg=C["text"],
                          selectcolor=C["panel2"], activebackground=C["bg"],
                          activeforeground=C["text"], font=mkfont(10))

def WToplevel(master):
    t = ctk.CTkToplevel(master) if HAVE_CTK else tk.Toplevel(master)
    try:
        t.configure(fg_color=C["bg"]) if HAVE_CTK else t.configure(bg=C["bg"])
    except Exception:
        pass
    return t

def set_label(w, text=None, color=None):
    kw = {}
    if text is not None:
        kw["text"] = text
    if color is not None:
        kw["text_color" if HAVE_CTK else "fg"] = color
    try:
        w.configure(**kw)
    except Exception:
        pass


# ----------------------------- win32 helpers -----------------------------

_PID_CACHE = {}

def _pid_name(pid):
    hit = _PID_CACHE.get(pid)
    if hit and time.time() - hit[1] < 30:
        return hit[0]
    name = _pid_name_uncached(pid)
    if len(_PID_CACHE) > 256:
        _PID_CACHE.clear()
    _PID_CACHE[pid] = (name, time.time())
    return name

def _pid_name_uncached(pid):
    try:
        h = kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        kernel32.CloseHandle(h)
        return os.path.basename(buf.value)
    except Exception:
        return ""

BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "opera_gx.exe"}

def foreground_raw():
    """Return (process_name_lower, window_title_lower) of the foreground window."""
    if not core.IS_WIN:
        return ("", "")   # reading the foreground window is Windows-only for now
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ("", "")
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = (buf.value or "").lower()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return (_pid_name(pid.value).lower(), title)
    except Exception:
        return ("", "")


# ---- global low-level mouse-wheel counter (for the doomscroll tax) ----
WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 0x020A
if core.IS_WIN:
    _HOOKPROC = ctypes.CFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

class ScrollCounter:
    """Counts mouse-wheel ticks via a global low-level hook. The hook runs Python code on
    EVERY mouse event system-wide, so it is only installed while it matters (a browser tab
    that looks like Shorts/Reels/TikTok is in front) and removed the rest of the time."""
    def __init__(self):
        self.count = 0
        self._proc = None
        self._tid = None
        self._running = False

    def set_active(self, on):
        if not core.IS_WIN:
            return
        if on and not self._running:
            self._running = True
            threading.Thread(target=self._run, daemon=True).start()
        elif not on and self._running and self._tid:
            user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)   # WM_QUIT -> _run unhooks and exits

    def _run(self):
        hook = None
        try:
            def cb(nCode, wParam, lParam):
                try:
                    if nCode >= 0 and wParam == WM_MOUSEWHEEL:
                        self.count += 1
                except Exception:
                    pass
                return user32.CallNextHookEx(None, nCode, wParam, lParam)
            self._proc = _HOOKPROC(cb)   # keep a ref so it isn't garbage-collected
            # explicit 64-bit-safe types: without them the module handle is truncated to 32 bits
            # and SetWindowsHookExW fails with ERROR_MOD_NOT_FOUND (126) on 64-bit Python
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc,
                                            kernel32.GetModuleHandleW(None), 0)
            if not hook:
                return
            msg = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)    # create this thread's message queue
            self._tid = kernel32.GetCurrentThreadId()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass
        finally:
            try:
                if hook:
                    user32.UnhookWindowsHookEx(hook)
            except Exception:
                pass
            self._tid = None
            self._running = False


def send_ctrl_w():
    """Send Ctrl+W to the foreground window (closes the active browser tab)."""
    if not core.IS_WIN:
        return
    try:
        VK_CONTROL, VK_W, KEYUP = 0x11, 0x57, 0x02
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_W, 0, 0, 0)
        user32.keybd_event(VK_W, 0, KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)
    except Exception:
        pass

# Browsers title their floating video window exactly this (Chrome/Edge/Brave/Opera: "Picture in
# picture"; Firefox: "Picture-in-Picture"). Exact match on purpose: a normal window whose tab is
# ABOUT picture-in-picture ends in " - Google Chrome" etc., so it can never equal this.
PIP_TITLES = {"picture in picture", "picture-in-picture"}
WM_CLOSE = 0x0010

def is_pip_title(title):
    return " ".join(str(title).lower().split()) in PIP_TITLES

def find_pip_windows():
    """Handles of visible browser Picture-in-Picture windows. Windows only. The cheap title test
    runs first so the process lookup only happens for the rare window that could be one."""
    if not core.IS_WIN:
        return []
    found = []
    try:
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _lparam):
            try:
                if user32.IsWindowVisible(hwnd):
                    n = user32.GetWindowTextLengthW(hwnd)
                    if 0 < n < 64:
                        buf = ctypes.create_unicode_buffer(n + 1)
                        user32.GetWindowTextW(hwnd, buf, n + 1)
                        if is_pip_title(buf.value):
                            pid = wintypes.DWORD()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            if _pid_name(pid.value).lower() in BROWSERS:
                                found.append(hwnd)
            except Exception:
                pass
            return True
        user32.EnumWindows(visit, 0)
    except Exception:
        return []
    return found

def close_window(hwnd):
    """Ask one specific window to close (WM_CLOSE). Targets the window itself, never the keyboard
    focus, so it cannot hit whatever else the user is typing into."""
    if not core.IS_WIN:
        return
    try:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    except Exception:
        pass

def _platform_beep(freq=880, dur_ms=200):
    """One beep/tone, cross-platform. Windows gets a real tone at the exact frequency
    via winsound. macOS/Linux can't easily do arbitrary-frequency tones without extra
    dependencies, so they play a short system sound instead — still audible feedback
    rather than silently doing nothing, which is what happened here before."""
    started = time.monotonic()
    try:
        if core.IS_WIN:
            import winsound
            winsound.Beep(max(37, min(int(freq), 32767)), max(1, int(dur_ms)))
        elif core.IS_MAC:
            subprocess.run(["afplay", "/System/Library/Sounds/Tink.aiff"],
                           capture_output=True, timeout=2)
        else:  # linux — try a couple of common system sound paths
            try:
                subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                               capture_output=True, timeout=2)
            except Exception:
                subprocess.run(["aplay", "-q", "/usr/share/sounds/alsa/Front_Center.wav"],
                               capture_output=True, timeout=2)
    except Exception:
        pass
    # A beep that failed instantly (no sound device / missing tool) must still take its time,
    # or the alarm threads that loop on it would spin at 100% CPU.
    remaining = dur_ms / 1000.0 - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)

def beeps(count, freq, dur):
    def run():
        for _ in range(count):
            _platform_beep(freq, dur)
    threading.Thread(target=run, daemon=True).start()

def play_chime():
    """A gentle rising arpeggio to reset the mind (works even without audio files)."""
    def run():
        try:
            if core.IS_WIN:
                import winsound
                for f, d in [(523, 260), (659, 260), (784, 260), (1047, 520)]:  # C E G C
                    winsound.Beep(f, d)
            else:
                _platform_beep()  # one system sound — the exact melody is Windows-only
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()

VOICES = [None, "Microsoft Zira Desktop", "Microsoft David Desktop", "Microsoft Hazel Desktop"]

_audio_procs = []
MAX_CONCURRENT_AUDIO = 3   # hard ceiling on simultaneous voice/sound subprocesses.
# Each of these is a whole new PowerShell process spinning up System.Speech (slow to
# start, ~0.3-0.8s of CPU). A sustained max-level nag used to keep 8 of them alive at all
# times for hours, which loads the whole machine and starves the window. Once at the ceiling,
# new voice/sound calls are simply skipped until a slot frees up.

AUDIO_QUEUE_MAX = 6
_audio_queue = queue.Queue(maxsize=AUDIO_QUEUE_MAX)
_audio_lock = threading.Lock()
_audio_thread = None

def _audio_worker():
    while True:
        job = _audio_queue.get()
        try:
            if job is None:
                return
            if _audio_slot_free():
                job()
        except Exception:
            pass
        finally:
            _audio_queue.task_done()

def _enqueue_audio(job):
    """Run `job` (which launches an audio subprocess) on the audio thread. Launching a process
    takes 20-30 ms or much more under load, so the window's own thread must never do it. If
    the queue is full the sound is dropped: a missed voice line is fine, a frozen window is not."""
    global _audio_thread
    with _audio_lock:
        if _audio_thread is None or not _audio_thread.is_alive():
            _audio_thread = threading.Thread(target=_audio_worker, daemon=True, name="focus-audio")
            _audio_thread.start()
    try:
        _audio_queue.put_nowait(job)
    except queue.Full:
        pass

def drain_audio(timeout=3.0):
    """Wait until every queued sound has been handed to the OS (used by tests and shutdown)."""
    deadline = time.monotonic() + timeout
    while _audio_queue.unfinished_tasks and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    return not _audio_queue.unfinished_tasks

def _spawn_audio(cmd):
    """Runs on the audio thread: start one speech/sound subprocess and track it."""
    try:
        p = subprocess.Popen(cmd, creationflags=core.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _register_audio(p)
    except Exception:
        pass

def _prune_audio():
    global _audio_procs
    _audio_procs = [p for p in _audio_procs if p.poll() is None]

def _register_audio(p):
    _prune_audio()   # do this first so the check below reflects reality
    _audio_procs.append(p)

def _audio_slot_free():
    _prune_audio()
    return len(_audio_procs) < MAX_CONCURRENT_AUDIO

def stop_speech():
    global _audio_procs
    try:                                   # drop anything still waiting to be launched
        while True:
            _audio_queue.get_nowait()
            _audio_queue.task_done()
    except queue.Empty:
        pass
    for p in list(_audio_procs):
        try:
            p.terminate()
        except Exception:
            pass
    _audio_procs = []

def _ps_quote(text):
    """Escape text for a PowerShell single-quoted string. PowerShell also treats the curly
    quotes (‘ ’ ‚ ‛) as quote characters, so a reminder like "don’t" must double those too."""
    return "".join(ch * 2 if ch in "'‘’‚‛" else ch for ch in str(text))

def say(text, voice=None, rate=0):
    if not text or not str(text).strip() or not _audio_slot_free():
        return
    if core.IS_WIN:
        ps = ("Add-Type -AssemblyName System.Speech;"
              "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              f"$s.Rate={int(rate)};")
        if voice:
            ps += f"try{{$s.SelectVoice('{_ps_quote(voice)}')}}catch{{}};"
        ps += f"$s.Speak('{_ps_quote(text)}')"
        cmd = ["powershell", "-NoProfile", "-Command", ps]
    elif core.IS_MAC:
        cmd = ["say", text]
    else:  # linux
        cmd = ["spd-say", text]
    _enqueue_audio(lambda: _spawn_audio(cmd))

def say_overlap(lines, n, voice=None):
    """Fire n TTS voices at once, overlapping, with different voices/rates -> chaos."""
    if not lines:
        return
    for i in range(max(1, n)):
        v = voice or VOICES[i % len(VOICES)]
        say(random.choice(lines), v, rate=random.choice([-1, 0, 2, 3]))

def list_voices():
    """Names of the installed Windows SAPI voices."""
    if not core.IS_WIN:
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech;"
             "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices()|"
             "%{$_.VoiceInfo.Name}"],
            capture_output=True, text=True, creationflags=core.CREATE_NO_WINDOW, timeout=8)
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


# ---- custom recordings: drop .wav files into the sounds/ folder ----
SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")

def list_customs():
    try:
        return [os.path.join(SOUNDS_DIR, f) for f in os.listdir(SOUNDS_DIR)
                if f.lower().endswith(".wav")]
    except Exception:
        return []

def _play_wav(path):
    if not _audio_slot_free():
        return
    if core.IS_WIN:
        cmd = ["powershell", "-NoProfile", "-Command",
               f"(New-Object System.Media.SoundPlayer '{_ps_quote(path)}').PlaySync()"]
    elif core.IS_MAC:
        cmd = ["afplay", path]
    else:
        cmd = ["aplay", path]
    _enqueue_audio(lambda: _spawn_audio(cmd))

def play_custom_overlap(n):
    """Play up to n custom recordings at once (separate processes -> they overlap)."""
    files = list_customs()
    if not files:
        return False
    random.shuffle(files)
    for path in files[:max(1, n)]:
        _play_wav(path)
    return True


# ---- microphone recording via the built-in Windows MCI (no extra installs) ----
def _mci(cmd):
    if not core.IS_WIN:
        return -1, ""
    try:
        buf = ctypes.create_unicode_buffer(256)
        err = ctypes.windll.winmm.mciSendStringW(cmd, buf, 256, None)
        return err, buf.value
    except Exception:
        return -1, ""

def record_start():
    if not core.IS_WIN:
        return False   # in-app recording is Windows-only (MCI)
    _mci("close focusrec")
    err, _ = _mci("open new type waveaudio alias focusrec")
    if err != 0:
        return False
    # 16-bit mono 22.05kHz — clean speech that System.Media.SoundPlayer can play back
    _mci("set focusrec bitspersample 16 channels 1 samplespersec 22050 alignment 2 bytespersec 44100")
    err, _ = _mci("record focusrec")
    return err == 0

def record_stop_save(path):
    _mci("stop focusrec")
    err, _ = _mci(f'save focusrec "{path}"')
    _mci("close focusrec")
    return err == 0 and os.path.exists(path)


class Alarm:
    """A continuous beeper: starts as slow pulses, accelerates with level, and at the top
    becomes a cluster of overlapping detuned tones (one dissonant wall of sound).

    Performance note: the dissonant cluster used to spawn a FRESH OS thread every
    20-140ms for as long as the alarm stayed escalated — over a sustained nag that's
    thousands of threads, which is exactly the kind of thing that makes an app go
    unresponsive. Instead, a small FIXED pool of persistent "chord voice" threads is
    started once and simply idles when not needed — the thread count never grows no
    matter how long the alarm runs.
    """
    TONES = [440, 466, 494, 415, 523, 370, 587]
    CHORD_VOICES = 3   # extra persistent threads for the dissonant cluster at high levels

    def __init__(self):
        self.level = -1
        self.speed = 3            # 1 (calm) .. 5 (relentless)
        self._thread = None
        self._chord_threads = []
        self._high = threading.Event()     # set while the dissonant cluster should be sounding
        self._closed = False

    def set_level(self, level):
        if self._closed:
            return
        self.level = level
        if level >= 4:
            self._high.set()
        else:
            self._high.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        while len(self._chord_threads) < self.CHORD_VOICES:
            t = threading.Thread(target=self._chord_voice, daemon=True)
            t.start()
            self._chord_threads.append(t)

    def stop(self):
        self.level = -1
        self._high.clear()

    def close(self):
        """End the alarm for good (app shutdown): lets the idle chord-voice threads exit."""
        self._closed = True
        self.level = -1
        self._high.set()                     # wake them so they notice and leave

    @staticmethod
    def _beep(freq, dur):
        _platform_beep(freq, dur)

    def _chord_voice(self):
        """One persistent extra voice for the cluster. It sleeps in the kernel (no polling) until
        the level reaches the top, so the total thread count for the whole alarm is fixed at
        1 + CHORD_VOICES, always, and an idle alarm costs nothing."""
        while not self._closed:
            if not self._high.wait(1.0):
                continue
            if self._closed:
                return
            if self.level >= 4:
                self._beep(random.choice(self.TONES), 110 + self.level * 25)
            else:
                time.sleep(0.05)             # level just dropped; don't spin until the event clears

    def _run(self):
        # gap between pulses shrinks as the level climbs; speed scales it further
        gaps = [1.0, 0.6, 0.35, 0.2]
        while self.level >= 0:
            lvl = self.level
            spd = max(1, min(int(self.speed), 5))
            sf = (6 - spd) / 3.0             # speed 3 -> 1.0, speed 5 -> 0.33, speed 1 -> 1.67
            dur = 110 + lvl * 25
            if lvl >= 4:
                # this thread supplies one tone; the persistent chord-voice threads
                # (started once in set_level) supply the rest of the cluster
                self._beep(random.choice(self.TONES), dur)
                time.sleep(max(0.06, (0.14 - (lvl - 4) * 0.06) * sf))
            else:
                self._beep(self.TONES[lvl % len(self.TONES)], dur)
                gap = gaps[min(lvl, len(gaps) - 1)] * sf
                slept = 0.0
                while slept < gap and self.level >= 0:
                    time.sleep(0.05); slept += 0.05

def fmt(sec):
    sec = max(0, int(sec))
    if sec >= 3600:
        return f"{sec // 3600}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"
    return f"{sec // 60:02d}:{sec % 60:02d}"


# ----------------------------- the obnoxious notifier -----------------------------
class Notifier:
    NAG_LINES = ["Back to work.", "Come on, focus.", "Stop slacking.",
                 "LOCK IN. NOW.", "SERIOUSLY. GET BACK TO IT.", "DO NOT LOOK AWAY."]
    # used only at the top "really mad" level: as firm as it gets, but never profane
    MAD_LINES = ["Get back to work. Right now.", "Stop wasting your time.",
                 "Put the phone down. Now.", "Enough. Open the book.",
                 "You said you would. Start studying."]

    STROBE = ["#ff0040", "#00e5ff", "#ffee00", "#ff00e5", "#00ff66", "#ffffff", "#ff6a00"]
    ACCENTS = ["#75dddd", "#f5c451", "#f59e0b", "#ef4444", "#ff2d55", "#ff0040"]
    ICONS = ["🔔", "⏰", "⚠", "🚨", "🔥", "💀"]
    CARD_BG = C["bg"]
    VOICE_MIN_GAP = 6.0        # seconds between voice/recording bursts, however fast the nag ticks
    DECOYS_PER_LEVEL = 2       # extra flashing 'FOCUS' boxes per level above 3

    def __init__(self, root):
        self.root = root
        self.win = None
        self.decoys = []
        self.flip = False
        self.level = -1
        self._styled_level = None  # the level the window's size/fonts were last set for
        self._shown = None         # (level, headline, subtext) last painted on the card
        self._strobe_delay = 0     # current (self-adjusting) strobe frame gap in ms
        self._strobe_due = None    # when the next strobe frame was supposed to run
        self._last_voice = -1e9    # when voices/recordings last fired
        self._strobe_job = None
        self._strobe_i = 0
        self.strobe_enabled = True
        self.max_voices = 4
        self.voice = None          # chosen Windows voice name (or None = default)
        self.nag_own = True        # nag with the user's own reminder lines
        self.own_lines = []
        self.on_start = None       # callback: start a study session (from the nag)
        self.on_snooze = None      # callback: snooze
        self.alarm = Alarm()

    def stop(self):
        self.alarm.stop()
        if self._strobe_job is not None:
            try:
                self.root.after_cancel(self._strobe_job)
            except Exception:
                pass
            self._strobe_job = None
        for w in [self.win] + self.decoys:
            try:
                if w:
                    w.destroy()
            except Exception:
                pass
        self.win = None
        self.decoys = []
        self.level = -1
        self._styled_level = None
        self._shown = None
        self._strobe_delay = 0
        self._strobe_due = None
        self._last_voice = -1e9

    def _accent(self, level):
        return self.ACCENTS[min(level, len(self.ACCENTS) - 1)]

    def _build_win(self):
        self.win = tk.Toplevel(self.root)
        self.win.configure(bg=self.CARD_BG)
        # deliberately NOT topmost — the alert shows without jumping to the very front
        self._top = tk.Frame(self.win, height=6, bg=self.CARD_BG); self._top.pack(fill="x", side="top")
        self._bot = tk.Frame(self.win, height=6, bg=self.CARD_BG); self._bot.pack(fill="x", side="bottom")
        self._inner = tk.Frame(self.win, bg=self.CARD_BG); self._inner.pack(expand=True, fill="both")
        self._icon = tk.Label(self._inner, bg=self.CARD_BG, font=("Segoe UI Emoji", 40))
        self._icon.pack(expand=True, pady=(16, 2))
        self._t = tk.Label(self._inner, bg=self.CARD_BG, fg="#ffffff", font=("Segoe UI Black", 26, "bold"))
        self._t.pack(expand=True)
        self._s = tk.Label(self._inner, bg=self.CARD_BG, fg=C["muted"], font=("Segoe UI", 13))
        self._s.pack(expand=True, pady=(2, 10))
        # action buttons so you can ALWAYS act on the nag (never get trapped)
        self._btns = tk.Frame(self._inner, bg=self.CARD_BG); self._btns.pack(expand=True, pady=(0, 16))
        self._start_btn = tk.Button(self._btns, text="▶  Start session", command=self._do_start,
                                    bg="#12c99a", fg="#04241d", activebackground="#0a8f6e",
                                    relief="flat", bd=0, cursor="hand2", padx=18, pady=9,
                                    font=("Segoe UI", 13, "bold"))
        self._start_btn.pack(side="left", padx=6)
        self._snooze_btn = tk.Button(self._btns, text="😴 Snooze", command=self._do_snooze,
                                     bg=C["panel2"], fg=C["text"], activebackground=C["panel"],
                                     relief="flat", bd=0, cursor="hand2", padx=16, pady=9,
                                     font=("Segoe UI", 12, "bold"))
        self._snooze_btn.pack(side="left", padx=6)
        def block_close():
            self.stop()   # the X always dismisses now (buttons give real actions)
        self.win.protocol("WM_DELETE_WINDOW", block_close)

    def _do_start(self):
        cb = self.on_start
        self.stop()
        if cb:
            try:
                cb()
            except Exception:
                pass

    def _do_snooze(self):
        cb = self.on_snooze
        self.stop()
        if cb:
            try:
                cb()
            except Exception:
                pass

    BAR_THIN, BAR_THICK = 6, 22      # accent-bar height; thick from level 4 up, so the flashing is hard to miss

    def _strobe_base_delay(self):
        return max(90, 150 - self.level * 12)

    def _strobe(self):
        """The flashing. It used to recolour the whole card (80-pt emoji, 48-pt text) ~14 times a
        second. Measured on this machine, repainting that card cost up to half a second per
        frame, so the window's thread did nothing BUT repaint and stopped responding to clicks.
        Now each frame only recolours the two accent bars (which have no text in them, so they cost
        next to nothing — they are simply made taller at the top levels) and, every other frame,
        the decoy boxes. Frames also pace themselves: if one runs late, the strobe slows down until
        the window keeps up, and speeds back up once it does."""
        if self.win is None or self.level < 2:
            self._strobe_job = None
            self._strobe_due = None
            return
        t0 = time.perf_counter()
        base = self._strobe_base_delay()
        if not self._strobe_delay:
            self._strobe_delay = base
        elif self._strobe_due is not None:
            late_ms = (t0 - self._strobe_due) * 1000
            if late_ms > 50:
                self._strobe_delay = min(self._strobe_delay * 1.6, 600)
            elif late_ms < 20:
                self._strobe_delay = max(base, self._strobe_delay * 0.9)
        self._strobe_i += 1
        i = self._strobe_i
        c1 = self.STROBE[i % len(self.STROBE)]
        c2 = self.STROBE[(i + 3) % len(self.STROBE)]
        try:
            self._top.configure(bg=c1)
            self._bot.configure(bg=c2)
            if i % 2 == 0:
                dc = self.STROBE[(i + 5) % len(self.STROBE)]
                for d in self.decoys:
                    d.configure(bg=dc)
                    for ch in d.winfo_children():
                        ch.configure(bg=dc)
        except Exception:
            pass
        delay = int(self._strobe_delay)
        self._strobe_due = time.perf_counter() + delay / 1000.0
        self._strobe_job = self.root.after(delay, self._strobe)

    def update(self, level, headline, subtext, voice_lines=None):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if self.win is not None:
            try:
                alive = bool(self.win.winfo_exists())
            except Exception:
                alive = False
            if not alive:            # closed behind our back — start fresh instead of erroring
                self.win, self.decoys = None, []
        created = self.win is None
        if created:
            self._build_win()
        acc = self._accent(level)
        icon = self.ICONS[min(level, len(self.ICONS) - 1)]
        w = self.win
        # repaint the card only when something on it actually changed (the nag refreshes it every
        # second with identical text, and each repaint of a big card is not free)
        shown = (level, headline, subtext)
        if created or shown != self._shown:
            self._shown = shown
            for wdg in (w, self._inner, self._icon, self._t, self._s, self._btns):
                wdg.configure(bg=self.CARD_BG)
            bar = self.BAR_THICK if level >= 4 else self.BAR_THIN
            self._top.configure(bg=acc, height=bar); self._bot.configure(bg=acc, height=bar)
            self._icon.configure(fg=acc, text=icon)
            self._t.configure(text=headline, fg="#ffffff")
            self._s.configure(text=subtext, fg=C["muted"])

        # NOTE: the alert is intentionally NOT topmost / fullscreen / focus-stealing — the
        # sound is the real alert; the window just shows without taking over the screen.
        # Size and fonts only change when the level does (re-laying-out a big window every
        # second for hours is pure waste); the small corner card still jiggles each time.
        if created or level != self._styled_level or level < 2:
            w.attributes("-fullscreen", False)
            if level >= 3:
                w.geometry(f"700x430+{(sw-700)//2}+{(sh-430)//2}")
                self._icon.configure(font=("Segoe UI Emoji", 80))
                self._t.configure(font=("Segoe UI Black", 48, "bold"))
                self._s.configure(font=("Segoe UI", 20))
            elif level == 2:
                w.geometry(f"600x360+{(sw-600)//2}+{(sh-360)//2}")
                self._icon.configure(font=("Segoe UI Emoji", 56))
                self._t.configure(font=("Segoe UI Black", 32, "bold"))
                self._s.configure(font=("Segoe UI", 16))
            else:
                jx = random.randint(-6, 6) if level >= 1 else 0
                w.geometry(f"420x186+{sw-440+jx}+{sh-250}")
                self._icon.configure(font=("Segoe UI Emoji", 38))
                self._t.configure(font=("Segoe UI Black", 21, "bold"))
                self._s.configure(font=("Segoe UI", 12))
            self._styled_level = level
        try:
            w.deiconify()
            if created:
                # pop into view ONCE when the alert starts (so you actually see it),
                # then leave it — no permanent topmost, no focus stealing
                w.lift()
        except Exception:
            pass

        want = max(0, level - 3) * self.DECOYS_PER_LEVEL
        while len(self.decoys) < want:
            d = tk.Toplevel(self.root)
            d.overrideredirect(True)
            tk.Label(d, bg=acc, fg="#ffffff", font=("Segoe UI Black", 17, "bold"),
                     text="  ⚠ FOCUS  ").pack()
            self.decoys.append(d)
        for d in self.decoys:
            try:
                d.geometry(f"188x62+{random.randint(0,max(1,sw-208))}+{random.randint(0,max(1,sh-82))}")
            except Exception:
                pass

        self.level = level
        # continuous beeper: slow pulses -> fast -> dissonant cluster
        self.alarm.set_level(level)
        # strobe lights at level 2+ (if enabled)
        if level >= 2 and self.strobe_enabled and self._strobe_job is None:
            self._strobe()
        # Voices and recordings are the expensive part (each one is a whole speech process), so
        # they fire in bursts at most every VOICE_MIN_GAP seconds even though the card refreshes
        # faster than that. Still plenty annoying, but the machine can breathe between bursts.
        now_m = time.monotonic()
        if level >= 2 and now_m - self._last_voice >= self.VOICE_MIN_GAP:
            self._last_voice = now_m
            # overlapping voices — context lines / your reminders, cuss words once "really mad"
            if voice_lines:
                lines = list(voice_lines) + (self.MAD_LINES if level >= 5 else [])
            elif self.nag_own and self.own_lines:
                lines = list(self.own_lines) + (self.MAD_LINES if level >= 5 else [])
            else:
                lines = self.MAD_LINES if level >= 5 else self.NAG_LINES
            say_overlap(lines, min(level - 1, max(1, self.max_voices)), voice=self.voice)
            # custom recordings (if any .wav files exist), overlapping, at high levels
            if level >= 3:
                play_custom_overlap(min(level - 2, 3))


# ----------------------------- freeze watchdog + health -----------------------------
_mono = time.monotonic     # the real clock, captured before anything can patch this module's `time`

def dump_threads(max_frames=8, limit=6000):
    """A readable stack for every thread: this is what shows WHERE a frozen app was stuck.
    The main thread (the window) always comes first, and threads parked on the same line are
    merged into one entry, so a pile of idle helper threads can't push the important part out."""
    names = {t.ident: t.name for t in threading.enumerate()}
    main = threading.main_thread().ident
    frames = sys._current_frames()
    groups = {}                                   # stack text -> [thread names]
    order = []
    for ident in sorted(frames, key=lambda i: (i != main, str(names.get(i, i)))):
        stack = "\n".join(line.rstrip() for line in
                           traceback.format_stack(frames[ident])[-max_frames:])
        if stack not in groups:
            groups[stack] = []
            order.append(stack)
        groups[stack].append(str(names.get(ident, ident)))
    out = []
    for stack in order:
        who = groups[stack]
        head = f"--- thread {who[0]}" if len(who) == 1 else f"--- {len(who)} threads ({', '.join(who)})"
        out.append(head + "\n" + stack)
    return "\n".join(out)[:limit]


def process_health():
    """Resource counters for this process (Windows): window objects, handles, memory, threads.
    A slow leak in any of them is what eventually makes an app that has run for days stop
    responding, so they are logged and used to restart the app BEFORE it gets that far."""
    if not core.IS_WIN:
        return {}
    try:
        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k = ctypes.WinDLL("kernel32")
        u = ctypes.WinDLL("user32")
        ps = ctypes.WinDLL("psapi")
        k.GetCurrentProcess.restype = ctypes.c_void_p
        h = k.GetCurrentProcess()
        u.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        u.GetGuiResources.restype = ctypes.c_ulong
        k.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        ps.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
        handles = ctypes.c_ulong()
        k.GetProcessHandleCount(h, ctypes.byref(handles))
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        ps.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
        return {"gdi": int(u.GetGuiResources(h, 0)), "user": int(u.GetGuiResources(h, 1)),
                "handles": int(handles.value), "mem_mb": round(pmc.WorkingSetSize / 1048576, 1),
                "threads": threading.active_count()}
    except Exception:
        return {}


class Watchdog:
    """Runs on its own thread and watches the window's thread.

    * If the UI thread stops ticking for `stall_log_sec`, it writes the stack of every thread to
      focus.log, so the cause of a freeze can actually be read afterwards.
    * If it stays frozen for `stall_restart_sec`, it restarts the app (state lives in a file and
      the hosts block stays in place, so nothing is lost).
    * Every `health_every` seconds it records the process's resource counters and restarts the
      app early if one is heading for the wall (Windows kills a process at ~10,000 window objects).
    A laptop sleeping/waking looks like a long stall from the inside, so a gap in THIS thread's
    own schedule is treated as 'the whole machine was suspended', not as a freeze."""

    LIMITS = {"gdi": 7500, "user": 7500, "handles": 20000, "mem_mb": 1500}

    def __init__(self, restart=None, log=None, stall_log_sec=8.0, stall_restart_sec=45.0,
                 interval=1.0, clock=_mono, health=process_health, health_every=600.0,
                 restart_cooldown=300.0):
        self.restart = restart
        self.log = log or core.log_event
        self.stall_log_sec = stall_log_sec
        self.stall_restart_sec = stall_restart_sec
        self.interval = interval
        self.clock = clock
        self.health = health
        self.health_every = health_every
        self.restart_cooldown = restart_cooldown     # don't hammer restarts if the first one failed
        self._last_restart = -1e18
        self._last_beat = clock()
        self._last_check = self._last_beat
        self._last_health = self._last_beat
        self._reported = False
        self._stop = threading.Event()
        self._thread = None

    def beat(self):
        self._last_beat = self.clock()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="focus-watchdog")
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.check(self.clock())
            except Exception as ex:
                self.log(f"watchdog error: {ex!r}")

    def check(self, now):
        gap = now - self._last_check
        self._last_check = now
        if gap > max(5.0, self.interval * 5):      # we were suspended too: the machine slept
            self._last_beat = self._last_health = now
            self._reported = False
            return "resumed"
        stalled = now - self._last_beat
        if stalled >= self.stall_log_sec:
            if not self._reported:
                self._reported = True
                self.log(f"UI thread not responding for {stalled:.0f}s\n{dump_threads()}")
            if stalled >= self.stall_restart_sec and self._may_restart(now):
                self.log(f"UI thread frozen for {stalled:.0f}s - restarting Focus")
                self.restart()
                return "restart"
            return "stalled"
        self._reported = False
        if self.health and now - self._last_health >= self.health_every:
            self._last_health = now
            stats = self.health() or {}
            if stats:
                self.log("health " + " ".join(f"{k}={v}" for k, v in stats.items()))
            over = [f"{k}={stats[k]}" for k, lim in self.LIMITS.items() if stats.get(k, 0) > lim]
            if over and self._may_restart(now):
                self.log("resource limit reached (" + ", ".join(over) + ") - restarting Focus")
                self.restart()
                return "restart"
        return None

    def _may_restart(self, now):
        if not self.restart or now - self._last_restart < self.restart_cooldown:
            return False
        self._last_restart = now
        return True


# ----------------------------- the app -----------------------------
class FocusApp:
    WATCHDOG_ENABLED = True      # tests switch this off: a watchdog that restarts the process would kill the run
    WATCHDOG_STALL_LOG_SEC = 8.0         # window silent this long -> write every thread's stack to the log
    WATCHDOG_STALL_RESTART_SEC = 45.0    # ... and this long -> restart the app

    def __init__(self):
        self.st = core.load_state()
        self.session_active = False
        self.session_remaining = 0
        self._tick_errors = 0                # exceptions swallowed by the tick loop (see _tick)
        self._last_tick_error = ""
        self._last_tick_mono = None
        self.session_paused = False          # paused right now (manual pause)
        self.session_manual_paused = False   # you hit Pause
        self._last_render = None             # cache to skip redundant label writes
        self.clock = 0
        self._last_nag_at = None
        self.secret = None

        # doomscroll tax
        self.scroll = ScrollCounter()
        self._hook_until = 0
        self._enforce_busy = False
        self._enforce_again = False
        self._enforce_refresh = False
        self._last_scroll = 0
        self.doom_active = False
        self._doom_flash = -999
        self.nag_frequency = 3
        self._noses_start = None   # when "on the clock, no session" began (for escalation)
        self._pause_start = None    # when the current manual pause began (for nagging)
        self._break_prev = False   # was a cheat/bank break active last tick
        self._steam_prev = False   # was a Steam break active last tick
        self._learn_prev = False   # was a learning break active last tick
        self._lt_bad_since = None  # when a non-approved YouTube tab first came to the front
        self._play_until = 0       # keep a transient notification on screen until this time
        self._recording = False    # mic recording in progress
        self._last_tabclose = 0    # cooldown for auto-closing blocked-site tabs
        self._last_pipcheck = 0    # throttle for the Picture-in-Picture sweep
        self._clocked_prev = core.clocked_out(self.st)  # for the one-time clock-out announcement
        self._clockout_offered = None   # date we last told you the clock-out option is open
        self._m_r4_shown = False        # is the popout's Clock-out row currently visible
        self._tut = None                # the open tutorial window's widgets, or None

        self.voices = list_voices()   # installed Windows voices for the picker

        # make Windows treat us as our own app so the taskbar shows OUR icon, not Python's
        if core.IS_WIN:
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Focus.StudyApp")
            except Exception:
                pass

        # The FULL window (self.root) and the mini POPOUT (self.popout) are two real,
        # independent windows, each created exactly once and never reconfigured live
        # (no toggling overrideredirect / geometry on a window after it's mapped —
        # that's an unreliable pattern that desyncs from the taskbar and the OS's own
        # window chrome). Switching modes just withdraws one and deiconifies the other,
        # so a native minimize on either window is a normal OS minimize: nothing is
        # destroyed, and root's after()-scheduled loops (enforcement, the tick) keep
        # running the whole time regardless of which window is shown.
        if HAVE_CTK:
            ctk.set_appearance_mode("dark")
            self.root = ctk.CTk()
            self.root.configure(fg_color=C["bg"])
        else:
            self.root = tk.Tk()
            self.root.configure(bg=C["bg"])
        self.root.title("StudyAnchor")
        self.root.geometry("680x672")
        # NOT topmost, unlike the popout below — the full window is allowed to sit behind
        # other apps like a normal window; <FocusOut> below sends you back to the mini
        # popout (which IS always-on-top) the moment it's no longer the front window.
        self._set_app_icon()
        self.root.protocol("WM_DELETE_WINDOW", self._quit_app)
        self.root.bind("<FocusOut>", self._on_root_focus_out)

        if HAVE_CTK:
            self.popout = ctk.CTkToplevel(self.root)
            self.popout.configure(fg_color=C["bg"])
        else:
            self.popout = tk.Toplevel(self.root)
            self.popout.configure(bg=C["bg"])
        self.popout.title("StudyAnchor")
        self.popout.geometry("320x238")
        self.popout.attributes("-topmost", True)
        self.popout.protocol("WM_DELETE_WINDOW", self._quit_app)
        try:
            self.popout.iconphoto(False, self._icon_img)
        except Exception:
            pass

        self.notifier = Notifier(self.root)
        self.notifier.on_start = self._nag_start_session
        self.notifier.on_snooze = self.snooze
        self._apply_notif_settings()
        self.is_mini = True
        self._maybe_reset_cheat_day()

        self._tk_errors = 0
        self.root.report_callback_exception = self._on_tk_error     # errors in button/timer callbacks -> focus.log
        self._watchdog = Watchdog(restart=self._restart_self, stall_log_sec=self.WATCHDOG_STALL_LOG_SEC,
                                  stall_restart_sec=self.WATCHDOG_STALL_RESTART_SEC)

        self._build_mini()
        self._build_full()
        self._show_mini()

        self._enforce_loop()
        self._tick()
        if self.WATCHDOG_ENABLED:
            self._watchdog.start()
        self._maybe_auto_tutorial()

    AUTO_TUTORIAL = True          # tests switch this off so no walkthrough pops up mid-test

    # ---------------- tutorial ----------------
    def _maybe_auto_tutorial(self):
        """First run (or the first start after this feature arrived): walk them through it once."""
        if self.AUTO_TUTORIAL and not self.st.get("tutorial_seen"):
            self.root.after(1500, self.show_tutorial)

    def show_tutorial(self):
        """The step-by-step walkthrough (tutorial.py has the words). Opens on first run and from the
        ❓ buttons; finishing, skipping or closing it all count as seen."""
        t = getattr(self, "_tut", None)
        if t:
            try:
                t["win"].lift()
                return t
            except tk.TclError:
                self._tut = None
        win = WToplevel(self.root); win.title("StudyAnchor tutorial"); win.attributes("-topmost", True)
        win.geometry("500x540")
        logo = WLogo(win, 52, C["bg"]); logo.pack(pady=(16, 0))
        count = WLabel(win, "", size=10, color=C["muted"]); count.pack(pady=(6, 0))
        title = WLabel(win, "", size=17, bold=True, color=C["cyan"], wrap=440); title.pack(pady=(4, 8))
        body = WLabel(win, "", size=11, color=C["text"], wrap=440); body.pack(padx=28, anchor="w")
        bottom = WFrame(win, color=C["bg"], radius=0); bottom.pack(side="bottom", fill="x", padx=24, pady=(0, 18))
        dots = WLabel(win, "", size=12, color=C["cyan"]); dots.pack(side="bottom", pady=(0, 10))
        back = WButton(bottom, "← Back", lambda: self._tut_move(-1), "sec", small=True)
        back.pack(side="left")
        skip = WButton(bottom, "Skip", lambda: self._tut_close(), "ghost", small=True)
        skip.pack(side="left", padx=6)
        nxt = WButton(bottom, "Next →", lambda: self._tut_move(1), "primary", small=True)
        nxt.pack(side="right")
        win.protocol("WM_DELETE_WINDOW", self._tut_close)
        self._tut = {"win": win, "i": 0, "steps": tutorial.steps(self.st), "count": count, "title": title,
                     "body": body, "dots": dots, "back": back, "next": nxt, "skip": skip}
        self._tut_render()
        return self._tut

    def _tut_render(self):
        t = self._tut
        if not t:
            return
        n, i = len(t["steps"]), t["i"]
        head, text = t["steps"][i]
        set_label(t["count"], f"Step {i + 1} of {n}")
        set_label(t["title"], head)
        set_label(t["body"], text)
        set_label(t["dots"], "  ".join("●" if k == i else "○" for k in range(n)))
        self._cfg(t["back"], state="normal" if i > 0 else "disabled")
        last = i == n - 1
        self._cfg(t["next"], text="Done ✓" if last else "Next →")
        self._cfg(t["skip"], text="Close" if last else "Skip")

    def _tut_move(self, delta):
        t = self._tut
        if not t:
            return
        i = t["i"] + delta
        if i >= len(t["steps"]):
            self._tut_close(); return
        t["i"] = max(0, i)
        self._tut_render()

    def _tut_close(self):
        """Close the walkthrough. However it ends, it has been seen, so it won't open by itself again."""
        t, self._tut = getattr(self, "_tut", None), None
        if not self.st.get("tutorial_seen"):
            self.st["tutorial_seen"] = True
            self._save()
        if t:
            try:
                t["win"].destroy()
            except Exception:
                pass

    def _on_tk_error(self, exc, val, tb):
        self._tk_errors += 1
        if self._tk_errors <= 20 or self._tk_errors % 100 == 0:
            core.log_event(f"callback error #{self._tk_errors}: "
                           + "".join(traceback.format_exception(exc, val, tb)))

    def _restart_self(self):
        """Called by the watchdog from its own thread when the window is frozen (or leaking).
        Let go of the single-instance lock, start a fresh copy, and leave. If the new copy can't
        be started this one carries on rather than leaving the machine with nothing running."""
        core.log_event("restarting Focus")
        core.release_app_instance()
        if not core.launch_app():
            core.claim_app_instance()
            return
        os._exit(3)

    def _quit_app(self):
        """The only real way to close Focus — from either window's native ✕."""
        try:
            self._watchdog.stop()
        except Exception:
            pass
        try:
            self.notifier.stop()
        except Exception:
            pass
        try:
            self.notifier.alarm.close()
        except Exception:
            pass
        for w in (getattr(self, "popout", None), getattr(self, "root", None)):
            try:
                if w:
                    w.destroy()
            except Exception:
                pass

    # ---------------- mini popout (its own real window: self.popout) ----------------
    def _build_mini(self):
        strip = WFrame(self.popout, color=C["panel"], radius=0)
        strip.pack(fill="x")
        WLogo(strip, 20, C["panel"]).pack(side="left", padx=(10, 5), pady=4)
        WLabel(strip, "StudyAnchor", size=11, bold=True, color=C["cyan"], bg=C["panel"]).pack(side="left", pady=4)
        WButton(strip, "⤢", self._show_full, "ghost", small=True, width=34).pack(side="right", pady=4)
        WButton(strip, "😴", self.snooze, "ghost", small=True, width=34).pack(side="right", padx=(0, 2), pady=4)
        WButton(strip, "❓", self.show_tutorial, "ghost", small=True, width=34).pack(side="right", padx=(0, 2), pady=4)
        WAccent(self.popout, C["green"], 3).pack(fill="x")

        body = WFrame(self.popout, color=C["bg"], radius=0)
        body.pack(fill="both", expand=True, padx=16, pady=(12, 14))
        hero = WFrame(body, color=C["bg"], radius=0); hero.pack(fill="x", anchor="w")
        self.m_dot = WLabel(hero, "●", size=13, bold=True, color=C["cyan"], bg=C["bg"])
        self.m_dot.pack(side="left", padx=(0, 7))
        self.m_status = WLabel(hero, "…", size=16, bold=True, color=C["cyan"], bg=C["bg"])
        self.m_status.pack(side="left")
        self.m_sub = WLabel(body, "…", size=10, color=C["muted"], bg=C["bg"])
        self.m_sub.pack(anchor="w", pady=(2, 12))

        r1 = WFrame(body, color=C["bg"], radius=0); r1.pack(fill="x", pady=3)
        self.m_study = WButton(r1, "▶ Study", self.toggle_session, "primary", small=True)
        self.m_study.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.m_btn2 = WButton(r1, "⚡ Cheat", self.cheat_break, "gold", small=True)
        self.m_btn2.pack(side="left", expand=True, fill="x", padx=(4, 0))
        r2 = WFrame(body, color=C["bg"], radius=0); r2.pack(fill="x", pady=3)
        WButton(r2, "☕ Bank", self.spend_bank, "sec", small=True).pack(side="left", expand=True, fill="x", padx=(0, 3))
        WButton(r2, "🎮 Games", self.steam_break, "sec", small=True).pack(side="left", expand=True, fill="x", padx=3)
        WButton(r2, "📚 Learn", self.learning_break, "sec", small=True).pack(side="left", expand=True, fill="x", padx=(3, 0))
        r3 = WFrame(body, color=C["bg"], radius=0); r3.pack(fill="x", pady=(3, 0))
        WButton(r3, "🔒 Lock in", self.end_all_breaks, "sec", small=True).pack(side="left", expand=True, fill="x", padx=(0, 4))
        WButton(r3, "☢ Nuclear", self.go_nuclear, "danger", small=True).pack(side="left", expand=True, fill="x", padx=(4, 0))
        # only packed from 20:00 (see _sync_clockout_row): the option to call it a night
        self.m_r4 = WFrame(body, color=C["bg"], radius=0)
        self.m_clockout = WButton(self.m_r4, "🕗 Clock out for the night", self.clock_out, "gold", small=True)
        self.m_clockout.pack(fill="x")

    POPOUT_BASE_H = 238

    def _sync_clockout_row(self, avail):
        """Show the popout's Clock-out button only while the option is open, and grow/shrink the
        popout to fit (its size is fixed, so it has to be told)."""
        if avail == self._m_r4_shown:
            return
        self._m_r4_shown = avail
        try:
            if avail:
                self.m_r4.pack(fill="x", pady=(3, 0))
            else:
                self.m_r4.pack_forget()
            self.popout.update_idletasks()
            # winfo_reqheight is in real pixels but customtkinter scales whatever geometry() is given
            # by the screen's DPI scaling, so convert back first or the window ends up too tall
            try:
                scale = float(self.popout._get_window_scaling()) if HAVE_CTK else 1.0
            except Exception:
                scale = 1.0
            self.popout.geometry(f"320x{max(self.POPOUT_BASE_H, round(self.popout.winfo_reqheight() / (scale or 1.0)))}")
        except tk.TclError:
            pass

    def _show_mini(self):
        self.is_mini = True
        self.root.withdraw()          # hide the full window (still alive: its after()
        self.popout.deiconify()       # loops keep running) — show the real popout window
        self.popout.lift()
        self.refresh_ui()

    def _on_root_focus_out(self, event=None):
        # <FocusOut> fires whenever focus leaves root, including onto our OWN dialogs
        # (settings entries, the nuclear/bank/day-off popups) — those aren't a real
        # "moved to the back". Check one tick later whether the whole app lost focus.
        self.root.after(150, self._check_root_focus_lost)

    def _check_root_focus_lost(self):
        if self.is_mini:
            return
        try:
            focused = self.root.focus_get()
        except Exception:
            focused = None
        if focused is None:   # nothing of ours has focus -> focus went to another app
            try:
                self._show_mini()
            except tk.TclError:
                pass          # the windows are being destroyed (app is quitting)

    # ---------------- full window ----------------
    def _build_full(self):
        self.full = WFrame(self.root, color=C["bg"], radius=0)
        self.full.pack(fill="both", expand=True)   # packed once, permanently — root IS the full window

        header = WFrame(self.full, color=C["panel"], radius=0)
        header.pack(fill="x")
        WLogo(header, 30, C["panel"]).pack(side="left", padx=(14, 7), pady=8)
        WLabel(header, "StudyAnchor", size=15, bold=True, color=C["cyan"], bg=C["panel"]).pack(side="left", pady=10)
        WButton(header, "⤡ popout", self._show_mini, "ghost", small=True).pack(side="right", padx=10, pady=8)
        WButton(header, "❓ Tutorial", self.show_tutorial, "ghost", small=True).pack(side="right", padx=(0, 2), pady=8)
        WAccent(self.full, C["green"], 3).pack(fill="x")

        if HAVE_CTK:
            self.tabs = ctk.CTkTabview(self.full, fg_color=C["panel"], corner_radius=14,
                                       segmented_button_fg_color=C["panel2"],
                                       segmented_button_selected_color=C["green"],
                                       segmented_button_selected_hover_color=C["green2"],
                                       segmented_button_unselected_color=C["panel2"],
                                       text_color=C["text"], command=self._on_tab_changed)
            self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
            for name in ("Dashboard", "Bank", "Learning", "Reminders", "Settings"):
                self.tabs.add(name)
            self.tab_dash = self.tabs.tab("Dashboard")
            self.tab_bank = self.tabs.tab("Bank")
            self.tab_learn = self.tabs.tab("Learning")
            self.tab_rem = self.tabs.tab("Reminders")
            self.tab_set = self.tabs.tab("Settings")
        else:
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except Exception:
                pass
            style.configure("TNotebook", background=C["bg"], borderwidth=0)
            style.configure("TNotebook.Tab", background=C["panel"], foreground=C["muted"],
                            padding=(14, 7), font=("Segoe UI", 9, "bold"), borderwidth=0)
            style.map("TNotebook.Tab", background=[("selected", C["panel2"])],
                      foreground=[("selected", C["cyan"])])
            nb = ttk.Notebook(self.full); nb.pack(fill="both", expand=True, padx=6, pady=6)
            self.tab_dash = tk.Frame(nb, bg=C["bg"]); self.tab_bank = tk.Frame(nb, bg=C["bg"])
            self.tab_rem = tk.Frame(nb, bg=C["bg"]); self.tab_set = tk.Frame(nb, bg=C["bg"])
            self.tab_learn = tk.Frame(nb, bg=C["bg"])
            for f, n in [(self.tab_dash, "Dashboard"), (self.tab_bank, "Bank"),
                         (self.tab_learn, "Learning"),
                         (self.tab_rem, "Reminders"), (self.tab_set, "Settings")]:
                nb.add(f, text=n)
            nb.bind("<<NotebookTabChanged>>",
                    lambda e: self._on_tab_changed(nb.tab(nb.select(), "text")))
            self._nb = nb

        self._build_dash()
        self._build_bank(); self._build_learning(); self._build_reminders(); self._build_settings()
        self._render_learning()

    def _build_learning(self):
        p = self.tab_learn
        WLabel(p, "📚 Learning break", size=14, bold=True, color=C["cyan"], bg=C["bg"]).pack(
            anchor="w", padx=14, pady=(14, 2))
        WLabel(p, f"Opens YouTube for {core.LEARNING_BREAK_MIN} min, but only for the videos you've approved. "
                  f"A YouTube tab whose title doesn't match is closed after {core.LEARNING_GRACE_SEC} seconds, "
                  "and every other blocked site stays blocked.",
               size=9, color=C["muted"], bg=C["bg"], wrap=600).pack(anchor="w", padx=14)
        self.l_status = WLabel(p, "", size=11, bold=True, color=C["muted"], bg=C["bg"])
        self.l_status.pack(anchor="w", padx=14, pady=(10, 4))
        WButton(p, "📚 Start learning break", self.learning_break, "primary").pack(anchor="w", padx=14, pady=(0, 10))

        WLabel(p, "APPROVED VIDEOS", size=9, bold=True, color=C["muted"], bg=C["bg"]).pack(anchor="w", padx=14)
        if HAVE_CTK:
            self.l_list = ctk.CTkScrollableFrame(p, fg_color=C["bg"], height=120)
        else:
            self.l_list = tk.Frame(p, bg=C["bg"])
        self.l_list.pack(fill="x", padx=14, pady=(2, 6))

        arow = WFrame(p, color=C["bg"], radius=0); arow.pack(anchor="w", padx=14, pady=(2, 0))
        self.l_entry = WEntry(arow, 24); self.l_entry.pack(side="left")
        self.l_entry.bind("<Return>", lambda e: self.add_approval())
        WButton(arow, "＋ Approve", self.add_approval, "sec", small=True).pack(side="left", padx=8)
        self.l_always = tk.IntVar(value=0)
        WCheck(p, f"  🎧 Audiobook — no time limit (needs {core.LEARNING_MIN_PHRASE_ALWAYS}+ characters, "
                  f"max {core.LEARNING_MAX_ALWAYS})", self.l_always).pack(anchor="w", padx=14, pady=(6, 0))
        WLabel(p, "Type a few words from the video's TITLE (not the channel), e.g. \"CS50 lecture 3\" - every "
                  "word has to appear in the title, in any order. "
                  f"A new approval only starts counting after {core.LEARNING_APPROVAL_DELAY_MIN} minutes, so "
                  "approve things in your free time — not in the middle of a craving. Removing one is instant.",
               size=9, color=C["muted"], bg=C["bg"], wrap=600).pack(anchor="w", padx=14, pady=(6, 0))
        self.l_msg = WLabel(p, "", size=9, color=C["green"], bg=C["bg"]); self.l_msg.pack(anchor="w", padx=14, pady=4)

    def _current_tab(self):
        try:
            if HAVE_CTK:
                return self.tabs.get()
            return self._nb.tab(self._nb.select(), "text")
        except Exception:
            return None

    def _on_tab_changed(self, current_name=None):
        # switching tabs should never show stale/blank data — refresh right away instead of
        # waiting for the next periodic tick, which is what made switching feel broken/laggy.
        if current_name is None:
            try:
                current_name = self.tabs.get()
            except Exception:
                current_name = None
        self.refresh_ui()
        if current_name == "Learning":
            self._render_learning()

    def _caption(self, parent, text):
        return WLabel(parent, text.upper(), size=9, bold=True, color=C["muted"], bg=C["bg"])

    def _chip(self, parent, title):
        card = WFrame(parent, color=C["chip"], radius=12)
        WLabel(card, title.upper(), size=8, bold=True, color=C["muted"], bg=C["chip"]).pack(
            anchor="w", padx=13, pady=(9, 0))
        val = WLabel(card, "—", size=15, bold=True, color=C["text"], bg=C["chip"])
        val.pack(anchor="w", padx=13, pady=(0, 9))
        return card, val

    def _build_dash(self):
        p = self.tab_dash
        # hero status card
        card = WFrame(p, color=C["panel"], radius=18); card.pack(fill="x", padx=16, pady=(16, 10))
        top = WFrame(card, color=C["panel"], radius=0); top.pack(fill="x", padx=20, pady=(18, 2))
        self.d_dot = WLabel(top, "●", size=15, bold=True, color=C["cyan"], bg=C["panel"])
        self.d_dot.pack(side="left", padx=(0, 9))
        self.d_status = WLabel(top, "…", size=24, bold=True, color=C["cyan"], bg=C["panel"])
        self.d_status.pack(side="left")
        self.d_sub = WLabel(card, "…", size=12, color=C["muted"], bg=C["panel"])
        self.d_sub.pack(anchor="w", padx=20, pady=(0, 18))

        # stat chips
        chips = WFrame(p, color=C["bg"], radius=0); chips.pack(fill="x", padx=16, pady=(0, 4))
        c1, self.d_bank_v = self._chip(chips, "Time bank"); c1.pack(side="left", expand=True, fill="x", padx=(0, 5))
        c2, self.d_steam_v = self._chip(chips, "Games"); c2.pack(side="left", expand=True, fill="x", padx=5)
        c3, self.d_cheat_v = self._chip(chips, "Cheats left"); c3.pack(side="left", expand=True, fill="x", padx=(5, 0))

        self._caption(p, "Focus").pack(anchor="w", padx=20, pady=(14, 4))
        r = WFrame(p, color=C["bg"], radius=0); r.pack(fill="x", padx=16, pady=(0, 2))
        self.d_study = WButton(r, "▶  Start study session", self.toggle_session, "primary")
        self.d_study.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.d_pause = WButton(r, "⏸ Pause", self.toggle_pause, "sec")
        self.d_pause.pack(side="left", padx=(5, 0))

        self._caption(p, "Breaks").pack(anchor="w", padx=20, pady=(14, 4))
        r2 = WFrame(p, color=C["bg"], radius=0); r2.pack(fill="x", padx=16, pady=(0, 2))
        for txt, cmd, kind in [("⚡ Cheat", self.cheat_break, "gold"),
                               ("🎮 Games", self.steam_break, "sec"),
                               ("📚 Learn", self.learning_break, "sec"),
                               ("☕ Bank", self.spend_bank, "gold"),
                               ("🔒 Lock in", self.end_all_breaks, "sec"),
                               ("😴 Snooze", self.snooze, "sec"),
                               ("🕗 Clock out", self.clock_out, "sec")]:
            WButton(r2, txt, cmd, kind, small=True).pack(side="left", expand=True, fill="x", padx=2)

        self._caption(p, "Danger zone").pack(anchor="w", padx=20, pady=(14, 4))
        r3 = WFrame(p, color=C["bg"], radius=0); r3.pack(fill="x", padx=16, pady=(0, 12))
        WButton(r3, "🌴 Disable for the day", self.disable_dialog, "danger").pack(
            side="left", expand=True, fill="x", padx=(0, 5))
        WButton(r3, "☢ GO NUCLEAR", self.go_nuclear, "danger").pack(
            side="left", expand=True, fill="x", padx=(5, 0))

    def _build_hours(self, p):
        """The (read-only) study hours: a compact block at the top of the Settings tab."""
        WLabel(p, "Active hours 🔒", size=14, bold=True, color=C["cyan"], bg=C["bg"]).pack(
            anchor="w", padx=14, pady=(10, 2))
        row = WFrame(p, color=C["bg"], radius=0); row.pack(anchor="w", padx=14)
        for col, (caption, attr) in enumerate([("WEEKDAYS", "s_hours"), ("WEEKENDS (Sat/Sun)", "s_hours_weekend")]):
            cell = WFrame(row, color=C["bg"], radius=0); cell.grid(row=0, column=col, sticky="w", padx=(0, 30))
            WLabel(cell, caption, size=9, bold=True, color=C["muted"], bg=C["bg"]).pack(anchor="w")
            lbl = WLabel(cell, "", size=16, bold=True, color=C["text"], bg=C["bg"]); lbl.pack(anchor="w")
            setattr(self, attr, lbl)
        self.s_clock = WLabel(p, "", size=10, color=C["muted"], bg=C["bg"])
        self.s_clock.pack(anchor="w", padx=14, pady=(2, 0))
        WLabel(p, "Locked: set in the program and can't be changed here. Outside these hours everything is free.",
               size=9, color=C["gold"], bg=C["bg"]).pack(anchor="w", padx=14)

    def _render_schedule(self):
        set_label(self.s_hours, f"{self.st['schedule_start']}  →  {self.st['schedule_end']}")
        set_label(self.s_hours_weekend,
                  f"{self.st.get('weekend_schedule_start', '10:00')}  →  "
                  f"{self.st.get('weekend_schedule_end', '18:00')}")
        co = self.st.get("clockout_time", "")
        set_label(self.s_clock, f"🕗 Clock out at {co} (every day)" if co else "🕗 Clock-out: off")

    def _build_bank(self):
        p = self.tab_bank
        card = WFrame(p, color=C["panel2"], radius=16); card.pack(fill="x", padx=14, pady=14)
        WLabel(card, "⏳ Time Bank", size=14, bold=True, color=C["gold"], bg=C["panel2"]).pack(anchor="w", padx=18, pady=(14, 0))
        self.b_balance = WLabel(card, "", size=30, bold=True, color=C["text"], bg=C["panel2"])
        self.b_balance.pack(anchor="w", padx=18, pady=(0, 14))
        WLabel(p, f"Finish a study session to earn +{core.SESSION_REWARD_MIN} min. Spend banked time "
                  "for a guilt-free break with no cheating.", size=10, color=C["muted"], bg=C["bg"]).pack(
            anchor="w", padx=18)
        WButton(p, "☕ Spend bank time now", self.spend_bank, "gold").pack(anchor="w", padx=14, pady=12)

    def _build_reminders(self):
        p = self.tab_rem
        WLabel(p, "📝 Reminders", size=14, bold=True, color=C["cyan"], bg=C["bg"]).pack(
            anchor="w", padx=14, pady=(14, 2))
        WLabel(p, "Your notepad. Write one reminder per line — the voice reads them aloud.",
               size=9, color=C["muted"], bg=C["bg"]).pack(anchor="w", padx=14)
        self.rem_text = WTextbox(p, height=9, width=46); self.rem_text.pack(fill="x", padx=14, pady=8)

        row = WFrame(p, color=C["bg"], radius=0); row.pack(fill="x", padx=14)
        WButton(row, "💾 Save", self.save_reminders, "primary").pack(side="left", padx=(0, 6))
        WButton(row, "🔊 Read all", lambda: self.read_reminders("all"), "sec").pack(side="left", padx=6)
        WButton(row, "🔊 Read one", lambda: self.read_reminders("one"), "sec").pack(side="left", padx=6)
        WButton(row, "⏹ Stop", stop_speech, "ghost", small=True).pack(side="left", padx=6)

        vrow = WFrame(p, color=C["bg"], radius=0); vrow.pack(fill="x", padx=14, pady=(10, 2))
        WLabel(vrow, "Voice:", bg=C["bg"]).pack(side="left")
        self.voice_var = tk.StringVar(value=(self.st.get("reminder_voice") or "(default)"))
        WOption(vrow, ["(default)"] + self.voices, self.voice_var).pack(side="left", padx=8)
        WButton(vrow, "▶ Test", self.test_voice, "ghost", small=True).pack(side="left", padx=6)

        row2 = WFrame(p, color=C["bg"], radius=0); row2.pack(fill="x", padx=14, pady=(6, 2))
        WLabel(row2, "Auto-read a random reminder every", bg=C["bg"]).pack(side="left")
        self.rem_interval = WEntry(row2, 5); self.rem_interval.pack(side="left", padx=8)
        WLabel(row2, "min (0 = off)", color=C["muted"], bg=C["bg"]).pack(side="left")

        self.nag_own_var = tk.IntVar(value=1 if self.st.get("nag_own_words", True) else 0)
        WCheck(p, "  Nag me with my OWN reminders during notifications",
               self.nag_own_var).pack(anchor="w", padx=14, pady=(6, 6))

        WLabel(p, "🎙 Record your own voice — plays during the loudest notifications:",
               size=9, color=C["muted"], bg=C["bg"]).pack(anchor="w", padx=14)
        rrow = WFrame(p, color=C["bg"], radius=0); rrow.pack(fill="x", padx=14, pady=(2, 2))
        self.rec_btn = WButton(rrow, "🎙 Record", self.toggle_record, "danger", small=True)
        self.rec_btn.pack(side="left", padx=(0, 6))
        WButton(rrow, "🔊 Test recordings", self.test_recordings, "ghost", small=True).pack(side="left", padx=6)
        WButton(rrow, "🗑 Clear", self.clear_recordings, "ghost", small=True).pack(side="left", padx=6)

        self.rem_msg = WLabel(p, "", size=9, color=C["green"], bg=C["bg"]); self.rem_msg.pack(anchor="w", padx=14, pady=(4, 0))

    def _reminder_lines(self):
        raw = self.st.get("reminders", "")
        return [ln.strip("-•*  \t").strip() for ln in raw.splitlines() if ln.strip()]

    def _chosen_voice(self):
        v = self.voice_var.get() if hasattr(self, "voice_var") else ""
        return None if (not v or v == "(default)") else v

    def save_reminders(self):
        try:
            self.st["reminders"] = self.rem_text.get("1.0", "end").strip()
            self.st["reminder_interval_min"] = min(self.SETTING_MAX, max(0, int(float(self.rem_interval.get().strip() or 0))))
            self.st["reminder_voice"] = self._chosen_voice() or ""
            self.st["nag_own_words"] = bool(self.nag_own_var.get())
            self._save()
            self._apply_notif_settings()   # push new voice / own-words into the nagger
            set_label(self.rem_msg, "Saved.", C["green"])
        except Exception as ex:
            set_label(self.rem_msg, f"Bad value: {ex}", C["danger"])

    def test_voice(self):
        say("This is the voice that will read your reminders.", voice=self._chosen_voice())
        set_label(self.rem_msg, "🔊 Testing voice…", C["cyan"])

    def toggle_record(self):
        if not self._recording:
            if record_start():
                self._recording = True
                self._cfg(self.rec_btn, text="⏹ Stop & save")
                set_label(self.rem_msg, "● Recording… speak, then hit Stop & save.", C["danger"])
            else:
                set_label(self.rem_msg, "Couldn't start recording — is a microphone connected?", C["danger"])
        else:
            try:
                os.makedirs(SOUNDS_DIR, exist_ok=True)
            except Exception:
                pass
            path = os.path.join(SOUNDS_DIR, f"rec_{int(time.time())}.wav")
            ok = record_stop_save(path)
            self._recording = False
            self._cfg(self.rec_btn, text="🎙 Record")
            if ok:
                set_label(self.rem_msg, f"Saved {os.path.basename(path)} ✓  ({len(list_customs())} recordings)", C["green"])
            else:
                set_label(self.rem_msg, "Save failed — recording may have been empty.", C["danger"])

    def test_recordings(self):
        files = list_customs()
        if not files:
            set_label(self.rem_msg, "No recordings yet — hit 🎙 Record first.", C["muted"]); return
        play_custom_overlap(1)
        set_label(self.rem_msg, f"🔊 Playing a recording… ({len(files)} saved)", C["cyan"])

    def clear_recordings(self):
        n = 0
        for f in list_customs():
            try:
                os.remove(f); n += 1
            except Exception:
                pass
        set_label(self.rem_msg, f"Deleted {n} recording(s).", C["muted"])

    def read_reminders(self, mode="all"):
        try:
            self.st["reminders"] = self.rem_text.get("1.0", "end").strip()
        except Exception:
            pass
        lines = self._reminder_lines()
        if not lines:
            set_label(self.rem_msg, "Nothing to read — write a reminder first.", C["danger"]); return
        text = random.choice(lines) if mode == "one" else ". ".join(lines)
        say(text, voice=self._chosen_voice(), rate=0)
        set_label(self.rem_msg, "🔊 Reading…", C["cyan"])

    def _build_settings(self):
        p = self._scrollable(self.tab_set)       # taller than the tab, so it scrolls
        self._set_scroll = p
        self._build_hours(p)
        WLabel(p, "Settings", size=14, bold=True, color=C["cyan"], bg=C["bg"]).pack(anchor="w", padx=14, pady=(12, 4))
        grid = WFrame(p, color=C["bg"], radius=0); grid.pack(anchor="w", padx=14)
        self.set_entries = {}
        rows = [("session_length_min", f"Study session length (min, {core.MIN_SESSION_MIN} or more)"),
                ("snooze_min", "Snooze length (min)"),
                ("daily_study_cap_min", "Daily study cap — burnout guard (min, 0=off)"),
                ("steam_break_min", "Gaming break length (min)"),
                ("steam_cooldown_min", "Gaming break cooldown (min)")]
        for i, (key, label) in enumerate(rows):
            WLabel(grid, label, bg=C["bg"]).grid(row=i, column=0, sticky="w", pady=4)
            e = WEntry(grid, 7); e.grid(row=i, column=1, padx=10, pady=4)
            self.set_entries[key] = e
        self.slider_widgets = {}
        self._slider_row(p, "Notification frequency (1 rare – 5 relentless)", "nag_frequency", 1, 5)
        self._slider_row(p, "Alarm intensity (1 calm – 5 relentless)", "alarm_speed", 1, 5)
        self._slider_row(p, "Max overlapping voices", "max_voices", 1, 6)

        self.strobe_var = tk.IntVar(value=1 if self.st.get("strobe_enabled", True) else 0)
        WCheck(p, "  Strobe lights on high-level notifications (⚠ flashing)",
               self.strobe_var).pack(anchor="w", padx=14, pady=(10, 4))
        WLabel(p, "Custom recordings: drop .wav files into the sounds\\ folder — they play "
                  "(overlapping) when the nagging peaks.", size=9, color=C["muted"], bg=C["bg"]).pack(
            anchor="w", padx=14)
        WLabel(p, "Blocked sites 🔒 (you can add, never remove):", bg=C["bg"]).pack(anchor="w", padx=14, pady=(12, 2))
        self.set_block = WTextbox(p, height=6, width=42); self.set_block.pack(anchor="w", padx=14)
        arow = WFrame(p, color=C["bg"], radius=0); arow.pack(anchor="w", padx=14, pady=(6, 0))
        self.add_site = WEntry(arow, 22); self.add_site.pack(side="left")
        self.add_site.bind("<Return>", lambda e: self.add_blocked_site())
        WButton(arow, "＋ Add site", self.add_blocked_site, "sec", small=True).pack(side="left", padx=8)
        WLabel(p, "Some settings only go one way: session length, daily cap & gaming cooldown can only "
                  "go up; snooze & gaming break length only down.",
               size=9, color=C["muted"], bg=C["bg"]).pack(anchor="w", padx=14, pady=(8, 0))
        srow = WFrame(p, color=C["bg"], radius=0); srow.pack(anchor="w", fill="x", padx=14, pady=10)
        WButton(srow, "Save settings", self.save_settings, "primary").pack(side="left", padx=(0, 6))
        WButton(srow, "🔔 Test notification", self.test_notification, "sec").pack(side="left")
        self.set_msg = WLabel(p, "", size=9, color=C["green"], bg=C["bg"]); self.set_msg.pack(anchor="w", padx=14)

    def _scrollable(self, parent):
        """A frame that scrolls vertically (mouse wheel or bar) when its content is taller than the
        space it has. Returns the frame to build into."""
        if HAVE_CTK:
            f = ctk.CTkScrollableFrame(parent, fg_color=C["bg"], corner_radius=0)
            f.pack(fill="both", expand=True)
            return f
        outer = tk.Frame(parent, bg=C["bg"]); outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=C["bg"], highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C["bg"])
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        def wheel(e):
            canvas.yview_scroll(-1 * (e.delta // 120 or (1 if e.delta > 0 else -1)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        inner._canvas = canvas          # so callers/tests can scroll it
        return inner

    def _slider_row(self, parent, label, key, frm, to):
        row = WFrame(parent, color=C["bg"], radius=0); row.pack(anchor="w", fill="x", padx=14, pady=3)
        var = tk.IntVar(value=int(self.st.get(key, frm)))
        WLabel(row, label, size=10, bg=C["bg"]).pack(side="left")
        vlbl = WLabel(row, str(var.get()), size=11, bold=True, color=C["cyan"], bg=C["bg"])
        vlbl.pack(side="right", padx=(8, 0))
        WSlider(row, frm, to, var, command=lambda v, l=vlbl: l.configure(text=str(int(float(v))))).pack(
            side="right", padx=8)
        self.slider_widgets[key] = (var, vlbl)

    def _apply_notif_settings(self):
        self.notifier.strobe_enabled = self.st.get("strobe_enabled", True)
        self.notifier.max_voices = int(self.st.get("max_voices", 4))
        self.notifier.alarm.speed = int(self.st.get("alarm_speed", 3))
        self.notifier.voice = self.st.get("reminder_voice") or None
        self.notifier.nag_own = bool(self.st.get("nag_own_words", True))
        self.notifier.own_lines = self._reminder_lines()
        self.nag_frequency = int(self.st.get("nag_frequency", 3))

    def _show_full(self):
        self.is_mini = False
        self.popout.withdraw()        # hide the popout (still alive) — show the real full window
        self.root.deiconify()
        self.root.lift()
        self._render_schedule()
        for k, e in self.set_entries.items():
            self._set_entry(e, str(self.st.get(k, "")))
        try:
            self.strobe_var.set(1 if self.st.get("strobe_enabled", True) else 0)
            for key, (var, vlbl) in self.slider_widgets.items():
                var.set(int(self.st.get(key, var.get())))
                vlbl.configure(text=str(var.get()))
        except Exception:
            pass
        self._render_blocklist()
        try:
            self.rem_text.delete("1.0", "end")
            self.rem_text.insert("1.0", self.st.get("reminders", ""))
            self._set_entry(self.rem_interval, str(self.st.get("reminder_interval_min", 0)))
            self.voice_var.set(self.st.get("reminder_voice") or "(default)")
            self.nag_own_var.set(1 if self.st.get("nag_own_words", True) else 0)
        except Exception:
            pass
        self.refresh_ui()

    @staticmethod
    def _set_entry(e, val):
        try:
            e.delete(0, "end"); e.insert(0, val)
        except Exception:
            pass

    # ---------------- status ----------------
    def _status(self):
        now = time.time()
        if core.nuclear(self.st):
            return (f"☢ NUCLEAR {fmt(self.st['nuclear_until'] - now)}", "total lockdown — no escapes", C["danger"])
        if self.session_active:
            if self.session_manual_paused:
                return (f"⏸ PAUSED {fmt(self.session_remaining)}", "session on hold — resume when ready", C["gold"])
            return (f"📚 STUDY {fmt(self.session_remaining)}", "locked in — earn your break", C["green"])
        if not core.within_schedule(self.st, now):
            return ("🌙 OFF-HOURS", f"free until {core.next_schedule_start(self.st, now)}", C["muted"])
        if self.st.get("unlock_until", 0) > now:
            return (f"☕ BREAK {fmt(self.st['unlock_until'] - now)}", "sites open — enjoy it", C["cyan"])
        if core.learning_active(self.st, now) and not core.clocked_out(self.st, now):
            return (f"📚 LEARNING {fmt(self.st['learning_until'] - now)}", "approved videos only", C["cyan"])
        if self.st.get("snooze_until", 0) > now:
            return (f"😴 SNOOZED {fmt(self.st['snooze_until'] - now)}", "nudges paused — still blocked", C["muted"])
        if core.clocked_out(self.st, now):
            return (f"🕗 CLOCKED OUT", "workday's over — go relax", C["green"])
        if core.burnout(self.st):
            return ("🌿 REST", f"you hit today's {self.st['daily_study_cap_min']}-min goal — relax", C["green"])
        return ("🔒 LOCKED IN", "distractions blocked", C["cyan"])

    @staticmethod
    def _cfg(w, **kw):
        try:
            w.configure(**kw)
        except Exception:
            pass

    def refresh_ui(self):
        head, sub, col = self._status()
        studying = self.session_active
        paused = self.session_manual_paused
        bank = self.st.get("time_bank_minutes", 0)
        pen = self.st.get("doomscroll_penalty_min", 1)
        dooming = self.doom_active or (self.clock - self._doom_flash) < 3
        if dooming:
            sub = f"📉 DOOMSCROLLING — −{pen} min/scroll"
        sub_col = C["danger"] if dooming else C["muted"]
        bank_col = C["danger"] if bank < 0 else C["text"]
        pause_txt = "▶ Resume" if paused else "⏸ Pause"

        now = time.time()
        idx = min(self.st.get("cheat_index", 0), len(core.CHEAT_LADDER) - 1)
        cheats_left = sum(1 for m in core.CHEAT_LADDER[idx:] if m > 0)
        steam = ("OPEN" if self.st.get("steam_break_until", 0) > now
                 else ("BLOCKED" if core.within_schedule(self.st, now) and not core.clocked_out(self.st, now)
                       else "FREE"))
        steam_col = C["green"] if steam == "OPEN" else (C["muted"] if steam == "FREE" else C["danger"])

        # skip all widget writes if nothing visible changed (optimization)
        co_avail = core.clockout_option_available(self.st, now)
        key = (self.is_mini, head, sub, col, sub_col, studying, paused, f"{bank:.0f}", bank_col, steam, cheats_left,
               co_avail)
        if key == self._last_render:
            return
        self._last_render = key
        self._sync_clockout_row(co_avail)

        if self.is_mini:
            set_label(self.m_dot, color=col)
            set_label(self.m_status, head, col); set_label(self.m_sub, sub, sub_col)
            set_label(self.m_study, "■ Stop" if studying else "▶ Study")
            if studying:
                self._cfg(self.m_btn2, text=pause_txt, command=self.toggle_pause)
            else:
                self._cfg(self.m_btn2, text="⚡ Cheat", command=self.cheat_break)
        else:
            set_label(self.d_dot, color=col)
            set_label(self.d_status, head, col); set_label(self.d_sub, sub, sub_col)
            set_label(self.d_study, "■  Stop session" if studying else "▶  Start study session")
            self._cfg(self.d_pause, text=pause_txt)
            set_label(self.b_balance, f"{bank:.0f} min", bank_col)
            set_label(self.d_bank_v, f"{bank:.0f} min", bank_col)
            set_label(self.d_steam_v, steam, steam_col)
            set_label(self.d_cheat_v, f"{cheats_left} × 5m" if cheats_left else "none",
                      C["gold"] if cheats_left else C["muted"])

    # ---------------- actions ----------------
    def _maybe_reset_cheat_day(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.st.get("cheat_day") != today:
            self.st["cheat_index"] = 0
            self.st["cheat_day"] = today
            self.st["learning_used"] = 0         # learning breaks come back daily too
            self.st["studied_today_min"] = 0     # burnout counter resets daily too
            self.st["studied_day"] = today
            self._save()

    START_LINES = ["Start a session.", "Lock in. Right now.", "Stop stalling and study.",
                   "You are on the clock. Begin now.", "No more excuses. Start a session.",
                   "Quit wasting time and focus."]
    CHEAT_LINES = ["Cheat break started.", "You are burning earned time.",
                   "Make it quick and get back to work.", "This is time you will not get back."]
    RESUME_LINES = ["Resume your session.", "Stop pausing and get back to work.",
                    "No pausing your way out. Resume now.", "Un-pause and focus."]

    def toggle_session(self):
        self._noses_start = None
        if self.session_active:
            self.session_active = False
            self.session_paused = False
            self.session_manual_paused = False
            self._pause_start = None
            self.notifier.stop()
        else:
            self.session_active = True
            self.session_paused = False
            self.session_manual_paused = False
            self._pause_start = None
            self.session_remaining = int(self.st.get("session_length_min", 45)) * 60
            self.st["unlock_until"] = 0
            self.st["learning_until"] = 0
            self._save(); self._enforce_async()
        self.refresh_ui()

    def _set_app_icon(self):
        """Show the StudyAnchor logo in the title bar and on the taskbar."""
        try:
            self._icon_img = tk.PhotoImage(master=self.root, file=LOGO_FILE)   # keep a ref so it isn't GC'd
            self.root.iconphoto(True, self._icon_img)   # True = default for all our windows
        except Exception:
            pass

    def _save(self):
        core.save_state(self.st)

    def _nag_start_session(self):
        """Start a study session straight from a notification (so you're never trapped)."""
        if not self.session_active:
            self.toggle_session()
        self._bring_to_front()

    def _bring_to_front(self):
        win = self.popout if self.is_mini else self.root
        try:
            win.deiconify()
            win.lift()
            if win is self.popout:   # only the popout stays pinned on top permanently
                win.attributes("-topmost", True)
        except Exception:
            pass

    def toggle_pause(self):
        """Manually pause/resume the study session (back out without losing progress)."""
        if not self.session_active:
            return
        self.session_manual_paused = not self.session_manual_paused
        if not self.session_manual_paused:
            self._pause_start = None
            self.notifier.stop(); self._last_nag_at = None
        self.refresh_ui()

    def snooze(self):
        """Pause the 'start a session' nudges for 10 minutes (sites stay blocked)."""
        if core.nuclear(self.st):
            self._popup("☢ Nuclear lockdown", "No snoozing during a nuclear lockdown.", C["danger"]); return
        mins = int(self.st.get("snooze_min", 10))
        self.st["snooze_until"] = time.time() + mins * 60
        self._noses_start = None
        self.notifier.stop(); self._last_nag_at = None
        self._save()
        self._popup(f"😴 Snoozed {mins} min", "Session nudges paused. Sites stay blocked.", C["muted"])
        self.refresh_ui()

    def test_notification(self, level=4):
        """Fire a full notification now (icon + strobe + beeps + voices) for a few seconds."""
        self.notifier.update(int(level), "TEST ALERT",
                             "If you see and hear this, notifications work.",
                             voice_lines=["This is a test.", "Notifications are working."])
        self.root.after(5000, self.notifier.stop)

    def end_all_breaks(self):
        """Back out of a cheat / bank / gaming / learning break early and lock straight back in."""
        now = time.time()
        active = (self.st.get("unlock_until", 0) > now or self.st.get("steam_break_until", 0) > now
                  or self.st.get("learning_until", 0) > now)
        if not active:
            self._popup("Already locked in", "No break to end — you're already focused. 💪", C["cyan"]); return
        self.st["unlock_until"] = 0
        self.st["steam_break_until"] = 0
        self.st["learning_until"] = 0
        self._save(); self._enforce_async()
        self._popup("🔒 Locked back in", "Break ended early. Respect.", C["green"])
        self.refresh_ui()

    def clock_out(self):
        """Call it a night. Allowed from 20:00 (core.CLOCKOUT_OPTION_TIME) until the automatic
        clock-out; it frees the evening, so it asks first."""
        if self._nuke_guard() or self._session_guard():
            return
        now = time.time()
        if not core.within_schedule(self.st, now) or core.clocked_out(self.st, now):
            self._popup("Already free", "You're already clocked out — nothing is blocked.", C["muted"]); return
        if not core.clockout_option_available(self.st, now):
            self._popup("Not yet", f"You can clock out from {core.CLOCKOUT_OPTION_TIME}.", C["muted"]); return
        dlg = WToplevel(self.root); dlg.title("Clock out"); dlg.attributes("-topmost", True)
        dlg.geometry("360x210")
        WLabel(dlg, "🕗 Clock out for the night?", size=16, bold=True, color=C["gold"]).pack(pady=(18, 6))
        WLabel(dlg, "Blocking and nagging switch off until tomorrow.\nYou can't undo it tonight.",
               size=10, color=C["muted"]).pack()
        def yes():
            dlg.destroy()
            self._do_clock_out()
        WButton(dlg, "Yes, clock out", yes, "gold").pack(pady=(14, 3))
        WButton(dlg, "Not yet", dlg.destroy, "sec").pack(pady=3)

    def _do_clock_out(self):
        now = time.time()
        if not core.clock_out(self.st, now):
            return False
        self._save(); self._enforce_async()
        self.refresh_ui()
        return True

    def complete_session(self):
        self.session_active = False
        self.session_paused = False
        self.notifier.stop()
        self._maybe_reset_cheat_day()
        was_ok = not core.burnout(self.st)
        self.st["time_bank_minutes"] = self.st.get("time_bank_minutes", 0) + core.SESSION_REWARD_MIN
        self.st["cheat_index"] = 0        # reward: 5 cheats back
        self.st["studied_today_min"] = self.st.get("studied_today_min", 0) + int(self.st.get("session_length_min", 45))
        self._save()
        beeps(3, 1100, 160)
        self._popup("Session complete! 🎉",
                    f"+{core.SESSION_REWARD_MIN} min banked (total {self.st['time_bank_minutes']:.0f}).\n"
                    "Your 5 cheat breaks are back.", C["green"])
        # burnout guard: if this session pushed you over the daily cap, tell you to rest
        if was_ok and core.burnout(self.st):
            play_chime()
            self._popup("🌿 That's enough for today",
                        f"You've hit your {self.st['daily_study_cap_min']}-min study goal. "
                        "Rest — the nagging is off now.", C["green"])
        self.refresh_ui()

    def _is_doomscrolling(self):
        proc, title = foreground_raw()
        if proc not in BROWSERS or not title:
            return False
        return any(k.lower() in title for k in self.st.get("doomscroll_keywords", ["shorts"]))

    def go_nuclear(self):
        if core.nuclear(self.st):
            self._popup("☢ Already nuclear", f"{fmt(self.st['nuclear_until'] - time.time())} of lockdown left.",
                        C["danger"]); return
        dlg = WToplevel(self.root); dlg.title("Go nuclear"); dlg.attributes("-topmost", True)
        dlg.geometry("360x330")
        WLabel(dlg, "☢ TOTAL LOCKDOWN", size=16, bold=True, color=C["danger"]).pack(pady=(18, 6))
        WLabel(dlg, "Blocks everything and disables EVERY escape —\nno cheat, no bank, no games, no "
                    "code — until the timer ends.\nThere is no way to cancel it. Choose wisely.",
               size=10, color=C["muted"]).pack()
        def arm(mins, rest=False):
            self._arm_nuclear(mins, rest)
            dlg.destroy()
            self._popup("☢ Nuclear armed", "Total lockdown engaged. Go do something real.", C["danger"])
        for label, mins in [("30 minutes", 30), ("1 hour", 60), ("2 hours", 120), ("4 hours", 240)]:
            WButton(dlg, label, lambda m=mins: arm(m), "danger").pack(pady=3)
        WButton(dlg, "Rest of the day", lambda: arm(0, rest=True), "danger").pack(pady=3)
        WButton(dlg, "Cancel", dlg.destroy, "sec").pack(pady=(8, 0))

    def _arm_nuclear(self, mins, rest=False):
        """Start (or extend) the lockdown. It can only ever get LONGER: a second dialog left
        open must not be able to shorten a lockdown that is already running."""
        now = time.time()
        until = core.next_midnight(now) if rest else now + mins * 60
        self.st["nuclear_until"] = max(until, self.st.get("nuclear_until", 0))
        self._save(); self._enforce_async()
        self.refresh_ui()
        return self.st["nuclear_until"]

    def _nuke_guard(self):
        if core.nuclear(self.st):
            when = datetime.fromtimestamp(self.st["nuclear_until"]).strftime("%H:%M")
            self._popup("☢ Nuclear lockdown", f"No escapes until {when}. That was the deal.", C["danger"])
            return True
        return False

    def _session_guard(self):
        """Block every break-granting action while a study session is running — otherwise
        you could click Cheat/Bank/Steam/day-off mid-session and get free browsing while
        the status still shows STUDY, which defeats the whole point of locking in."""
        if self.session_active:
            self._popup("You're in a session", "Stop or finish your session first — no breaks while locked in.",
                        C["danger"])
            return True
        return False

    def cheat_break(self):
        if self._nuke_guard() or self._session_guard():
            return
        now = time.time()
        if not core.within_schedule(self.st, now) or core.clocked_out(self.st, now):
            self._popup("Nothing to cheat", "Sites are already free right now.", C["muted"]); return
        if self.st.get("unlock_until", 0) > now:
            self._popup("Already on a break", "You're already free — no need to burn another cheat.", C["muted"]); return
        self._maybe_reset_cheat_day()
        idx = min(self.st.get("cheat_index", 0), len(core.CHEAT_LADDER) - 1)
        mins = core.CHEAT_LADDER[idx]
        if mins <= 0:
            self._popup("No cheats left today",
                        "You've used all 5. Finish a study session to get them back.", C["danger"]); return
        self.st["cheat_index"] = min(idx + 1, len(core.CHEAT_LADDER) - 1)
        self.st["unlock_until"] = now + mins * 60
        self._save(); self._enforce_async()
        left = sum(1 for m in core.CHEAT_LADDER[idx + 1:] if m > 0)
        # play a notification + voice so a cheat never feels free
        self.notifier.update(2, f"⚡ CHEAT BREAK · {mins} min",
                             f"Burning earned time — {left} cheat(s) left today.",
                             voice_lines=self.CHEAT_LINES)
        self._play_until = now + 4
        self.refresh_ui()

    def spend_bank(self):
        if self._nuke_guard() or self._session_guard():
            return
        bank = self.st.get("time_bank_minutes", 0)
        if bank < 1:
            self._popup("Bank empty", "Finish a study session to earn break time.", C["danger"]); return
        now = time.time()
        if self.st.get("unlock_until", 0) > now:
            self._popup("Already on a break", "You're already free — save your banked time.", C["muted"]); return
        since = now - self.st.get("bank_last_break", 0)
        cd = core.BANK_COOLDOWN_MIN * 60
        if since < cd:
            self._popup("Bank on cooldown", f"Wait {fmt(cd - since)} before another bank break — "
                        "no chaining them back-to-back.", C["danger"]); return
        dlg = WToplevel(self.root); dlg.title("Spend bank time"); dlg.attributes("-topmost", True)
        dlg.geometry("320x260")
        WLabel(dlg, f"You have {bank:.0f} min banked", size=14, bold=True, color=C["gold"]).pack(pady=(18, 8))
        WLabel(dlg, "Open the sites for how long?", bg=C["bg"]).pack()
        def grant(m):
            if self._grant_bank(m):
                dlg.destroy()
        for m in (5, 15, 30):
            if bank >= m:
                WButton(dlg, f"{m} min", lambda mm=m: grant(mm), "gold").pack(pady=4)
        WButton(dlg, f"All ({bank:.0f} min)", lambda: grant(bank), "sec").pack(pady=4)

    def _grant_bank(self, minutes):
        """Turn banked minutes into a break. Re-checks everything (the dialog may have been
        open a while): no break during a session/nuclear/existing break, never more than the
        balance, and never within BANK_COOLDOWN_MIN of the last bank break — otherwise you could
        chain bank breaks back-to-back for effectively unlimited free time."""
        if core.nuclear(self.st) or self.session_active:
            return False
        now = time.time()
        if self.st.get("unlock_until", 0) > now:
            return False
        if now - self.st.get("bank_last_break", 0) < core.BANK_COOLDOWN_MIN * 60:
            return False
        m = min(minutes, self.st.get("time_bank_minutes", 0))
        if m <= 0:
            return False
        self.st["time_bank_minutes"] -= m
        self.st["unlock_until"] = now + m * 60
        self.st["bank_last_break"] = now
        self._save(); self._enforce_async()
        self.refresh_ui()
        return True

    def steam_break(self):
        if self._nuke_guard() or self._session_guard():
            return
        now = time.time()
        if not core.within_schedule(self.st, now) or core.clocked_out(self.st, now):
            self._popup("Games already free", "It's outside your active hours — nothing is blocked.", C["muted"]); return
        cd = self.st.get("steam_cooldown_min", 90) * 60
        since = now - self.st.get("steam_last_break", 0)
        if self.st.get("steam_break_until", 0) > now:
            self._popup("Games already open", f"{fmt(self.st['steam_break_until']-now)} left.", C["cyan"]); return
        if since < cd:
            self._popup("Gaming on cooldown", f"Wait {fmt(cd - since)} for another gaming break.", C["danger"]); return
        mins = self.st.get("steam_break_min", 30)
        self.st["steam_break_until"] = now + mins * 60
        self.st["steam_last_break"] = now
        self._save()
        self.notifier.update(2, f"🎮 GAMING BREAK · {mins} min",
                             "Game on — it re-locks when the timer ends.",
                             voice_lines=[f"Gaming break. {mins} minutes.",
                                          "Back to studying after."])
        self._play_until = now + 4
        self.refresh_ui()

    # ---------------- learning break (approved YouTube videos only) ----------------
    def learning_break(self):
        if self._nuke_guard() or self._session_guard():
            return
        now = time.time()
        if not core.within_schedule(self.st, now) or core.clocked_out(self.st, now):
            self._popup("YouTube already free", "It's outside your active hours — nothing is blocked.", C["muted"]); return
        if self.st.get("unlock_until", 0) > now:
            self._popup("Already on a break", "Everything is open right now — no need for a learning break.",
                        C["muted"]); return
        if core.learning_active(self.st, now):
            self._popup("Learning break running", f"{fmt(self.st['learning_until'] - now)} left.", C["cyan"]); return
        self._maybe_reset_cheat_day()
        used = int(self.st.get("learning_used", 0))
        if used >= core.LEARNING_BREAKS_PER_DAY:
            self._popup("No learning breaks left today",
                        f"You've used all {core.LEARNING_BREAKS_PER_DAY}. They come back tomorrow.", C["danger"]); return
        if not core.approved_phrases(self.st, now):
            waiting = bool(self.st.get("learning_approved"))
            self._popup("Nothing approved yet",
                        (f"Your approvals are still in their {core.LEARNING_APPROVAL_DELAY_MIN}-minute "
                         "waiting period." if waiting else
                         "Approve a video first (Learning tab). Approvals start counting after "
                         f"{core.LEARNING_APPROVAL_DELAY_MIN} minutes."), C["danger"]); return
        mins = core.LEARNING_BREAK_MIN
        self.st["learning_until"] = now + mins * 60
        self.st["learning_used"] = used + 1
        self._lt_bad_since = None
        self._save(); self._enforce_async()
        left = core.LEARNING_BREAKS_PER_DAY - (used + 1)
        self._popup("📚 Learning break", f"YouTube is open for {mins} min — approved videos only; "
                    f"anything else closes after {core.LEARNING_GRACE_SEC}s. {left} left today.", C["cyan"])
        self._render_learning()
        self.refresh_ui()

    def _learning_enforce(self, now, proc, title):
        """During a learning break, close the foreground YouTube tab unless its title contains an
        approved phrase. The hosts file can only open or close ALL of YouTube, so this is what
        makes it per-video. A page that is still loading shows a placeholder title, and a freshly
        opened tab shouldn't be killed for that, hence the grace period."""
        title = str(title).lower()
        if (not core.youtube_open(self.st, now) or proc not in BROWSERS
                or not title or "youtube" not in title):
            self._lt_bad_since = None
            return
        if core.title_allowed(self.st, title, now):
            self._lt_bad_since = None
            return
        if self._lt_bad_since is None:
            self._lt_bad_since = now
            return
        if now - self._lt_bad_since >= core.LEARNING_GRACE_SEC and now - self._last_tabclose >= 2:
            self._last_tabclose = now
            self._lt_bad_since = None
            beeps(2, 600, 120)
            send_ctrl_w()

    def _close_pip(self, now):
        """Close any browser Picture-in-Picture window while sites are being blocked. A PiP window
        keeps a video playing outside every tab, so the tab-title checks can't see it, and its title
        never says what is playing, so there is nothing to approve: it is closed even during a
        learning break or audiobook. Free time (outside hours, clock-out, a break) leaves it alone."""
        if now - self._last_pipcheck < 2:
            return
        self._last_pipcheck = now
        if not core.pip_blocked(self.st, now):
            return
        for hwnd in find_pip_windows():
            close_window(hwnd)
            core.log_event("closed a Picture-in-Picture window")

    def add_approval(self):
        raw = self.l_entry.get()
        if core.looks_like_link(raw):
            set_label(self.l_msg, "That's a link. Approvals match the video's TITLE as shown on the tab "
                      "(open the video, read its title, and type a few of its words).", C["danger"]); return
        phrase = core.normalize_phrase(raw)
        if phrase is None:
            set_label(self.l_msg, f"Use at least {core.LEARNING_MIN_PHRASE} characters of the video's "
                      "title (not just \"youtube\").", C["danger"]); return
        approved = core.clean_approvals(self.st.get("learning_approved"))
        if any(e["phrase"] == phrase for e in approved):
            set_label(self.l_msg, f"\"{phrase}\" is already on the list.", C["muted"]); return
        entry = {"phrase": phrase, "added": time.time()}
        always = bool(self.l_always.get())
        if always:
            if len(phrase.replace(" ", "")) < core.LEARNING_MIN_PHRASE_ALWAYS:
                set_label(self.l_msg, f"An audiobook entry needs at least {core.LEARNING_MIN_PHRASE_ALWAYS} "
                          "characters of the title, so it can't match half of YouTube.", C["danger"]); return
            if sum(1 for e in approved if e.get("always")) >= core.LEARNING_MAX_ALWAYS:
                set_label(self.l_msg, f"You can have at most {core.LEARNING_MAX_ALWAYS} no-limit audiobooks "
                          "at once — remove one first.", C["danger"]); return
            entry["always"] = True
        approved.append(entry)
        self.st["learning_approved"] = approved
        self._save()
        self._set_entry(self.l_entry, "")
        self.l_always.set(0)
        self._render_learning()
        kind = "no time limit" if always else "for learning breaks"
        set_label(self.l_msg, f"Approved \"{phrase}\" ({kind}) — it starts counting in "
                  f"{core.LEARNING_APPROVAL_DELAY_MIN} min.", C["green"])

    def remove_approval(self, phrase):
        """Removing an approval makes things stricter, so it works immediately."""
        self.st["learning_approved"] = [e for e in core.clean_approvals(self.st.get("learning_approved"))
                                        if e["phrase"] != phrase]
        self._save()
        self._render_learning()
        set_label(self.l_msg, f"Removed \"{phrase}\".", C["muted"])

    def _render_learning(self):
        try:
            now = time.time()
            left = max(0, core.LEARNING_BREAKS_PER_DAY - int(self.st.get("learning_used", 0)))
            if core.learning_active(self.st, now):
                set_label(self.l_status, f"📚 Learning break running — {fmt(self.st['learning_until'] - now)} left",
                          C["cyan"])
            elif core.always_phrases(self.st, now):
                set_label(self.l_status, "🎧 Audiobook mode — YouTube is open for your audiobook titles only "
                          f"({left} learning break{'s' if left != 1 else ''} left today)", C["cyan"])
            else:
                set_label(self.l_status, f"{left} learning break{'s' if left != 1 else ''} left today "
                          f"({core.LEARNING_BREAK_MIN} min each)", C["muted"])
            for w in self.l_list.winfo_children():
                w.destroy()
            approved = sorted(core.clean_approvals(self.st.get("learning_approved")), key=lambda e: e["added"])
            if not approved:
                WLabel(self.l_list, "Nothing approved yet.", color=C["muted"], bg=C["bg"]).pack(anchor="w", pady=4)
            for e in approved:
                row = WFrame(self.l_list, color=C["bg"], radius=0); row.pack(fill="x", pady=2)
                wait = core.approval_ready_at(e) - now
                state, col = ("✓ active", C["green"]) if wait <= 0 else (f"active in {fmt(wait)}", C["muted"])
                WButton(row, "✕", lambda p=e["phrase"]: self.remove_approval(p), "ghost", small=True,
                        width=34).pack(side="right")
                WLabel(row, state, size=10, color=col, bg=C["bg"]).pack(side="right", padx=8)
                WLabel(row, ("🎧 " if e.get("always") else "") + e["phrase"][:44], size=11,
                       bg=C["bg"]).pack(side="left")
        except tk.TclError:
            pass          # the window is being torn down

    def disable_dialog(self):
        if self._nuke_guard() or self._session_guard():
            return
        now = time.time()
        if self.st.get("unlock_until", 0) > now:
            self._popup("Already on a break", "You're already free right now.", C["muted"]); return
        if not core.within_schedule(self.st, now) or core.clocked_out(self.st, now):
            self._popup("Already free", "It's outside your active hours — nothing is blocked.", C["muted"]); return
        self.secret = f"{random.randint(0, 999):03d}"
        dlg = WToplevel(self.root); dlg.title("Disable for today"); dlg.attributes("-topmost", True)
        dlg.geometry("360x270")
        WLabel(dlg, "Guess the 3-digit code", size=15, bold=True, color=C["danger"]).pack(pady=(18, 4))
        WLabel(dlg, "Correct = a break until midnight — same rule as everything\n"
                    "else: only a break unblocks you. The code re-rolls on every miss.",
               size=10, color=C["muted"]).pack()
        ent = WEntry(dlg, 6); ent.pack(pady=12)
        try:
            ent.focus_set()
        except Exception:
            pass
        msg = WLabel(dlg, "", size=9, color=C["danger"]); msg.pack()
        def attempt():
            if self._try_code(ent.get()):
                dlg.destroy()
                self._popup("🌴 Break until midnight", "You cracked it. That's a break, same as any other.", C["gold"])
            else:
                try:
                    ent.delete(0, "end")
                except Exception:
                    pass
                set_label(msg, "Wrong. New number generated. Try again.")
                beeps(1, 300, 120)
        ent.bind("<Return>", lambda e: attempt())
        WButton(dlg, "Try", attempt, "danger").pack(pady=10)

    def _try_code(self, guess):
        """One guess at the day-off code. Right = a break until midnight; wrong = the code re-rolls."""
        allowed = not self.session_active and not core.nuclear(self.st)
        if allowed and self.secret is not None and str(guess).strip() == self.secret:
            self.st["unlock_until"] = core.next_midnight(time.time())
            self.secret = None
            self._save(); self._enforce_async()
            self.refresh_ui()
            return True
        self.secret = f"{random.randint(0, 999):03d}"
        return False

    def _render_blocklist(self):
        try:
            self.set_block.configure(state="normal")
            self.set_block.delete("1.0", "end")
            self.set_block.insert("1.0", "\n".join(self.st.get("blocklist", [])))
            self.set_block.configure(state="disabled")   # read-only: removal isn't possible here
        except Exception:
            pass

    def add_blocked_site(self):
        d = core.normalize_domain(self.add_site.get())
        if not d:
            set_label(self.set_msg, "That doesn't look like a site (try example.com).", C["danger"]); return
        sites = list(self.st.get("blocklist", []))
        if d in [s.lower() for s in sites]:
            set_label(self.set_msg, f"{d} is already blocked.", C["muted"]); return
        sites.append(d)
        self.st["blocklist"] = sites
        self._save()
        if core.sites_blocked(self.st):
            self._enforce_async(refresh=True)
        self._render_blocklist()
        self._set_entry(self.add_site, "")
        set_label(self.set_msg, f"Added {d}.", C["green"])

    SETTING_MAX = 1440      # minutes (24h) — keeps absurd values from breaking timers and clocks

    # a setting may only move in the "stricter" direction; 0 counts as unlimited for the cap
    LOCKED_DIR = {"session_length_min": "up", "daily_study_cap_min": "up",
                  "steam_cooldown_min": "up", "snooze_min": "down", "steam_break_min": "down"}

    def _loosens(self, key, old, new):
        d = self.LOCKED_DIR.get(key)
        if d is None:
            return False
        if key == "daily_study_cap_min":         # 0 = no cap = strictest
            old = float("inf") if old == 0 else old
            new = float("inf") if new == 0 else new
        return new < old if d == "up" else new > old

    def save_settings(self):
        try:
            new = {k: int(float(ent.get().strip())) for k, ent in self.set_entries.items()}
            for k, v in new.items():
                if not 0 <= v <= self.SETTING_MAX:
                    raise ValueError(f"{k} must be between 0 and {self.SETTING_MAX}")
                old = int(self.st.get(k, v))
                if k == "session_length_min" and v < core.MIN_SESSION_MIN:
                    self._set_entry(self.set_entries[k], str(old))
                    set_label(self.set_msg, f"Study sessions must be at least {core.MIN_SESSION_MIN} minutes.",
                              C["danger"])
                    return
                if self._loosens(k, old, v):
                    way = "raised" if self.LOCKED_DIR[k] == "up" else "lowered"
                    self._set_entry(self.set_entries[k], str(old))
                    set_label(self.set_msg, f"Locked: that setting can only be {way}, never the other way.",
                              C["danger"])
                    return
            self.st.update(new)
            self.st["strobe_enabled"] = bool(self.strobe_var.get())
            for key, (var, _l) in self.slider_widgets.items():
                self.st[key] = int(var.get())
            self._apply_notif_settings()
            self._save()
            self._enforce_async(refresh=core.sites_blocked(self.st))
            set_label(self.set_msg, "Saved.", C["green"])
        except Exception as ex:
            set_label(self.set_msg, f"Bad value: {ex}", C["danger"])

    def _popup(self, title, body, color):
        dlg = WToplevel(self.root); dlg.title(title); dlg.attributes("-topmost", True)
        dlg.geometry("360x200")
        WLabel(dlg, title, size=15, bold=True, color=color).pack(pady=(20, 8))
        WLabel(dlg, body, size=11, bg=C["bg"]).pack(padx=16)
        WButton(dlg, "OK", dlg.destroy, "primary").pack(pady=16)

    # ---------------- loops ----------------
    def _enforce_async(self, refresh=False):
        """Run enforcement (hosts file, DNS flush, closing launchers) on a worker thread so the
        window never waits on disk or a subprocess. Requests that arrive while one is running
        are coalesced into one more pass."""
        if refresh:
            self._enforce_refresh = True
        if self._enforce_busy:
            self._enforce_again = True
            return
        self._enforce_busy = True
        def run():
            try:
                while True:
                    self._enforce_again = False
                    try:
                        if self._enforce_refresh:
                            self._enforce_refresh = False
                            core.refresh_hosts_block(self.st)
                        core.apply_enforcement(self.st)
                    except Exception:
                        pass
                    if not self._enforce_again:
                        break
            finally:
                self._enforce_busy = False
        threading.Thread(target=run, daemon=True).start()

    def _enforce_loop(self):
        self._enforce_async()
        self.root.after(3000, self._enforce_loop)

    def _tick(self):
        """Once a second. An error inside one pass must never stop the loop (it drives the
        session timer, nags and tab closing), so the next tick is always rescheduled."""
        self._watchdog.beat()                 # "the window is alive" signal for the freeze watchdog
        try:
            self._tick_body()
        except Exception as ex:
            self._tick_errors += 1
            self._last_tick_error = repr(ex)
            if self._tick_errors <= 20 or self._tick_errors % 100 == 0:
                core.log_event(f"tick error #{self._tick_errors}: {ex!r}\n{traceback.format_exc()}")
        finally:
            self._watchdog.beat()
            try:
                self.root.after(1000, self._tick)
            except Exception:
                pass      # the window is gone (app is quitting)

    def _tick_body(self):
        self.clock += 1
        now = time.time()
        # real elapsed time since the last tick (capped, so a sleeping laptop or a UI stall
        # neither freezes the session timer nor lets it jump ahead)
        mono = time.monotonic()
        dt = 1.0 if self._last_tick_mono is None else min(max(mono - self._last_tick_mono, 0.0), 3.0)
        self._last_tick_mono = mono

        self._maybe_reset_cheat_day()

        # clock-out announcement (once, when the workday's evening cutoff passes)
        co = core.clocked_out(self.st, now)
        if co and not self._clocked_prev:
            self.notifier.stop(); self._last_nag_at = None
            play_chime()
            say("You're clocked out. Step away and relax.")
            self._popup("🕗 Clocked out", "Workday's over — you're done for today.\nStep away and relax.", C["green"])
        self._clocked_prev = co
        today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if core.clockout_option_available(self.st, now) and self._clockout_offered != today:
            self._clockout_offered = today
            self._popup("🕗 You can clock out", f"It's {core.CLOCKOUT_OPTION_TIME} — if you're done for the "
                        "night, tap 🕗 Clock out.", C["gold"])

        # one foreground query per tick, reused by the tab closers and the doomscroll tax
        proc, title = foreground_raw()

        # auto-close a blocked site if it's the foreground tab while blocking is active. During a
        # learning break YouTube is not on the list being enforced; its own rule is below.
        if (proc in BROWSERS and title and now - self._last_tabclose >= 2
                and core.sites_blocked(self.st, now)):
            if any(k in title for k in core.blocked_title_keywords(self.st, now)):
                self._last_tabclose = now
                send_ctrl_w()
        self._learning_enforce(now, proc, title)
        self._close_pip(now)

        # doomscroll tax: each scroll on Shorts/Reels/TikTok = minutes off the bank (into debt)
        new_scrolls = self.scroll.count - self._last_scroll
        self._last_scroll = self.scroll.count
        self.doom_active = bool(proc in BROWSERS and title and
                                any(k.lower() in title for k in self.st.get("doomscroll_keywords", ["shorts"])))
        if self.doom_active:
            self._hook_until = now + 5           # keep the hook a few seconds past the last match
        self.scroll.set_active(now < self._hook_until)
        if new_scrolls > 0 and self.doom_active:
            pen = new_scrolls * self.st.get("doomscroll_penalty_min", 1)
            self.st["time_bank_minutes"] = self.st.get("time_bank_minutes", 0) - pen
            self._doom_flash = self.clock
            self._save()
            beeps(1, 200, 90)

        # auto-read a random reminder aloud on the chosen interval
        ri = self.st.get("reminder_interval_min", 0)
        if ri > 0 and self.clock > 0 and self.clock % (ri * 60) == 0 and core.within_schedule(self.st, now):
            lines = self._reminder_lines()
            if lines:
                say(random.choice(lines), voice=self.st.get("reminder_voice") or None)

        # detect a break ending -> re-block IMMEDIATELY, then snap you back with an alert
        break_active = self.st.get("unlock_until", 0) > now
        steam_active = self.st.get("steam_break_until", 0) > now
        learn_active = self.st.get("learning_until", 0) > now
        break_just_ended = ((self._break_prev and not break_active) or (self._steam_prev and not steam_active)
                            or (self._learn_prev and not learn_active))
        if break_just_ended:
            self._enforce_async()                      # don't wait for the next enforce tick
        can_nag = (not self.session_active and core.within_schedule(self.st, now)
                   and not core.clocked_out(self.st, now) and not core.nuclear(self.st, now))
        if can_nag and break_just_ended:
            if self._steam_prev and not steam_active:
                over_kind = "GAMES OVER"
            elif self._learn_prev and not learn_active:
                over_kind = "LEARNING OVER"
            else:
                over_kind = "BREAK OVER"
            self.notifier.update(3, f"⏰ {over_kind}", "Time's up — back to work.",
                                 voice_lines=["Break is over.", "Back to work now."])
            self._last_nag_at = self.clock
            self._noses_start = now - 30   # keep the pressure high right after a break
        self._break_prev = break_active
        self._steam_prev = steam_active
        self._learn_prev = learn_active

        if self.session_active:
            if self.session_manual_paused:
                self.session_paused = True
                # nag (with the annoying voices) the whole time you're paused
                if self._pause_start is None:
                    self._pause_start = now
                self._maybe_nag(now - self._pause_start, "RESUME YOUR SESSION",
                                "You paused — pausing isn't a free pass. Resume.",
                                floor_level=1, voice_lines=self.RESUME_LINES)
            else:
                self.session_paused = False
                self._pause_start = None
                self.notifier.stop(); self._last_nag_at = None
                self.session_remaining -= dt
                if self.session_remaining <= 0:
                    self.complete_session()
        else:
            blocking = (core.within_schedule(self.st, now) and not core.clocked_out(self.st, now)
                        and not core.nuclear(self.st, now) and self.st.get("unlock_until", 0) <= now
                        and self.st.get("steam_break_until", 0) <= now
                        and self.st.get("learning_until", 0) <= now)
            snoozed = self.st.get("snooze_until", 0) > now
            if blocking and not snoozed and not core.burnout(self.st) and self.nag_frequency >= 2:
                if self._noses_start is None:
                    self._noses_start = now
                # escalates by how long you've been on the clock WITHOUT a session
                # (voicelines begin around ~30s in)
                over = now - self._noses_start
                self._maybe_nag(over, "START A SESSION", "You're on the clock — start a session NOW.",
                                voice_lines=self.START_LINES)
            elif now < self._play_until:
                pass  # let a transient play (e.g. cheat-break alert) finish
            else:
                self.notifier.stop(); self._last_nag_at = None; self._noses_start = None

        self.refresh_ui()

    def _level(self, over):
        if over < 8:   return 0
        if over < 25:  return 1
        if over < 70:  return 2
        if over < 150: return 3
        if over < 300: return 4
        return 5

    def _interval(self, over):
        if over < 8:   return 6
        if over < 25:  return 4
        if over < 70:  return 3
        if over < 150: return 2
        return 1

    NAG_SCALE = {1: 2.5, 2: 1.6, 3: 1.0, 4: 0.6, 5: 0.35}

    def _maybe_nag(self, over, headline, subtext, floor_level=0, cap_level=5,
                   force_interval=None, voice_lines=None):
        level = max(floor_level, min(self._level(over), cap_level))
        base = force_interval if force_interval is not None else self._interval(over)
        scale = self.NAG_SCALE.get(self.nag_frequency, 1.0)
        itv = max(1, int(round(base * scale)))
        if self._last_nag_at is None or (self.clock - self._last_nag_at) >= itv:
            self._last_nag_at = self.clock
            self.notifier.update(level, headline, subtext, voice_lines=voice_lines)

    def run(self):
        self.root.mainloop()


def main():
    if not core.is_admin():
        if core.IS_WIN:
            core.relaunch_as_admin(); return
        print("Note: not running as root - blocking edits /etc/hosts, so start it with sudo "
              "for the block to take effect.")
    if not core.claim_app_instance():
        return      # Focus is already running (the guard relaunches it if it ever closes)
    core.scrub_state_file()      # drop saved data from removed features (the old usage history)
    core.apply_enforcement(core.load_state())
    FocusApp().run()


if __name__ == "__main__":
    main()
