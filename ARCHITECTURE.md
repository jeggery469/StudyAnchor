# StudyAnchor — Architecture

> Naming note: the app was called "Focus" before it was renamed StudyAnchor. Only the visible name changed. The
> data folder (`C:\ProgramData\FocusTool`), the `FocusGuard`/`FocusApp` scheduled tasks, the single-instance
> mutex and the `FOCUS-BLOCK` hosts-file markers keep their old names on purpose: renaming them would orphan
> existing installs (stale hosts blocks, duplicate tasks, lost state).

How the code is organized and why. StudyAnchor is a small system of cooperating parts that share one
state file. It runs **fully local** — no account, no server, nothing leaves the machine.

## The parts

| Part | Runs as | Job |
|---|---|---|
| `focusapp.py` | you (elevated) | The GUI: timer, breaks, notifications, all interaction |
| `guard.py` | you (elevated), scheduled every minute | Headless enforcer: keeps the block applied and relaunches the app if it was closed |
| `state.json` | — (`C:\ProgramData\FocusTool\`) | Single source of truth, read/written by both |
| `core.py` | (imported) | The shared engine: rules, state, hosts file, launcher closing |
| `tests\` | — | The test suite (`python run_tests.py`) |

**Central idea:** buttons don't block sites directly. A button changes **state**; enforcement
makes the computer *match* that state. Intent and enforcement are decoupled, so the app and the
guard always agree.

```
 [ you click Start ] → focusapp edits state → saves state.json
                                            → asks a worker thread to run apply_enforcement()
                                               → reads state → edits hosts file / closes launchers
   every 3s (app)  and  every 60s (guard)  run apply_enforcement() again
```

## `core.py` — the engine

- **Platform flags** — `IS_WIN/IS_MAC/IS_LINUX` pick the hosts path, DNS-flush and process-killing
  method, and the admin check.
- **State** — `load_state()` starts from `default_state()` and layers the saved file on top, but
  defensively: values of the wrong type fall back to defaults; the schedule keys — including a
  separate weekday/weekend window (`today_schedule()` picks by `datetime.weekday()`) — are always
  taken from the code (`LOCKED_KEYS`); the blocklist is normalized and **merged with the built-in list**,
  so it can only grow and new built-in sites reach existing installs. `save_state()` is atomic
  (temp file + `os.replace`) and cleans up after a failure.
- **The decision functions** — the whole "what's blocked right now?" rulebook:
  ```python
  def sites_blocked(st, now):
      if nuclear(st, now):           return True    # beats everything, even a break
      if not within_schedule(st, now): return False # outside your hours: free
      if clocked_out(st, now):       return False   # after the evening cut-off: free
      return st["unlock_until"] <= now              # inside the schedule: only a break frees you
  ```
  `steam_blocked` is the same rule with the gaming break. They are pure functions of
  (state, clock), so the tests exercise them with a controlled clock (including an exhaustive
  truth table).
- **Hosts blocking** — writes `0.0.0.0 <domain>` lines between marker comments. `set_hosts_block()`
  compares the *whole block* with what it wants, so it is idempotent **and self-healing**: a
  deleted line, a half-written block, or a grown blocklist is repaired on the next pass. It only
  flushes DNS when a write actually succeeded, and `_strip_block` never swallows anyone else's
  entries, even from a damaged block.
- **Closing launchers** — `kill_game_launchers()` takes an in-process process snapshot
  (`CreateToolhelp32Snapshot`) and only spawns `taskkill` when a launcher is actually running,
  throttled to once per 20 s. On macOS/Linux it uses exact process names (`pkill -x`), never
  command-line substrings.
- **Single instance** — a named mutex (`claim_app_instance`, `app_running`) lets the guard tell
  whether the app is alive without starting a second copy.
- **Domain handling** — `normalize_domain()` turns pasted URLs into hostnames (punycode for
  non-ASCII, rejects IPs/junk); `title_keywords()` derives the words the tab-closer looks for from
  the *site name*, never a subdomain (so `search.bilibili.com` can't close a Google Search tab).

## `guard.py`

Elevate → apply enforcement → if the app isn't running, launch it. Registered as a per-minute task
that runs as you (SYSTEM can't start a Store-installed Python and would show an invisible window).

## `focusapp.py` — the application

- **UI abstraction** — `WButton/WLabel/WFrame/...` return **customtkinter** widgets when it is
  installed and **plain tkinter** otherwise; one codebase, two renderers. Windows-only calls are
  guarded behind `core.IS_WIN`. The toolkit is only pip-installed when the file is run as the app,
  never as a side effect of importing it.
- **Two real windows** — `self.root` (full) and `self.popout` (mini) are created once and never
  reconfigured; switching just withdraws one and shows the other. The popout is `-topmost`; the
  full window is not, and a `<FocusOut>` check collapses it back to the popout when focus leaves
  the app.
- **Loops** — two self-rescheduling `root.after` timers:
  - `_tick()` every 1 s: session countdown (by real elapsed time, capped so sleep can't skip
    ahead), nagging, tab auto-close, doomscroll tax, clock-out/break-end events,
    UI refresh. **An exception in one pass is recorded and the next tick is always scheduled**, so
    the timer can never silently die.
  - `_enforce_loop()` every 3 s → `_enforce_async()`.
- **Background enforcement** — `_enforce_async()` runs `apply_enforcement()` on a single worker
  thread (hosts I/O, DNS flush and process checks must never block the window). Requests that
  arrive while it runs are coalesced into one more pass.
- **Breaks** — `toggle_session / complete_session / cheat_break / spend_bank / steam_break /
  disable_dialog / go_nuclear / snooze` are all "check the rules → edit state → save → enforce".
  The dialogs are thin: the logic lives in `_grant_bank`, `_try_code` and `_arm_nuclear` so it can
  be tested without clicking. Breaks are refused during a session or nuclear lockdown and can't
  stack; `_arm_nuclear` only ever extends.
- **Settings** — `LOCKED_DIR` marks which settings may only go up or down; `save_settings` validates
  everything before applying anything (atomic), with a 0–1440 bound.
- **Notifications** — `Notifier` (one styled alert card, decoys and strobe at the top levels),
  `Alarm` (a *fixed* pool of four threads for the beeps; idle ones sleep on an Event), `say_overlap()`
  (several voices at once), `_maybe_nag()` (seconds over → level + interval, scaled by the frequency
  slider). The strobe only recolours two thin bars and the decoys — never the card's text — and paces
  itself against its own lateness. Voice bursts are throttled to one per 6 s.
- **Speech** — each voice or recording is one short-lived process (PowerShell + System.Speech on
  Windows, `say`/`spd-say`/`afplay`/`aplay` elsewhere), so voices overlap. Launches are queued to one audio
  thread (the UI thread never starts a process; a full queue drops sounds rather than blocking), capped at
  3 concurrent, and the nag fires them in bursts at most every 6 s. (A single resident speech process was
  tried and removed: it could only be verified by writing speech to files, not by listening, and the files
  came out inconsistent.)
- **Learning break** — `core.effective_blocklist()` drops YouTube from the hosts block while
  `learning_until` is in the future (nuclear overrides); the tick's `_learning_enforce()` closes the
  foreground YouTube tab after a grace period unless its title contains an approved phrase
  (`core.title_allowed`; approvals only count after a delay; a phrase matches when all its words are in
  the title). The hosts file can't tell one video from another, so this is the per-video part.
  An approval can carry `"always": true` (audiobook): `core.youtube_open()` is then true all day, not just
  during a break, and only those phrases are allowed outside a break (`allowed_phrases`). Those entries
  need 8+ characters and are capped at 3, enforced when the state is loaded as well as in the UI.
- **Tutorial** — `tutorial.py` is pure text (`steps(state)`), built from `core`'s constants so it can't drift;
  `FocusApp.show_tutorial()` is a small step dialog. `tutorial_seen` in the state stops it opening by itself
  again; `AUTO_TUTORIAL` (class attribute) lets the tests switch the first-run popup off.
- **Blocking YouTube Shorts** — a path can't be blocked in the hosts file and a Short's title doesn't say
  "Shorts", so `core.set_shorts_block()` writes the browsers' `URLBlocklist` policy (Chromium: Chrome, Edge,
  Brave; Firefox: `WebsiteFilter\Block`) under `HKLM\SOFTWARE\Policies`. `apply_enforcement()` calls it every
  pass, regardless of the schedule; it only adds/removes its own patterns (recognised by text, numbered into
  the first free slot), so other policies are untouched. `POLICY_HIVE`/`POLICY_ROOT` are redirected to a
  scratch HKCU key in the tests (`support.py`), so they never touch the real policies.
- **Clocking out early** — `core.clockout_option_available()` (from `CLOCKOUT_OPTION_TIME`, only while
  blocking, never in nuclear) and `core.clock_out()` store `clockout_manual_at`; `core.clocked_out()` also
  returns true when `manual_clockout_active()` (same date, at/after 20:00, not in the future, finite - a
  hand-edited value can't clock you out early). The popout's button row is packed only while the option is
  open (`_sync_clockout_row`).
- **Bing video search** — the hosts file can't block one path of bing.com, so `core.VIDEO_SEARCH_TITLES`
  ("search videos", "bing videos") are added to the tab closer's keywords by `core.blocked_title_keywords()`
  whenever `sites_blocked` is true, independent of learning/audiobook mode.
- **Picture-in-Picture** — a PiP window is a separate top-level window, invisible to the foreground-tab
  checks. While `core.pip_blocked()` (= `sites_blocked`) is true, `_close_pip()` (every ~2 s) calls
  `find_pip_windows()` (`EnumWindows`; a window whose whole title is exactly `Picture in picture` /
  `Picture-in-Picture` and whose process is a browser) and `close_window()` posts `WM_CLOSE` to that
  window. Exact title match so a normal window about PiP is never touched; no keystrokes are used.
- **Staying alive** — `Watchdog` (own thread) watches a heartbeat from the 1 s tick: after 8 s it logs
  every thread's stack (`dump_threads`, main thread first) to `focus.log`; after 45 s it restarts the app
  (`_restart_self`: release the single-instance lock, launch a new copy, exit); every 10 min it logs
  `process_health()` and restarts early on a resource leak. A gap in its own schedule (laptop sleep) is
  not a freeze. Every beep takes at least its own duration, so a missing sound
  device can't turn the alarm threads into a busy loop.
- **Watching activity** — `foreground_raw()` reads the active window (process names cached);
  `ScrollCounter` installs the global mouse hook **only while a Shorts/Reels/TikTok tab is in
  front**; `send_ctrl_w()` closes a blocked foreground tab.
- **Safe scripting of PowerShell** — `_ps_quote()` doubles straight *and curly* quotes so a
  reminder like `don’t` can't break out of the speech command.

## Why it's built this way

- **State-as-truth + a reconciling loop** keeps the app and the guard consistent without them ever
  talking to each other.
- **Pure decision functions** make the rules readable and exhaustively testable.
- **Idempotent, self-healing enforcement** makes frequent loops cheap and tampering pointless.
- **Nothing slow on the UI thread** — subprocesses, disk and DNS work all happen elsewhere.

## Testing

`python run_tests.py` (or `--fast` to skip the window tests). `tests/support.py` isolates every
test in a scratch folder with a controllable clock; `tests/appsupport.py` builds one real app per
test class (customtkinter and plain tkinter) with audio, the foreground window, the scroll hook
and the enforcement thread replaced, and resets it between tests. Dialog tests click the real
buttons.
