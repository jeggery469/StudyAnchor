"""
core.py - shared engine for the StudyAnchor app.

Holds everything the GUI (focusapp.py) and the headless enforcer (guard.py) both
need: the shared state file, the block list, hosts-file editing, Steam killing,
the schedule check, and the single apply_enforcement() that makes the machine
match the current state.

State lives in C:\\ProgramData\\FocusTool\\state.json so that both the guard task and
the (elevated) app can read/write it.
"""

import math
import os
import sys
import json
import time
import tempfile
import threading
import subprocess
from datetime import datetime, timedelta

# ----------------------------- platform -----------------------------

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0

if IS_WIN:
    import ctypes

# ----------------------------- paths -----------------------------

if IS_WIN:
    DATA_DIR = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "FocusTool")
else:
    # a shared spot both a root helper and the user app can read
    DATA_DIR = "/usr/local/share/FocusTool" if os.access("/usr/local/share", os.W_OK) \
        else os.path.expanduser("~/.focustool")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

def _ensure_dir():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass

# ----------------------------- block list -----------------------------

DEFAULT_BLOCKLIST = [
    # video / social
    "instagram.com", "tiktok.com", "youtube.com", "youtu.be", "facebook.com",
    "reddit.com", "old.reddit.com", "redd.it", "twitter.com", "x.com", "snapchat.com",
    "pinterest.com", "twitch.tv", "tumblr.com", "9gag.com",
    # streaming
    "netflix.com", "hulu.com", "disneyplus.com", "primevideo.com", "iyf.tv",
    "bilibili.com", "bilibili.tv", "b23.tv", "space.bilibili.com", "live.bilibili.com",
    "search.bilibili.com", "t.bilibili.com",
    # communities / shopping / games
    "fandom.com", "minecraft.net", "minecraft.wiki", "minecraftforum.net", "amazon.com",
]

# Sites that were blocked by mistake (or that you decided you need) and must be actively
# removed from anyone's saved blocklist, not just left out of new installs (the blocklist is
# otherwise add-only, so this is the one deliberate exception to that rule).
# archive.org: the Internet Archive is where the audiobooks and textbooks come from. The hosts
# file can only block a whole domain, so it can't block just its movies and keep the books.
MISTAKENLY_BLOCKED = ["discord.com", "discord.gg", "gateway.discord.gg", "discordapp.com",
                      "cdn.discordapp.com", "discordapp.net", "media.discordapp.net",
                      "archive.org"]

def normalize_domain(raw):
    """'https://www.Site.com/path?x' -> 'site.com'; None for anything that isn't a hostname
    (spaces, IP addresses, bare words like 'localhost', junk). Non-ASCII names become punycode."""
    d = str(raw).strip().lower()
    for pre in ("https://", "http://"):
        if d.startswith(pre):
            d = d[len(pre):]
    d = d.split("/")[0].split("?")[0].split("#")[0].split(":")[0].strip(".")
    if d.startswith("www."):
        d = d[4:]
    if d and not d.isascii():
        try:
            d = d.encode("idna").decode("ascii")
        except Exception:
            return None
    labels = d.split(".")
    if len(d) > 253 or len(labels) < 2 or not all(labels):
        return None
    for lab in labels:
        bad_edge = lab.startswith("-") or lab.endswith("-")
        bad_chars = not all(ch.isascii() and (ch.isalnum() or ch == "-") for ch in lab)
        if len(lab) > 63 or bad_edge or bad_chars:
            return None
    if not labels[-1].isalpha() and not labels[-1].startswith("xn--"):
        return None          # rejects IP addresses like 192.168.0.1
    return d

# Sites whose name is also an ordinary word: the tab auto-closer matches these on a more specific
# phrase, or an article about the Amazon rainforest / "National Archives" would get closed mid-read.
TITLE_OVERRIDES = {"amazon": ["amazon.com"], "archive": ["internet archive"]}

def title_keywords(blocklist):
    """Lowercase strings that identify a blocked site in a browser tab title. Uses the main
    site name (bilibili.com / search.bilibili.com -> "bilibili"), never a subdomain word like
    "search" or "space" that would match unrelated tabs."""
    out = set()
    for d in blocklist:
        parts = d.lower().strip(".").split(".")
        if len(parts) < 2:
            continue
        label = parts[-2]
        if label in TITLE_OVERRIDES:
            out.update(TITLE_OVERRIDES[label])
        elif len(label) >= 5:
            out.add(label)
    return sorted(out)

# Bing's video search plays YouTube (and others) inline on a page titled "<query> - Search Videos",
# which slips past the YouTube rules: the title never says "youtube" and the player is an embed.
# The hosts file can't block one path of bing.com (that would kill Bing search), so these tab-title
# fragments are closed whenever sites are blocked - learning breaks and audiobook mode included.
VIDEO_SEARCH_TITLES = ("search videos", "bing videos", "google videos")

