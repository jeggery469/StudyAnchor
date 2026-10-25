# Focus — Starter (build it yourself)

A minimal skeleton of Focus. The plumbing is done; **you write the 6 brains** (the `TODO`s in
`focus_starter.py`). When they're all filled in, you have a real, working focus app you built.

## Run
```
python focus_starter.py
```
It runs immediately (buttons just won't do much yet). Once you reach the blocking TODOs, run your
terminal **as Administrator** — editing the Windows hosts file needs admin rights.

## Your checklist (do them in order)
- [ ] **TODO 1** — `save_state`: write state to a JSON file
- [ ] **TODO 2** — `within_schedule`: is the current time inside your active hours?
- [ ] **TODO 3** — `sites_blocked`: the decision — should sites be blocked right now?
- [ ] **TODO 4** — `apply_enforcement`: make the hosts file match that decision
- [ ] **TODO 5** — `complete_session`: reward finishing (+30 bank, refill cheats)
- [ ] **TODO 6** — `cheat`: a shrinking 5-4-3-2-1 cheat ladder

## Read this first
**`LEARN.md`** — how the design was found, the one big idea (desired state + a reconcile loop),
what each TODO teaches, and where to learn every piece. Start there.

## Files
- `focus_starter.py` — the skeleton with your TODOs
- `LEARN.md` — the lesson
- `README.md` — this file

> This is separate from the full app in the folder above — it's yours to grow. Nothing here
> touches the full version's settings (it uses its own `FocusStarter` state folder).
