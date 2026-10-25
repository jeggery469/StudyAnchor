# LEARN — how this was designed, and how to build it yourself

This walks you through **how I arrived at the design** (not just what it is), the one big idea
that makes Focus work, the order to build the TODOs, and where to learn each piece.

---

## 1. How the design was actually found (the honest story)

**First idea (the obvious one):** "When I click *Block*, block YouTube. When I click *Break*,
unblock it." So you write `block()` and `unblock()` and wire them to buttons.

**Why that falls apart fast:** now add a schedule (only block 8am–10pm), and breaks that expire
after 5 minutes, and "finish a session to earn a break." Suddenly you have `block()` /
`unblock()` calls sprinkled everywhere — in the button, in a timer, in the schedule check. And
the moment two of them disagree (a break *expired* but nothing *re-blocked*), you're stuck in a
wrong state with no idea why. You spend all your time chasing "who forgot to call block()?"
bugs. This is called **imperative** code: you're giving step-by-step commands and hoping the
order is always right.

**The insight (the thing worth learning):** stop *commanding*. Instead, separate two questions:

1. **What SHOULD be true right now?** (a decision, from data)
2. **Make it true.** (an action that closes the gap)

So I stored the app's *intent* as plain **state** (a dict of numbers/timestamps), wrote **one
function** that reads that state and answers "should sites be blocked right now?", and then a
**loop** that, once a second, asks that question and makes the hosts file match the answer.

Now there's no "who forgot to call block()?" — because *nobody* calls block(). Buttons just
change the state; the loop always reconciles reality to it. A break expiring isn't an event you
have to handle; it's just `unlock_until` being in the past, which the next loop notices for free.

That's the whole trick, and it's the same pattern behind a lot of serious software.

---

## 2. The one big idea: **desired state + a reconcile loop**

Think of a **thermostat**. You don't tell it "turn on the heater now, turn it off in 10 minutes."
You set a *desired* temperature (state). A loop constantly compares desired vs actual and closes
the gap. That's Focus:

```
   STATE (desired)            DECISION                 ENFORCEMENT (make it real)
   unlock_until, schedule  →  sites_blocked(st)?   →   edit the hosts file
        ▲                                                     │
        └───────────  buttons change state   ◄───────  loop runs every 1–3s
```

- **Buttons change state** (start session, take a cheat) — that's it.
- **`sites_blocked(st)`** is a *pure decision*: it only reads state + the clock, returns
  True/False, and changes nothing.
- **`apply_enforcement(st)`** makes the world match that decision.
- **A loop** runs enforcement over and over, so the system is *self-correcting*.

Names to google, because they'll show up everywhere in your career:
**declarative vs imperative**, **single source of truth**, **reconciliation / control loop**,
**idempotency**, **pure function**, **separation of concerns**.

---

## 3. Three smaller decisions that make it clean

- **Pure decision functions.** `within_schedule()` and `sites_blocked()` don't touch files or
  UI — they just compute an answer. Pure functions are trivial to *test* (call with fake inputs,
  check the output) and impossible to get into a weird half-state. Keep your "brains" pure.
- **Precedence by order.** In the real app `sites_blocked` reads top-to-bottom: nuclear → clock-out
  → day-off → break → schedule. The *order of the `if`s literally is the rulebook.* When you add
  a feature, you're mostly deciding "where in this list does it go?"
- **Idempotency.** Running enforcement twice should be the same as running it once. That's why
  the real one only rewrites the hosts file when the block actually needs to change — so a loop
  every second is safe and cheap. ("Idempotent" = safe to repeat.)

---

## 4. Build it — do the TODOs in this order

Each TODO is one concept. Do them in order and test after each.

1. **`save_state` (TODO 1) — persistence.** Learn: files, `json`, `os.makedirs`. Test: run the
   app, close it, reopen — your bank/cheats should still be there once later TODOs change them.
2. **`within_schedule` (TODO 2) — time math.** Learn: `datetime`, minutes-since-midnight. Test:
   temporarily set `SCHEDULE_END` to a minute from now and watch it flip.
3. **`sites_blocked` (TODO 3) — the brain.** Learn: precedence, pure functions. Test: with no
   break it should be True in-hours; give yourself a fake break (`unlock_until` in the future)
   and it should be False.
4. **`apply_enforcement` (TODO 4) — the reconcile step.** Learn: the hosts file, string editing,
   admin rights. **Run as Administrator.** Test: during a blocked time, visit youtube.com — it
   should fail to load. Take a break — it should load.
5. **`complete_session` (TODO 5) — reward.** Learn: mutating state, why finishing matters. Test:
   set `SESSION_MIN` tiny, finish one, watch the bank jump +30 and cheats refill.
6. **`cheat` (TODO 6) — the shrinking ladder.** Learn: indexing a list as a "ladder." Test:
   click Cheat five times (5→0) and confirm the sixth does nothing.

When all six are in, you have a real, working focus app **that you built and can explain.**

---

## 5. Where to learn each piece (free, practical)

- **Python fundamentals:** *Automate the Boring Stuff with Python* (free online) and the official
  tutorial at docs.python.org/3/tutorial. You need: variables, dicts, functions, `if`, loops.
- **Reading/writing files + JSON:** docs.python.org/3/library/json.html — the `json.dump` /
  `json.load` examples are all you need for TODO 1.
- **Dates and time:** docs.python.org/3/library/datetime.html and `time.time()` (seconds since
  1970, "epoch"). That's the whole basis of every timer/break here.
- **Tkinter (the GUI):** Real Python's "Python GUI Programming With Tkinter" and TkDocs
  (tkdocs.com). Focus on: `Label`, `Button`, `.config()`, and `root.after(ms, fn)` — that
  `after` call *is* the loop.
- **The hosts file (what blocking really is):** search "what is the hosts file" — it's an OS
  file mapping names to IPs before DNS. Sending a domain to `0.0.0.0` = dead end.
- **The design pattern (the important part):** read react.dev's *"Thinking in React"* — its core
  lesson is "UI is a function of state," which is the same desired-state idea. Then google
  **"reconciliation loop"** / **"control loop"** and **"declarative vs imperative"**. If you want
  the deep end later, look at how a *thermostat controller* or a *Kubernetes controller* works —
  same shape at bigger scale.

---

## 6. After the six TODOs (stretch goals, in rough difficulty order)

1. Add a **time bank spend** button (subtract from bank, set `unlock_until`). Easy.
2. Add a **daily reset** (store today's date; if it changed, refill cheats). Easy–medium.
3. Add a **second rule** to `sites_blocked` (e.g., a "day off") and notice you're just inserting
   an `if` at the right spot. Medium.
4. Make enforcement **idempotent** (only rewrite the hosts file on a change). Medium.
5. Add a **notification** when a break ends. Medium.

Each one is a small, understandable step — that's the point. Build up from something you *own*.

Stuck on a TODO? Try it, then bring me what you wrote and I'll help you debug it (that's how
you'll actually learn — not by being handed the answer).