def blocked_title_keywords(st, now=None):
    """Everything the tab auto-closer looks for in a browser tab title right now."""
    return sorted(set(title_keywords(effective_blocklist(st, now))) | set(VIDEO_SEARCH_TITLES))

# Every major PC game distribution client/launcher, by process name (Windows) — the
# gaming break gate isn't Steam-specific anymore, it covers whichever of these you have
# installed. Names are picked to be distinctive (deliberately skipping generic ones like
# a bare "Launcher.exe" that could false-positive-kill unrelated software).
GAME_LAUNCHER_PROCS = [
    # Steam
    "steam.exe", "steamwebhelper.exe", "steamservice.exe", "GameOverlayUI.exe",
    # Epic Games
    "EpicGamesLauncher.exe", "EpicWebHelper.exe",
    # Battle.net (Blizzard)
    "Battle.net.exe", "Blizzard Battle.net.exe", "BlizzardBrowser.exe",
    # Origin / EA app
    "Origin.exe", "EADesktop.exe", "EABackgroundService.exe", "EACefSubProcess.exe",
    # Ubisoft Connect
    "UbisoftConnect.exe", "upc.exe", "UplayWebCore.exe",
    # GOG Galaxy
    "GalaxyClient.exe", "GalaxyClientService.exe", "GalaxyCommunication.exe",
    # Xbox app / Game Bar
    "XboxApp.exe", "GameBar.exe", "GameBarFTServer.exe",
    # Riot Client (League of Legends, Valorant, ...)
    "RiotClientServices.exe", "RiotClientUx.exe", "RiotClientUxRender.exe",
    # Rockstar Games Launcher
    "RockstarService.exe", "RockstarErrorHandler.exe",
    # itch.io
    "itch.exe",
]
# macOS/Linux launcher clients, matched by EXACT process name (pkill -x). Never a substring of
# the command line: "origin" would also match `git push origin`, "steam" a browser tab, etc.
GAME_LAUNCHER_UNIX_NAMES = ["steam", "steamwebhelper", "steam_osx", "Steam Helper", "heroic",
                            "lutris", "Epic Games Launcher", "Battle.net", "Origin", "EABackgroundService"]

REDIRECT_IP = "0.0.0.0"
MARK_START = "# ==== FOCUS-BLOCK START (managed by Focus - do not edit) ===="
MARK_END = "# ==== FOCUS-BLOCK END ===="
if IS_WIN:
    HOSTS_PATH = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "drivers", "etc", "hosts")
else:
    HOSTS_PATH = "/etc/hosts"

# the always-available "cheat" break: five 5-minute cheats, then none until you finish a
# session or a new day resets them.
CHEAT_LADDER = [5, 5, 5, 0]
MIN_SESSION_MIN = 20             # a study session can never be set shorter than this (Settings and saved state)
SESSION_REWARD_MIN = 15          # banked minutes earned per completed study session
BANK_COOLDOWN_MIN = 5            # minutes between the START of one bank break and the next —
                                 # stops chaining bank breaks back-to-back for endless free time

# Learning break: YouTube opens for a while, but a YouTube tab is only allowed to stay open if its
# title contains a phrase you approved IN ADVANCE. (Blocking works per domain, so the hosts file
# can't tell one video from another — the app checks the tab you're looking at instead.)
LEARNING_BREAKS_PER_DAY = 2
LEARNING_BREAK_MIN = 45
LEARNING_APPROVAL_DELAY_MIN = 10   # a new approval only counts after this long: no impulse approvals
LEARNING_GRACE_SEC = 10            # a non-approved YouTube tab is closed after this long in front
LEARNING_UNBLOCKS = ("youtube.com", "youtu.be")   # the only domains a learning break opens
LEARNING_MIN_PHRASE = 4
# "Audiobook" approvals have no time limit and don't use up a learning break: while one is active,
# YouTube stays reachable and only those titles may stay open. Because that is much more open than a
# 45-minute break, they must be specific and there can only be a few.
LEARNING_MIN_PHRASE_ALWAYS = 8
LEARNING_MAX_ALWAYS = 3
# words found in EVERY browser window title; a phrase made of these would approve everything
_GENERIC_TITLE_TEXT = ("youtube - google chrome - microsoft edge - mozilla firefox - brave - opera - "
                       "profile 1 - audio playing - and more pages - new tab")

# ----------------------------- state -----------------------------

