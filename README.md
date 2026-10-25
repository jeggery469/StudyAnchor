<p align="center"><img src="logo.png" width="112" alt="StudyAnchor logo"></p>

# StudyAnchor

**An always-on study lockout app that makes it *hard* to get distracted and *easy* to stay
accountable.** During your study hours it blocks entertainment sites and game launchers, makes you
*earn* your breaks, and gets harder to ignore the longer you slack.

Music and normal web search keep working — it only blocks the stuff that eats your day.

---

## 🚀 Quick start

> **New here?** StudyAnchor shows a short step-by-step tutorial the first time it opens. Reopen it any time with
> the **❓** button (in the popout, or **❓ Tutorial** in the full window).

1. **Keep this folder somewhere permanent** (e.g. `Documents\FocusTool`) — the auto-start tasks
   point at it, so don't move it afterwards. Keep all the files together.
2. **Double-click `Install Forever.bat`** and click **Yes** on the admin prompt. It sets up the
   background guard and auto-start, then opens StudyAnchor. *(Admin is needed once: blocking sites means
   editing the Windows hosts file.)*
3. A small **popout** appears. Hit **▶ Study** to start a session.

Just want to try it without installing anything permanent? Double-click **`Start Focus.bat`**.

**Requirements:** Python 3.9+ ([python.org](https://www.python.org/) — tick *"Add Python to
PATH"*). The modern UI toolkit (customtkinter) installs itself on first launch; without it the app
still runs with plainer styling.

**Platforms:** **Windows 10/11 is the supported platform** — it is the only one StudyAnchor has been tested
on, and the only one with every feature. The code has partial, **untested** fallbacks for macOS and Linux
(blocking through `/etc/hosts` when started with `sudo`, closing game launchers, sounds), but large parts do
not work there: closing blocked tabs, the per-video rules of learning breaks (so a learning break, or
audiobook mode, would leave all of YouTube open), Picture-in-Picture and Shorts blocking, the scroll tax,
in-app recording, the always-on guard and the single-instance lock. Treat macOS/Linux as experimental.
Everything runs **locally**: no account, no server, nothing leaves your machine.

---

## 🧭 The rules

**Study hours are fixed: 07:00 – midnight on weekdays, 10:00 – 18:00 on Sat/Sun, and you clock out at
23:59 every night.** They are set in the code, not
in a settings box, so they can't be shortened from the app. Outside those hours (and after
clock-out) everything is free.

**Inside the schedule, the only thing that unblocks anything is an actual break.** Not turning the
app off, not closing it — the guard relaunches it within a minute.

| Way to a break | How | Cost |
|---|---|---|
| 🏦 **Bank** | Finish a study session → **+15 min** saved; spend it any time | Earned; **15-min cooldown** between bank breaks, can't chain them |
| ⚡ **Cheat** | One button, instant **5-minute** break | **2 per day**; finishing a session gives both back |
| 🌴 **Day off** | Guess a hidden **3-digit code** (it re-rolls on every miss) | Hard — a break until midnight |
| 🎮 **Games** | A 30-minute gaming break for launchers only | 90-minute cooldown |
| 📚 **Learning** | 45 minutes of YouTube — **approved videos only** | **2 per day**; you approve videos in advance |
| ☢ **Nuclear** | Total lockdown for 30 min – rest of day | **No escapes at all, can't be cancelled** |

Rules that keep the breaks honest:

- **No breaks during a study session.** Stop or finish it first.
- **Breaks don't stack** — you can't burn a cheat or spend the bank while one is already running.
- **Nuclear can only get longer.** A second lockdown never shortens the first.
- **A scroll on Shorts / Reels / TikTok costs a bank minute** (the bank can go negative).
- **Settings only move in the stricter direction** (see the reference below), and the **blocked
  list can only grow.**

---

## 🖥️ The app

It opens as a small **always-on-top popout** (drag it by the top bar). **⤢** expands it to the full
window; the full window behaves like a normal window, and **the moment you click away to another
app it collapses back to the popout** so the small box is never buried.

The full window has tabs: **Dashboard** (status, quick actions, live stats), **Bank**, **Learning**,
**Reminders** and **Settings**. Settings starts with your (read-only, locked) **active hours**, then the
adjustable settings, the blocked-sites list and the Save button; the tab scrolls if it doesn't all fit.
StudyAnchor doesn't keep a record of which apps or sites you use.

### 📚 Study sessions
Hit **Study**; when the timer ends you bank **+15 minutes** and get your cheats back. The timer
counts real elapsed time (a sleeping laptop doesn't finish your session for you). **⏸ Pause** is for
real interruptions — while paused, the nagging tells you to resume.

### 📢 Notifications
Whenever you're on the clock **without a study session** (or a break just ended), an alert
escalates from a small corner card to a big centered one, with beeps that build into a dissonant
cluster, overlapping voices, optional strobe lights and your own recordings. The **sound is the
real alert** — the window never goes fullscreen or steals focus. Every alert has **▶ Start session**
and **😴 Snooze** buttons, so you're never trapped. *Settings → 🔔 Test notification* shows one.

### 📝 Reminders & 🎙 your own voice
Write reminders in the **Reminders** tab; the app can read them aloud, auto-read one on an interval,
and use them as the words it nags you with. Pick any installed Windows voice. **🎙 Record** saves a
`.wav` into `sounds\` that plays during the loudest alerts (you can also drop `.wav` files there).

### 📚 Learning break (YouTube tutorials without the rabbit hole)
Blocking works per website, so YouTube is normally all-or-nothing. A learning break opens YouTube for
45 minutes but only lets a tab stay open if its **title contains something you approved in advance**
(Learning tab → type part of the video's title, e.g. `CS50 lecture 3` or an audiobook's name). Any other
YouTube tab — the home page, recommendations, autoplay into something else — is **closed after 10
seconds**, with a short warning beep. Every other blocked site stays blocked.

- **Approvals only count after 10 minutes**, so you can't approve something on impulse in the middle
  of a craving; do it in your free time. Removing an approval is instant.
- 2 learning breaks a day, none during a study session or a nuclear lockdown; starting a session or
  pressing Lock in ends one early.
- It checks the tab you are **looking at**: a YouTube tab left playing in the background isn't policed.
  Phrases match the **video's title** (what the tab shows), not the channel and **not the link** — pasting a
  link is refused — and **every word you type has to appear in the title, in any order** (`dune audiobook` matches "Dune (Audiobook)" and "DUNE - Full Audiobook").

**🎧 Audiobook mode (no time limit).** Tick *Audiobook — no time limit* when you approve a title and,
once its 10 minutes are up, YouTube stays open **all day** for that title (and only that title) without
a learning break and without using one of your 2. Other YouTube tabs still close after 10 seconds, other
blocked sites stay blocked, and it keeps working during a study session so you can listen while you
work. Because it is so much more open, an audiobook entry needs at least 8 characters, you can have at
most 3, and a nuclear lockdown still shuts YouTube completely. Remove it from the list to turn it off.

**🚫 YouTube Shorts are blocked completely — at every hour.** The hosts file can only block a whole site, and
a Short's tab title never says "Shorts", so StudyAnchor uses the browsers' own URL-blocklist policy instead: it
blocks the path `youtube.com/shorts` and nothing else on YouTube (Chrome, Edge, Brave and Firefox; Opera is
not covered). The app and the guard keep it in place and put it back if it's removed. Needs the admin rights
StudyAnchor already has. Good to know: Chrome/Edge will say *"Managed by your organization"* (that's this policy);
it doesn't touch other policies already set; and a Shorts tab that is **already open** keeps scrolling until
you reload it — new Shorts links are blocked straight away. `Install Forever.bat --off` / uninstall removes it.

**🔎 Bing video search is blocked.** Bing's video results (`bing.com/videos`) play YouTube inline, which
would sidestep the YouTube rules, so any tab titled "… - Search Videos" is closed while blocking is on —
learning breaks and audiobook mode included. Normal Bing web search still works.

**🪟 Picture-in-Picture is blocked.** A video popped out into its own floating window would keep playing
outside every tab (so the tab checks can't see it), so while blocking is on, any browser Picture-in-Picture
window is closed within about 2 seconds — learning breaks and audiobook mode included, since the window
doesn't say what is playing. In free time (a break, outside your hours, after clock-out) it is left alone.
(Use the tab itself for audiobooks.) It closes only that window — it never sends keystrokes.

### 🌿 Burnout guard & 🕗 Clock out
Once you've studied your **daily cap** (default 240 min; `0` = off) the nagging stops and it tells
you to rest. At **clock-out (23:59)** blocking and nagging switch off for the evening.

**🕗 Clock out early.** From **20:00** a *🕗 Clock out* button appears in the popout (and in the
full window's Breaks row). Tap it, confirm, and you're clocked out for the night: blocking and nagging
switch off straight away, until tomorrow. It isn't there before 20:00, it can't be used mid-session or
during a nuclear lockdown, and it can't be undone tonight. It resets at midnight.

### 🚫 What gets blocked
YouTube, Instagram, TikTok, Reddit, Twitter/X, Facebook, Snapchat, Pinterest, Twitch, Tumblr, 9GAG,
Netflix, Hulu, Disney+, Prime Video, Bilibili, IYF, Fandom, Minecraft, Amazon — plus any
site you add in **Settings**. Game launchers (Steam, Epic, Battle.net, EA/Origin, Ubisoft Connect,
GOG Galaxy, Xbox app, Riot, Rockstar, itch.io) are closed unless you take a gaming break.

Blocking uses the hosts file, so it works in every browser — but it stops **new** page loads. A
blocked tab you're **looking at** is closed automatically within a couple of seconds; blocked tabs
you already have open in the background stay open until you reload them.

---

## ♾️ Forever mode

`Install Forever.bat` creates two scheduled tasks:

- **FocusGuard** — runs every minute (as you, elevated), re-applies the block if anything changed
  or was tampered with, and **relaunches StudyAnchor if it was closed**.
- **FocusApp** — opens the popout every time you log in.

There is deliberately **no one-click uninstall**. To remove it: open **Task Scheduler**, delete the
`FocusGuard` and `FocusApp` tasks, then run `pythonw guard.py --off` (as administrator) from this
folder to unblock the sites.

After updating the files, double-click **`Restart Focus.bat`** to load the new version.

---

## ⚙️ Settings reference

| Setting | Can be changed… | What it does |
|---|---|---|
| Study session length | up only, never below 20 | Minutes per session |
| Daily study cap | up only (`0` = off is the strictest) | Rest message + nagging stops after this many minutes |
| Gaming break cooldown | up only | Wait between gaming breaks |
| Snooze length | down only | How long 😴 pauses the nudges |
| Gaming break length | down only | Length of a gaming break |
| Notification frequency, Alarm intensity, Max voices, Strobe | freely | How loud and how often the nagging is |
| Blocked sites | **add only** | The list of blocked sites |
| Reminders, voice, auto-read, own-words | freely | The Reminders tab |

Time values are minutes, 0–1440.

---

## 🧪 Tests

```
python run_tests.py          # everything (about 2 minutes: opens real, hidden windows)
python run_tests.py --fast   # skip the window tests (about 10 seconds)
```

or double-click **`Run Tests.bat`**. There are ~700 tests covering the schedule and blocking rules,
hosts-file editing, saved state, the audio/alarm layer, every button and dialog, the tick loop and
nagging, on both UI toolkits. They run against scratch copies and never touch your real hosts file
or settings.

---

## 🛠️ Troubleshooting

- **A blocked site still loads?** Turn off your browser's **Secure DNS / DNS-over-HTTPS**
  (Chrome/Edge: Settings → Privacy → Security; Firefox: DNS over HTTPS → Off) and reload the tab.
- **Nothing is being blocked?** Check the popout says 🔒 LOCKED IN. Outside your hours (07:00–midnight
  weekdays, 10:00–18:00 weekends), after
  23:59, or during any break, everything is free on purpose. Run `Install Forever.bat` again if the
  app isn't running at all.
- **The window seems frozen?** It now restarts itself if it stays frozen for 45 seconds, and writes
  what it was stuck on to `C:\ProgramData\FocusTool\focus.log` (also errors and a resource check every
  10 minutes). Send that file if it ever happens repeatedly.
- **Notifications don't appear?** Use **Settings → Test notification**. If that works, you just
  haven't hit a trigger (outside hours, or a session is running).
- **Recording doesn't work?** Make sure a microphone is connected and allowed in Windows.
- **Too much nagging?** Lower *Notification frequency*, or use **😴 Snooze**.
- **Strobe warning:** high-level alerts flash rapidly. Turn **Strobe off** in Settings if you're
  sensitive to flashing light.

---

## 📁 What's in the folder

| File | Purpose |
|---|---|
| `Install Forever.bat` | One-time setup: guard + auto-start, then opens StudyAnchor |
| `Start Focus.bat` | Open the app without installing anything |
| `Restart Focus.bat` | Stop the running app and start the latest code |
| `Setup.bat` | (Optional) install the modern UI toolkit up front |
| `Run Tests.bat` / `run_tests.py` | Run the test suite |
| `C:\ProgramData\FocusTool\focus.log` | Diagnostics: freezes (with stacks), restarts, errors |
| `focusapp.py` | The app: UI, sessions, breaks, notifications, reminders |
| `core.py` | The engine: rules, state, hosts file, launcher closing |
| `tutorial.py` | The words of the in-app tutorial (numbers come from the real settings) |
| `guard.py` | The background enforcer |
| `logo.png` / `logo.ico` | The app logo (window icon, headers, tutorial, this page) |
| `sounds\` | Empty on purpose: put your own `.wav` recordings here for the loudest alerts |
| `tests\` | The test suite |
| `starter\` | A "build it yourself" teaching version with a step-by-step guide |
| `FEATURES.md`, `ARCHITECTURE.md` | Feature list and how the code fits together |

Your settings and progress live in `C:\ProgramData\FocusTool\state.json`.

---

**Study hard. ⚓**
