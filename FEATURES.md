# StudyAnchor — Feature List

## 🚫 Blocking
- Site blocking in every browser via the hosts file — YouTube, Instagram, TikTok, Reddit, Twitter/X,
  Facebook, Snapchat, Pinterest, Twitch, Tumblr, 9GAG, Netflix, Hulu, Disney+, Prime Video, Bilibili,
  IYF, Fandom, Minecraft, Amazon — plus anything you add. The list **only grows**; new
  built-in sites reach existing installs automatically.
- **Self-healing** — if someone deletes a line from the hosts block, or it's left half-written, the
  next pass repairs it. Other people's hosts entries are never touched.
- Music & search stay open (Spotify/SoundCloud/Google untouched).
- **Game launchers** (Steam, Epic, Battle.net, EA/Origin, Ubisoft Connect, GOG Galaxy, Xbox app,
  Riot, Rockstar, itch.io) are closed during study hours unless you take a gaming break.
- **Foreground tab auto-close** — a blocked site you're looking at is closed within a couple of
  seconds (matched by site name, so Google Search / Spotify / research tabs are never hit).
- **Fixed schedule** — 07:00–midnight on weekdays, **10:00–18:00 on weekends**, with a 23:59 clock-out
  every day, set in code (read-only in the app).

## ⏱️ Study & breaks
- Study sessions — at least **20 minutes** (can be lengthened, never shortened below that); countdown by real elapsed time; **Pause/Resume** without losing progress.
- 🏦 Time Bank — finish a session → **+15 min** saved; can go **negative** (scroll tax). A
  **15-minute cooldown** between bank breaks stops chaining them back-to-back.
- ⚡ Cheat break — **two 5-minute breaks a day**; a finished session gives them back.
- 🌴 Day-off code — guess a hidden **3-digit code** (re-rolls on every miss) → a break until midnight.
- 🎮 Gaming break — 30 minutes for the launchers only, with a 90-minute cooldown.
- 📚 **Learning break** — 45 min of YouTube for **approved videos only** (2 a day). You approve part of a
  video's title in advance (counts after 10 min, removable instantly); any other YouTube tab is closed
  after 10 s. Everything else stays blocked. Nuclear overrides it; sessions end it.
- ❓ **Built-in tutorial** — a 9-step walkthrough on first run (and from the ❓ button any time). Its numbers are read from
  the app's real settings, so it never goes out of date.
- 🚫 **YouTube Shorts blocked completely, 24/7** — through the browsers' URL-blocklist policy (path
  `youtube.com/shorts` only; Chrome, Edge, Brave, Firefox), kept in place by the app and the guard.
- 🔎 **No Bing video search** — Bing's video results play YouTube inline, bypassing the YouTube rules, so any tab
  titled "… - Search Videos" is closed whenever sites are blocked (learning break and audiobook mode included).
- 🪟 **No Picture-in-Picture** — while sites are blocked, a floating browser video window (Chrome, Edge,
  Firefox, Brave, Opera) is closed within ~2 s, even during a learning break or audiobook mode. Free time
  (breaks, outside hours, clock-out) leaves it alone.
- 🎧 **Audiobook mode** — approve a title with "no time limit" and YouTube stays open all day for that title
  only (no break needed, none used up, works during sessions). At least 8 characters, at most 3, the same
  10-minute wait, nuclear overrides it, removing it is instant. Phrases match when every word is in the title.
- 🔒 Lock in now — end a break early.
- 😴 Snooze — pause the session nudges (sites stay blocked).
- ☢ Nuclear lockdown — 30 min to rest-of-day; **no escapes, can't be cancelled, can only be extended**.
- **Honest breaks** — refused during a session or nuclear, can't stack, can't be used to shorten
  anything.

## 📉 Anti-doomscroll
- Every scroll on a Shorts / Reels / TikTok tab costs a bank minute. The global mouse hook is only
  installed while such a tab is in front, so it never slows the rest of your computer.

## 📢 Notifications (escalating)
- Alert card that grows corner → centered → large, with a level icon, accent bars, decoy windows at
  the top levels and optional strobe. It never goes fullscreen or steals focus.
- Beeps that accelerate into a dissonant cluster (fixed pool of 4 threads).
- Overlapping voices (max 3 speech processes at once, in bursts at most every 6 s), your own reminders as the words, the rude
  lines only at the very top level, and your own `.wav` recordings.
- **▶ Start session** and **😴 Snooze** buttons on every alert — never trapped.
- Frequency slider (1 rare → 5 relentless); **🔔 Test notification** in Settings.
- Break-over alerts: "BREAK OVER" / "GAMES OVER".

## 📝 Reminders & recording
- Notepad; read all / read one / stop; auto-read on an interval; pick any installed voice.
- 🎙 In-app recorder (Windows MCI) with Test and Clear.

## 🖥️ UI
- Always-on-top popout ⇄ normal full window with tabs (Dashboard · Bank ·
  Learning · Reminders · Settings). Click away from the full window and it collapses back to the popout.
- Lavender/navy theme; customtkinter with a plain-tkinter fallback.
- Settings tab — your locked active hours at the top, then adjustable settings (it scrolls). No usage tracking:
  StudyAnchor keeps no record of which apps or sites you use.

## ⚙️ Settings
- Session length, daily cap, gaming cooldown (**up only**); snooze and gaming-break length
  (**down only**); notification frequency, alarm intensity, voices, strobe (free); blocklist
  (**add only**). All values 0–1440 and validated atomically.

## 🌿 Wellbeing
- **Burnout guard** — a daily study cap; once hit the nagging stops and it tells you to rest.
- **🕗 Clock out early** — from 20:00 a button lets you call it a night (confirm first; not during a session or
  nuclear; resets at midnight). Otherwise the automatic clock-out is 23:59.
- **🕗 Clock out** — after 23:59 blocking and nagging are off for the evening.

## ♾️ Forever mode & reliability
- `Install Forever.bat`: a guard task every minute (relaunches the app if closed) + auto-start at
  login. Single-instance mutex so it never runs twice.
- Enforcement, DNS flush and process checks run off the UI thread; nothing on the window's thread
  waits on disk or a subprocess. The 1-second tick survives errors.
- **Freeze watchdog** — if the window stops responding it logs every thread's stack to `focus.log`, and
  restarts the app after 45 s. A resource check (window objects, handles, memory) every 10 min restarts
  it early if it is leaking. Sleep/wake is not mistaken for a freeze.
- **Speech is launched off the window's thread**, capped at 3 at once and at one burst every 6 s (a sustained
  nag used to start a speech engine several times a second, which loaded the whole machine).
- **The strobe no longer repaints the alert card** (measured: it cost up to 0.5 s a frame and froze the
  window); it paces itself and slows down if the machine struggles.
- Hand-edited or corrupt state files can't crash it: wrong-typed values fall back to defaults.

## 🧪 Tests
- ~700 tests (`python run_tests.py`, `--fast` skips window tests) covering every module on both UI
  toolkits, including clicking the real buttons. They never touch your real hosts file or settings.

## 🌍 Platforms
- **Windows 10/11 is the supported platform** (the only one tested, and the only one with every feature).
- macOS/Linux: partial and **untested** fallbacks (blocking via `/etc/hosts` with `sudo`, launcher closing by
  exact process name, sounds). Not available there: tab auto-close, per-video learning-break rules (a
  learning break or audiobook mode would leave all of YouTube open), Picture-in-Picture and Shorts
  blocking, the scroll tax, in-app recording, the always-on guard and the single-instance lock.