def default_state():
    return {
        "schedule_start": "07:00",
        "schedule_end": "00:00",       # midnight
        "weekend_schedule_start": "10:00",   # Saturday/Sunday get their own, shorter window
        "weekend_schedule_end": "18:00",
        "tutorial_seen": False,        # the first-run walkthrough has been shown (or skipped)
        "clockout_manual_at": 0.0,     # epoch of tonight's voluntary clock-out (only valid if after CLOCKOUT_OPTION_TIME)
        "clockout_time": "23:59",      # after this each evening you're "clocked out" (free + told to relax); "" = off
        "unlock_until": 0.0,           # epoch: sites free until this time (cheat/bank break)
        "cheat_index": 0,              # index into CHEAT_LADDER
        "cheat_day": "",               # date the cheat ladder was last reset
        "nuclear_until": 0.0,          # epoch: TOTAL lockdown, no escapes, until this time
        "snooze_until": 0.0,           # epoch: pause the "start a session" nudges until here
        "time_bank_minutes": 0.0,      # earned break minutes (can go negative from doomscrolling)
        "bank_last_break": 0.0,        # epoch of last bank-break start (cooldown, like steam_last_break)
        "learning_until": 0.0,         # epoch: YouTube is open (approved videos only) until this time
        "learning_used": 0,            # learning breaks taken today (resets daily with the cheats)
        "learning_approved": [],       # [{"phrase": "python tutorial", "added": epoch}, ...]
        "steam_break_until": 0.0,      # epoch: steam allowed until this time
        "steam_last_break": 0.0,       # epoch of last steam break start (cooldown)
        "steam_break_min": 30,
        "steam_cooldown_min": 90,
        "session_length_min": 45,
        "snooze_min": 10,             # how long the 😴 snooze pauses the nudges
        "strobe_enabled": True,        # flashing strobe lights on high-level nags
        "max_voices": 4,              # how many TTS voices overlap at the peak
        "alarm_speed": 3,             # 1 (calm) .. 5 (relentless) beeping intensity
        "nag_frequency": 3,           # 1 (rare) .. 5 (relentless) how often nags fire
        "doomscroll_keywords": ["shorts", "reels", "tiktok"],  # window-title triggers
        "doomscroll_penalty_min": 1,  # bank minutes charged per scroll while doomscrolling
        "reminders": "- Put the phone down\n- Remember why you started\n- Future you is watching",
        "reminder_interval_min": 0,   # auto-read a random reminder every N min (0 = off)
        "reminder_voice": "",         # installed Windows voice name ("" = system default)
        "nag_own_words": True,        # speak your own reminders during the escalating nags
        "blocklist": list(DEFAULT_BLOCKLIST),
        # burnout guard: stop hounding you once you've studied enough today
        "daily_study_cap_min": 240,   # 0 = off
        "studied_today_min": 0,
        "studied_day": "",
        # NOTE: account/sync keys removed — the app is fully local now.
    }

LOCKED_KEYS = ("schedule_start", "schedule_end", "weekend_schedule_start", "weekend_schedule_end",
              "clockout_time")

# keys written by features that no longer exist; dropped on load so old state files don't carry them
OBSOLETE_KEYS = ("enabled", "day_off_until", "market", "go_outside_after_min", "go_outside_lock_min",
                 "screen_on_min", "account", "sync",
                 "usage")        # the Usage tab (and its record of which windows you used) was removed

def _coerce(default, value):
    """Keep a loaded value only if it has the same kind as the default (a hand-edited
    'unlock_until': 'abc' must not crash the enforcement loop)."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, (int, float)):
        is_num = isinstance(value, (int, float)) and not isinstance(value, bool)
        finite = is_num and value == value and value not in (float("inf"), float("-inf"))
        return value if finite else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    if isinstance(default, list):
        return value if isinstance(value, list) else default
    if isinstance(default, dict):
        return value if isinstance(value, dict) else default
    return value

def load_state():
    _ensure_dir()
    st = default_state()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return st
    if not isinstance(data, dict):
        return st
    for k, v in data.items():
        if k in OBSOLETE_KEYS:
            continue
        st[k] = _coerce(st[k], v) if k in st else v
    fixed = default_state()
    for k in LOCKED_KEYS:
        st[k] = fixed[k]        # the schedule is fixed in code, never taken from the saved file
    # a hand-edited state file can't shorten sessions below the floor either
    st["session_length_min"] = max(MIN_SESSION_MIN, int(st["session_length_min"]))
    # the blocklist only ever grows: every built-in site is always present, and sites added
    # later to the defaults reach existing installs automatically
    merged = []
    for d in list(st["blocklist"]) + list(DEFAULT_BLOCKLIST):
        d = normalize_domain(d) if isinstance(d, str) else None
        if d and d not in merged and d not in MISTAKENLY_BLOCKED:
            merged.append(d)
    st["blocklist"] = merged
    st["learning_approved"] = clean_approvals(st.get("learning_approved"))
    return st

def scrub_state_file():
    """Rewrite the saved state if it still holds data from features that were removed (e.g. the old
    'usage' record of which windows you used), so nothing lingers on disk until some later save.
    Only the running app calls this, at startup, so it can't race another writer. True if it rewrote."""
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return False
    if not isinstance(raw, dict) or not any(k in raw for k in OBSOLETE_KEYS):
        return False
    return save_state(load_state())

