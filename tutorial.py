"""tutorial.py - the words of the StudyAnchor walkthrough.

Pure text, no windows, so it can be tested. Every number comes from core (or the saved state), so
the tutorial can never disagree with what the app actually does.
"""
import core


def clock(hhmm):
    """'00:00' -> 'midnight'; '07:00' -> '7:00 AM'; '18:00' -> '6:00 PM'."""
    if hhmm in ("00:00", "24:00"):
        return "midnight"
    try:
        h, m = (int(x) for x in str(hhmm).split(":"))
    except Exception:
        return str(hhmm)
    suffix = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12}:{m:02d} {suffix}"


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def steps(st=None):
    """The walkthrough as a list of (title, body). `st` is the saved state (defaults are used for anything
    missing, so it also works with a brand-new install)."""
    st = st if isinstance(st, dict) else core.default_state()
    d = core.default_state()
    g = lambda k: st.get(k, d[k])                        # noqa: E731

    cheats = [m for m in core.CHEAT_LADDER if m > 0]
    cheat_min = cheats[0] if cheats else 0
    work = f"{clock(g('schedule_start'))} to {clock(g('schedule_end'))}"
    weekend = f"{clock(g('weekend_schedule_start'))} to {clock(g('weekend_schedule_end'))}"

    return [
        ("Welcome to StudyAnchor",
         "StudyAnchor keeps you on track while you study. During your study hours it blocks the sites "
         "and games that eat your day, and the only ways to get time off are ones you earn.\n\n"
         f"Study hours:\n   •  Weekdays: {work}\n   •  Weekends: {weekend}\n\n"
         "Outside those hours everything is free. The hours are fixed in the program on purpose, so "
         "you can't shorten them in a weak moment."),

        ("🧭 The little popout",
         "The small window that stays on top of everything is your remote control:\n\n"
         "   ▶ Study  –  start a focus session\n"
         f"   ⚡ Cheat  –  a short break ({_plural(len(cheats), 'cheat')} a day)\n"
         "   ☕ Bank  –  spend the minutes you've earned\n"
         "   🎮 Games  –  a break for game launchers only\n"
         "   📚 Learn  –  open YouTube for approved videos\n"
         "   🔒 Lock in  –  end a break early\n"
         "   ☢ Nuclear  –  total lockdown, no escapes\n\n"
         "Open the full window with ⤢ for your hours, settings and the blocked-sites list. "
         "It folds back into the popout when you switch to another app."),

        ("⏳ Study sessions & your time bank",
         f"Press Study to start a {g('session_length_min')}-minute session (sessions are never shorter than "
         f"{core.MIN_SESSION_MIN} minutes). Finish it and "
         f"{_plural(core.SESSION_REWARD_MIN, 'minute')} go into your time bank.\n\n"
         "Spend banked time with ☕ Bank for a real break. After one bank break you wait "
         f"{_plural(core.BANK_COOLDOWN_MIN, 'minute')} before the next, so you can't chain them.\n\n"
         "Scrolling Shorts, Reels or TikTok costs bank minutes, and the bank can go negative. "
         "No breaks can be started in the middle of a session."),

        ("☕ Breaks",
         f"⚡ Cheat: {_plural(len(cheats), 'break')} a day of {cheat_min} minutes each. "
         "Finishing a session gives your cheats back.\n\n"
         f"🎮 Games: {g('steam_break_min')} minutes for game launchers, then a "
         f"{g('steam_cooldown_min')}-minute cooldown.\n\n"
         "🌴 Day off: guess the hidden 3-digit code. It changes on every miss, so it's hard.\n\n"
         "🔒 Lock in ends any break early. When a break ends you get a loud reminder to go back to work."),

        ("📚 Watching YouTube to learn",
         "Some videos are genuinely useful. Teach StudyAnchor which ones:\n\n"
         "1.  Open the Learning tab and type a few words from the video's title, such as "
         "\"ap world review\". Every word must appear in the title.\n"
         f"2.  Wait {_plural(core.LEARNING_APPROVAL_DELAY_MIN, 'minute')}. New approvals can't be used "
         "right away, so you can't approve something on impulse.\n"
         f"3.  Press 📚 Learn for a {core.LEARNING_BREAK_MIN}-minute learning break "
         f"({core.LEARNING_BREAKS_PER_DAY} a day).\n\n"
         f"During it, approved videos play and any other YouTube tab closes after "
         f"{core.LEARNING_GRACE_SEC} seconds. For an audiobook, tick \"no time limit\" when you approve it."),

        ("🚫 What gets blocked",
         "•  The sites on your blocklist: social media, streaming, game stores and more.\n"
         "•  YouTube Shorts, completely, at every hour.\n"
         "•  Video results on Bing and Google, and floating Picture-in-Picture video windows.\n"
         "•  Game launchers like Steam, Epic and Battle.net.\n\n"
         "You can add sites in Settings, but you can never remove them. If a blocked site is in front, "
         "its tab closes itself within a couple of seconds."),

        ("🕗 Clocking out",
         f"You're automatically clocked out at {clock(g('clockout_time'))} each night: blocking and "
         "nagging switch off until the next day.\n\n"
         f"From {clock(core.CLOCKOUT_OPTION_TIME)} you can clock out early with the 🕗 button, "
         "after you confirm. It can't be undone that night, and it isn't available during a session "
         "or a nuclear lockdown."),

        ("☢ Nuclear & the rules that don't bend",
         "☢ Nuclear locks everything, with no cheat, no bank, no games and no code, for as long as you "
         "choose (up to the rest of the day). It can't be cancelled, only extended.\n\n"
         "Some things are deliberately fixed so a bad moment can't undo a good decision:\n"
         "   •  The schedule can't be changed.\n"
         "   •  The blocklist only grows.\n"
         "   •  You can't add extra time to a break.\n\n"
         "The app restarts itself if it ever freezes, and a background guard reopens it if it's closed."),

        ("✅ You're set",
         "That's everything. A few last tips:\n\n"
         "   •  The status at the top of the popout tells you what's happening right now.\n"
         "   •  If something is blocked that you need, check the Learning tab before anything else.\n"
         "   •  After updating the files, double-click Restart Focus.bat to load them.\n"
         "   •  Troubleshooting notes are in the README, and a diagnostics log is kept in "
         "C:\\ProgramData\\FocusTool\\focus.log.\n\n"
         "You can reopen this tutorial any time with the ❓ button."),
    ]