def save_state(st):
    """Atomic write (temp file + replace). Returns True on success."""
    _ensure_dir()
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
        os.replace(tmp, STATE_PATH)
        return True
    except Exception:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False

# ----------------------------- diagnostics log -----------------------------

LOG_MAX_BYTES = 256 * 1024
_log_lock = threading.Lock()

def log_path():
    return os.path.join(DATA_DIR, "focus.log")

def log_event(message):
    """Append a timestamped line to focus.log (kept under ~512 KB by rotating once). Used for the
    things that are otherwise invisible in a windowless app: crashes, freezes, restarts. It must
    never raise - a logging problem can't be allowed to cause one."""
    try:
        with _log_lock:
            _ensure_dir()
            path = log_path()
            try:
                if os.path.getsize(path) > LOG_MAX_BYTES:
                    os.replace(path, path + ".1")
            except OSError:
                pass
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except Exception:
        pass

# ----------------------------- elevation -----------------------------

def is_admin():
    try:
        if IS_WIN:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        return os.geteuid() == 0    # root on macOS/Linux
    except Exception:
        return False

def relaunch_as_admin():
    if IS_WIN:
        params = " ".join(f'"{a}"' for a in sys.argv)
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params,
            os.path.dirname(os.path.abspath(__file__)), 1)
        sys.exit(0)
    # macOS/Linux: editing /etc/hosts needs root — tell the user and carry on
    # (the app still runs; blocking writes just no-op without privileges).
    return

# ----------------------------- single instance + watchdog -----------------------------

APP_MUTEX = "Global\\FocusStudyApp"
_app_mutex = None

def claim_app_instance():
    """True if this is the only running Focus app (holds a named mutex for the process's life)."""
    global _app_mutex
    if not IS_WIN:
        return True
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    h = k.CreateMutexW(None, False, APP_MUTEX)
    if ctypes.get_last_error() in (183, 5):  # ALREADY_EXISTS / ACCESS_DENIED (owned by another session)
        return False
    _app_mutex = h
    return True

def release_app_instance():
    """Let go of the single-instance mutex (used right before the app restarts itself)."""
    global _app_mutex
    if not IS_WIN or not _app_mutex:
        return
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.CloseHandle(_app_mutex)
    _app_mutex = None

def app_running():
    if not IS_WIN:
        return True
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenMutexW.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenMutexW(0x00100000, False, APP_MUTEX)    # SYNCHRONIZE
    if h:
        k.CloseHandle(h)
        return True
    return False

def launch_app():
    """Start the Focus app detached (used by the guard when the app has been closed)."""
    if not IS_WIN:
        return False
    here = os.path.dirname(os.path.abspath(__file__))
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        exe = os.path.join(os.path.dirname(exe), "pythonw.exe")
    try:
        subprocess.Popen([exe, os.path.join(here, "focusapp.py")], cwd=here, close_fds=True,
                         creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | NEW_PROCESS_GROUP
        return True
    except Exception as ex:
        log_event(f"could not launch the app: {ex!r}")
        return False

# ----------------------------- schedule -----------------------------

def _hhmm_to_min(s):
    """'HH:MM' -> minutes after midnight; 0 for anything malformed or out of range."""
    try:
        h, m = str(s).split(":")
        h, m = int(h), int(m)
        return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else 0
    except Exception:
        return 0

def next_midnight(now=None):
    now = time.time() if now is None else now
    dt = datetime.fromtimestamp(now)
    nxt = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.timestamp()

SCHEDULE_MIN_HOURS = 8   # the active (blocked) window must cover at least this many hours

def schedule_hours(start_s, end_s):
    """Length of the active window in hours (handles overnight; equal = 24h always-on)."""
    sm = _hhmm_to_min(start_s)
    em = _hhmm_to_min(end_s)
    if sm == em:
        return 24.0
    return ((em - sm) % (24 * 60)) / 60.0

def is_weekend(now=None):
    now = time.time() if now is None else now
    return datetime.fromtimestamp(now).weekday() >= 5   # Saturday=5, Sunday=6

def today_schedule(st, now=None):
    """The (start, end) HH:MM strings that apply right now — Sat/Sun get their own window."""
    now = time.time() if now is None else now
    if is_weekend(now):
        return (st.get("weekend_schedule_start", "10:00"), st.get("weekend_schedule_end", "18:00"))
    return (st.get("schedule_start", "07:00"), st.get("schedule_end", "00:00"))

def within_schedule(st, now=None):
    now = time.time() if now is None else now
    lt = datetime.fromtimestamp(now)
    cur = lt.hour * 60 + lt.minute
    start_s, end_s = today_schedule(st, now)
    start = _hhmm_to_min(start_s)
    end = _hhmm_to_min(end_s)
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end     # overnight window

def next_schedule_start(st, now=None):
    """The HH:MM your active window next begins — today's, or tomorrow's if today's has
    already passed (which may be a different weekday/weekend window than today's)."""
    now = time.time() if now is None else now
    lt = datetime.fromtimestamp(now)
    cur = lt.hour * 60 + lt.minute
    start_s, _end_s = today_schedule(st, now)
    if cur < _hhmm_to_min(start_s):
        return start_s
    return today_schedule(st, now + 24 * 3600)[0]

def nuclear(st, now=None):
    now = time.time() if now is None else now
    return st.get("nuclear_until", 0) > now

def burnout(st):
    cap = st.get("daily_study_cap_min", 0)
    return cap > 0 and st.get("studied_today_min", 0) >= cap

CLOCKOUT_OPTION_TIME = "20:00"   # from this time you MAY clock out early; the automatic one is clockout_time

def _minute_of_day(ts):
    lt = datetime.fromtimestamp(ts)
    return lt.hour * 60 + lt.minute

def manual_clockout_active(st, now=None):
    """True if you chose to clock out tonight. It only counts if it was done on today's date, at
    or after CLOCKOUT_OPTION_TIME and not in the future - so a hand-edited state file can't
    clock you out at 10 in the morning - and it lapses on its own at midnight."""
    now = time.time() if now is None else now
    at = st.get("clockout_manual_at", 0)
    if not isinstance(at, (int, float)) or isinstance(at, bool) or not math.isfinite(at) or at <= 0 or at > now:
        return False
    try:
        if datetime.fromtimestamp(at).date() != datetime.fromtimestamp(now).date():
            return False
        return _minute_of_day(at) >= _hhmm_to_min(CLOCKOUT_OPTION_TIME)
    except (ValueError, OverflowError, OSError):     # a corrupt state file must never break the clock check
        return False

def clocked_out(st, now=None):
    """After the evening clock-out time (or once you clock out yourself from 20:00) you're done
    for the day (free, told to relax)."""
    now = time.time() if now is None else now
    if manual_clockout_active(st, now):
        return True
    t = st.get("clockout_time", "")
    if not t:
        return False
    return _minute_of_day(now) >= _hhmm_to_min(t)

def clockout_option_available(st, now=None):
    """You can clock out early from 20:00 until the automatic clock-out - but only while sites
    are actually being blocked (nothing to clock out of in free time) and never during nuclear."""
    now = time.time() if now is None else now
    if nuclear(st, now) or not within_schedule(st, now) or clocked_out(st, now):
        return False
    return _minute_of_day(now) >= _hhmm_to_min(CLOCKOUT_OPTION_TIME)

def clock_out(st, now=None):
    """Clock out for the night. Returns True if it happened, False if it isn't allowed right now."""
    now = time.time() if now is None else now
    if not clockout_option_available(st, now):
        return False
    st["clockout_manual_at"] = now
    return True

def sites_blocked(st, now=None):
    """Two legitimate ways to be free: it's outside your scheduled hours, or you're
    past your evening clock-out. Neither of those is a "bug" or a loophole — they're
    your own intentional boundaries. But WITHIN the schedule and before clock-out,
    blocking is now unconditional except an actual active break (unlock_until in the
    future) — the 'enabled' flag and the day-off code no longer create gaps there.
    Nuclear overrides even a break: it's stricter than everything else."""
    now = time.time() if now is None else now
    if nuclear(st, now):
        return True
    if not within_schedule(st, now):     # outside active hours — legitimately free
        return False
    if clocked_out(st, now):             # past your evening cutoff — legitimately free
        return False
    return st.get("unlock_until", 0) <= now   # in schedule: only an active break frees you

def pip_blocked(st, now=None):
    """Picture-in-Picture video windows are closed whenever sites are blocked, learning break and
    audiobook mode included (the window's title doesn't reveal what it is playing)."""
    return sites_blocked(st, now)

def steam_blocked(st, now=None):
    """Same rule as sites_blocked, for Steam: schedule + clock-out are the real
    boundaries; within them, only an active Steam break frees it."""
    now = time.time() if now is None else now
    if nuclear(st, now):
        return True
    if not within_schedule(st, now):
        return False
    if clocked_out(st, now):
        return False
    return st.get("steam_break_until", 0) <= now

# ----------------------------- learning break -----------------------------

def looks_like_link(raw):
    """A pasted web address. Approvals are matched against the TITLE shown on the browser tab, which
    never contains the address, so a link can never match anything."""
    t = str(raw).strip().lower()
    return ("://" in t or t.startswith("www.") or "youtube.com/" in t or "youtu.be/" in t) and " " not in t

def normalize_phrase(raw):
    """Clean a typed approval phrase: lower-cased, single-spaced. None if it is too short, is a
    web link, or is so generic that it would approve every YouTube tab (e.g. "youtube" or "chrome")."""
    if not isinstance(raw, str) or looks_like_link(raw):
        return None
    p = " ".join(raw.lower().split())
    if len(p.replace(" ", "")) < LEARNING_MIN_PHRASE or p.isdigit():
        return None
    if p in _GENERIC_TITLE_TEXT:
        return None
    return p

def clean_approvals(raw):
    """Keep only well-formed approvals; one entry per phrase (the earliest, so re-adding an
    old phrase can never restart its waiting period)."""
    out = {}
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict):
            continue
        p = normalize_phrase(e.get("phrase"))
        a = e.get("added")
        if p is None or isinstance(a, bool) or not isinstance(a, (int, float)) or a != a:
            continue
        if p not in out or a < out[p]["added"]:
            entry = {"phrase": p, "added": float(a)}
            if e.get("always") is True and len(p.replace(" ", "")) >= LEARNING_MIN_PHRASE_ALWAYS:
                entry["always"] = True
            out[p] = entry
    kept, always = [], 0
    for entry in sorted(out.values(), key=lambda x: x["added"]):
        if entry.get("always"):
            always += 1
            if always > LEARNING_MAX_ALWAYS:          # a hand-edited file can't exceed the cap either
                entry = {"phrase": entry["phrase"], "added": entry["added"]}
        kept.append(entry)
    return kept

def approval_ready_at(entry):
    return entry["added"] + LEARNING_APPROVAL_DELAY_MIN * 60

def approved_phrases(st, now=None):
    """Phrases that count right now (approved at least LEARNING_APPROVAL_DELAY_MIN ago)."""
    now = time.time() if now is None else now
    return [e["phrase"] for e in clean_approvals(st.get("learning_approved")) if approval_ready_at(e) <= now]

def phrase_in_title(phrase, title):
    """A phrase matches when EVERY word of it appears somewhere in the title, in any order -
    so "dune audiobook" matches "Dune (Audiobook)" and "DUNE - Frank Herbert - Full Audiobook"."""
    t = str(title).lower()
    words = str(phrase).lower().split()
    return bool(words) and all(w in t for w in words)       # an empty phrase must match nothing

def title_approved(st, title, now=None):
    return any(phrase_in_title(p, title) for p in approved_phrases(st, now))

def always_phrases(st, now=None):
    """Active 'audiobook' phrases: approved long enough ago, and marked as having no time limit."""
    now = time.time() if now is None else now
    return [e["phrase"] for e in clean_approvals(st.get("learning_approved"))
            if e.get("always") and approval_ready_at(e) <= now]

def youtube_open(st, now=None):
    """Is YouTube being held open *as an exception to the block*? True during a learning break or while
    an audiobook approval is active - but only while sites are actually being blocked. In free time
    (clock-out, outside your hours, any ordinary break) nothing is restricted, so there is no
    exception to enforce and YouTube tabs must be left completely alone. A nuclear lockdown closes it."""
    now = time.time() if now is None else now
    if nuclear(st, now) or not sites_blocked(st, now):
        return False
    return st.get("learning_until", 0) > now or bool(always_phrases(st, now))

def allowed_phrases(st, now=None):
    """The titles that may stay open: every approved phrase during a learning break, otherwise
    only the audiobook ones."""
    now = time.time() if now is None else now
    if learning_active(st, now):
        return approved_phrases(st, now)
    return always_phrases(st, now) if youtube_open(st, now) else []

def title_allowed(st, title, now=None):
    return any(phrase_in_title(p, title) for p in allowed_phrases(st, now))

def learning_active(st, now=None):
    """Nuclear lockdown overrides a learning break, like every other break."""
    now = time.time() if now is None else now
    return st.get("learning_until", 0) > now and not nuclear(st, now)

def _is_learning_domain(domain):
    return any(domain == y or domain.endswith("." + y) for y in LEARNING_UNBLOCKS)

def effective_blocklist(st, now=None):
    """The domains the hosts block should contain right now: the whole blocklist, minus YouTube
    while a learning break is running."""
    bl = list(st.get("blocklist", DEFAULT_BLOCKLIST))
    if youtube_open(st, now):
        return [d for d in bl if not _is_learning_domain(d)]
    return bl

# ----------------------------- hosts -----------------------------

def _expand(domains):
    out, seen = [], set()
    for d in domains:
        for v in (d, "www." + d, "m." + d):
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out

def _read_hosts():
    try:
        with open(HOSTS_PATH, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def _write_hosts(text):
    try:
        with open(HOSTS_PATH, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception:
        return False

def _strip_block(text):
    """Remove the Focus block from hosts text. Tolerates a damaged block (missing END marker):
    only our own 0.0.0.0 lines are dropped, so nobody else's entries are ever swallowed."""
    if MARK_START not in text and MARK_END not in text:
        return text
    out, skip = [], False
    for ln in text.splitlines():
        t = ln.strip()
        if t == MARK_START:
            skip = True
            continue
        if t == MARK_END:
            skip = False
            continue
        if skip and (not t or t.startswith(REDIRECT_IP + " ")):
            continue
        skip = False
        out.append(ln)
    res = "\n".join(out)
    while res.endswith("\n\n"):
        res = res[:-1]
    return res

def _desired_block(st, domains=None):
    lines = [MARK_START]
    domains = st.get("blocklist", DEFAULT_BLOCKLIST) if domains is None else domains
    lines += [f"{REDIRECT_IP} {d}" for d in _expand(domains)]
    lines.append(MARK_END)
    return "\n".join(lines) + "\n"

def _extract_block(text):
    """The Focus block exactly as it currently sits in the hosts text ('' if absent/incomplete)."""
    out, inside = [], False
    for ln in text.splitlines():
        t = ln.strip()
        if t == MARK_START:
            out, inside = [], True
        if inside:
            out.append(t)
            if t == MARK_END:
                return "\n".join(out) + "\n"
    return ""

def flush_dns():
    try:
        if IS_WIN:
            try:    # in-process (a few ms) instead of spawning ipconfig (100ms-1s)
                if ctypes.windll.dnsapi.DnsFlushResolverCache():
                    return
            except Exception:
                pass
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True,
                           creationflags=CREATE_NO_WINDOW)
        elif IS_MAC:
            subprocess.run(["dscacheutil", "-flushcache"], capture_output=True)
            subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True)
        else:  # linux (best effort; harmless if the tool is absent)
            subprocess.run(["resolvectl", "flush-caches"], capture_output=True)
    except Exception:
        pass

def set_hosts_block(st, want_blocked, domains=None):
    """Make the hosts file match the wish. Idempotent, and self-healing: if the block is
    present but incomplete (someone deleted a line, or the blocklist grew) it is rewritten.
    Returns True only when the file was actually changed."""
    text = _read_hosts()
    want = _desired_block(st, domains) if want_blocked else ""
    if _extract_block(text) == want and (want_blocked or (MARK_START not in text and MARK_END not in text)):
        return False
    base = _strip_block(text).rstrip("\n")
    new = (base + "\n" if base else "") + want
    if not _write_hosts(new):
        return False                     # no permission: don't pretend anything changed
    flush_dns()
    return True

def refresh_hosts_block(st, now=None):
    """Force the block to match the current blocklist (set_hosts_block already heals a stale one)."""
    return set_hosts_block(st, True, domains=effective_blocklist(st, now))

# ----------------------------- game launchers (Steam + everything else) -----------------------------

_last_steam_kill = 0.0
STEAM_KILL_COOLDOWN = 20   # seconds between attempts — a launcher relaunching mid-block
                           # doesn't need to be caught within one enforce tick (3s)

def _running_process_names():
    """Lowercase names of every running process, via an in-process snapshot (~ms, no subprocess)."""
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PE)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    snap = k.CreateToolhelp32Snapshot(0x2, 0)          # TH32CS_SNAPPROCESS
    names = set()
    if not snap or snap == ctypes.c_void_p(-1).value:
        return None
    try:
        e = PE(); e.dwSize = ctypes.sizeof(PE)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            names.add(e.szExeFile.lower())
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return names

def kill_game_launchers(force=False):
    """Close any running game launcher — Steam, Epic, Battle.net, Origin/EA app, Ubisoft
    Connect, GOG Galaxy, the Xbox app, Riot Client, Rockstar Launcher, itch.io. Throttled
    + a single process spawn on Windows (not one per process name) so this doesn't quietly
    become a background performance drain when called every few seconds for hours."""
    global _last_steam_kill
    now = time.time()
    if not force and (now - _last_steam_kill) < STEAM_KILL_COOLDOWN:
        return
    _last_steam_kill = now
    try:
        if IS_WIN:
            running = _running_process_names()
            targets = (GAME_LAUNCHER_PROCS if running is None
                       else [n for n in GAME_LAUNCHER_PROCS if n.lower() in running])
            if not targets:
                return                     # nothing to kill -> no subprocess at all
            args = ["taskkill", "/F"]
            for name in targets:
                args += ["/IM", name]
            subprocess.run(args, capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            # macOS/Linux: one short exact-name pkill per known launcher
            for name in GAME_LAUNCHER_UNIX_NAMES:
                try:
                    subprocess.run(["pkill", "-x", name], capture_output=True, timeout=3)
                except Exception:
                    pass
    except Exception:
        pass

# ----------------------------- enforcement -----------------------------

# ---- YouTube Shorts: blocked completely, at every hour ----
# The hosts file can only block a whole domain, and a Shorts tab's title never says "Shorts" (the
# feed is titled just "- YouTube"), so neither can single Shorts out. The browsers' own URL-blocklist
# policy can: it blocks the PATH youtube.com/shorts and nothing else on YouTube. Chrome, Edge and
# Brave read it from the registry (Chromium syntax); Firefox reads match patterns. Needs admin, which
# the app and the guard have. Our entries are recognised by their text, so anything else already in a
# browser's list (a work policy, say) is left alone, and removing ours never touches it.
SHORTS_PATTERNS_CHROMIUM = ["youtube.com/shorts"]
SHORTS_PATTERNS_FIREFOX = ["*://youtube.com/shorts/*", "*://*.youtube.com/shorts/*"]
POLICY_HIVE = "HKLM"                 # tests point this at a scratch HKCU key instead
POLICY_ROOT = "SOFTWARE\\Policies"
POLICY_TARGETS = [
    ("Google\\Chrome\\URLBlocklist", SHORTS_PATTERNS_CHROMIUM),
    ("Microsoft\\Edge\\URLBlocklist", SHORTS_PATTERNS_CHROMIUM),
    ("BraveSoftware\\Brave\\URLBlocklist", SHORTS_PATTERNS_CHROMIUM),
    ("Mozilla\\Firefox\\WebsiteFilter\\Block", SHORTS_PATTERNS_FIREFOX),
]
_policy_warned = False

def _policy_hive():
    import winreg
    return winreg.HKEY_LOCAL_MACHINE if POLICY_HIVE == "HKLM" else winreg.HKEY_CURRENT_USER

def _policy_path(sub):
    return POLICY_ROOT + "\\" + sub

def _policy_values(sub):
    """{value name: text} of the string values in one policy list (empty if the key isn't there)."""
    import winreg
    out = {}
    try:
        with winreg.OpenKey(_policy_hive(), _policy_path(sub)) as k:
            i = 0
            while True:
                try:
                    name, val, typ = winreg.EnumValue(k, i)
                except OSError:
                    break
                if typ == winreg.REG_SZ and isinstance(val, str):
                    out[name] = val
                i += 1
    except OSError:
        pass
    return out

def _set_policy_list(sub, patterns, on):
    """Make our patterns present (on) or absent in one list. True if it had to change something."""
    import winreg
    have = _policy_values(sub)
    if on:
        missing = [p for p in patterns if p not in have.values()]
        if not missing:
            return False
        used = set(have)
        with winreg.CreateKeyEx(_policy_hive(), _policy_path(sub), 0, winreg.KEY_SET_VALUE) as k:
            n = 1
            for p in missing:
                while str(n) in used:
                    n += 1
                winreg.SetValueEx(k, str(n), 0, winreg.REG_SZ, p)
                used.add(str(n))
        return True
    ours = [name for name, val in have.items() if val in patterns]
    if not ours:
        return False
    with winreg.OpenKey(_policy_hive(), _policy_path(sub), 0, winreg.KEY_SET_VALUE) as k:
        for name in ours:
            winreg.DeleteValue(k, name)
    return True

def set_shorts_block(on=True):
    """Add (or remove) the Shorts block in every supported browser. True if every browser is now as
    asked; False on non-Windows or without admin rights (logged once, then quiet)."""
    global _policy_warned
    if not IS_WIN:
        return False
    ok = True
    for sub, patterns in POLICY_TARGETS:
        try:
            if _set_policy_list(sub, patterns, on):
                log_event(("blocked" if on else "unblocked") + " YouTube Shorts in " + sub.split("\\")[-2])
        except OSError as e:
            ok = False
            if not _policy_warned:
                _policy_warned = True
                log_event("could not set the Shorts block (" + sub + "): " + str(e))
    return ok

def shorts_block_in_place():
    """True if every supported browser currently has the Shorts block."""
    if not IS_WIN:
        return False
    return all(all(p in _policy_values(sub).values() for p in patterns) for sub, patterns in POLICY_TARGETS)

def apply_enforcement(st, now=None):
    """Make the machine match the state: block/unblock sites, gate game launchers, keep Shorts blocked."""
    now = time.time() if now is None else now
    set_hosts_block(st, sites_blocked(st, now), domains=effective_blocklist(st, now))
    set_shorts_block(True)                      # always - not just inside the schedule
    if steam_blocked(st, now):
        kill_game_launchers()

def off():
    """Remove all blocking (used by uninstall)."""
    set_shorts_block(False)
    return set_hosts_block({}, False)
