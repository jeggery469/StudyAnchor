"""
FOCUS — STARTER  (you build it)
================================

This is a clean, minimal skeleton of Focus. The boring plumbing (the window, the
loop, reading the hosts file) is done for you. The *brains* are left as six
numbered TODOs. Fill them in, in order (1 → 6). Each one makes a feature work.

It already RUNS as-is — you'll just see a window where the buttons don't do much
yet. As you finish each TODO, more of it comes alive.

Run it:
    python focus_starter.py
Once you reach the blocking TODOs, run it "as Administrator" (right-click the
terminal → Run as administrator) — editing the hosts file needs admin rights.

Read LEARN.md alongside this. It explains *why* the code is shaped this way.
"""

import os
import json
import time
import datetime
import tkinter as tk

# ============================ CONFIG ============================
BLOCKLIST = ["youtube.com", "instagram.com", "tiktok.com", "reddit.com"]
SCHEDULE_START = "08:00"          # blocking is on between these times...
SCHEDULE_END = "22:00"            # ...and off outside them
CHEAT_LADDER = [5, 5, 5, 5, 5, 0] # five 5-minute cheats a day, then none
SESSION_MIN = 25                  # length of a study session
SESSION_REWARD_MIN = 30           # bank minutes earned for finishing one

STATE_PATH = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                          "FocusStarter", "state.json")
HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
MARK_START = "# ==== FOCUS-STARTER START ===="
MARK_END = "# ==== FOCUS-STARTER END ===="


# ============================ STATE ============================
# The state dict is the SINGLE SOURCE OF TRUTH. Everything the app "knows" lives
# here, and it's saved to a JSON file so it survives restarts.
#
# You'll see a parameter named `st` passed into most functions below — that is ALWAYS
# this same dict. "Decision" functions only READ it; "action" functions MODIFY it and save.
def default_state():
    return {
        "unlock_until": 0,     # epoch time until which sites are free (a break)
        "cheat_index": 0,      # how many cheats used today (index into CHEAT_LADDER)
        "time_bank_min": 0,    # break minutes you've earned
        "session_end": 0,      # epoch time the current session ends (0 = no session)
    }

def load_state():
    try:
        with open(STATE_PATH) as f:
            data = json.load(f)
        st = default_state()
        st.update(data)        # defaults first, then saved values on top
        return st
    except Exception:
        return default_state()

def save_state(st):
    # GOAL:       write the app's memory to disk so it survives closing the program.
    # PARAMETER   st = the state dict (the app's whole memory: unlock_until, cheat_index,
    #                  time_bank_min, session_end). You're saving this entire dict to a file.
    # RETURNS:    nothing (its job is the side effect of writing the file).
    # ---- TODO 1 : DONE (written by you) ---------------------------------------
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(st, f)


# ============================ SCHEDULE ============================
def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def within_schedule():
    # GOAL:       answer "is it currently inside my active hours?" (when blocking applies).
    # PARAMETERS: none — it reads the clock (datetime.now()) and the SCHEDULE_START / SCHEDULE_END config.
    # RETURNS:    True if now is inside the window, else False.
    # ---- TODO 2 : DONE (written by you) ----------------------------------------
    start = _to_min(SCHEDULE_START)
    end = _to_min(SCHEDULE_END)
    now = datetime.datetime.now()
    cur = now.hour * 60 + now.minute
    if start <= cur < end:
        return True
    else:
        return False


# ============================ THE DECISION (the brain) ============================
def sites_blocked(st):
    # GOAL:       THE core decision — should the blocklist be blocked RIGHT NOW?
    # PARAMETER   st = the state dict. You only READ from it here (e.g. st["unlock_until"]);
    #                  never change it in a decision function.
    # RETURNS:    True  = block the sites,   False = leave them open.
    # ---- TODO 3 : DONE (written by you) ---------------------------------------
    if st["unlock_until"] > time.time():
        return False
    elif within_schedule():
        return True
    else:
        return False


# ============================ ENFORCEMENT (make reality match) ============================
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
        return False  # (probably not running as Administrator)

def _strip_block(text):
    """Remove any FOCUS-STARTER section we added before (leave the rest alone)."""
    out, skip = [], False
    for ln in text.splitlines():
        if ln.strip() == MARK_START:
            skip = True; continue
        if ln.strip() == MARK_END:
            skip = False; continue
        if not skip:
            out.append(ln)
    return "\n".join(out)

def apply_enforcement(st):
    # GOAL:       make the REAL hosts file match the yes/no from sites_blocked(st).
    #             This is the "reconcile" step — it turns the decision into reality.
    # PARAMETER   st = the state dict. You pass it straight to sites_blocked(st) to get
    #                  the decision, then edit the file to match.
    # RETURNS:    nothing (side effect = the hosts file is rewritten).
    # ---- TODO 4 : DONE (written by you) ---------------------------------------
    base = _strip_block(_read_hosts())
    if sites_blocked(st):
        lines = [MARK_START]
        for domain in BLOCKLIST:
            lines.append("0.0.0.0 " + domain)
            lines.append("0.0.0.0 www." + domain)
        lines.append(MARK_END)
        base = base.rstrip() + "\n" + "\n".join(lines) + "\n"
    _write_hosts(base)


# ============================ ACTIONS (change state) ============================
def start_or_stop_session(st):
    if st["session_end"]:                       # already running -> stop it
        st["session_end"] = 0
    else:
        st["session_end"] = time.time() + SESSION_MIN * 60
        st["unlock_until"] = 0                   # starting means: lock in now
    save_state(st)

def complete_session(st):
    # GOAL:       reward the user when a study session's timer reaches zero.
    # PARAMETER   st = the state dict. Here you MODIFY it (add to the bank, refill cheats,
    #                  clear session_end) and then save it.
    # RETURNS:    nothing (it changes st and writes it).
    # ---- TODO 5 : DONE (written by you) ---------------------------------------
    st["time_bank_min"] += SESSION_REWARD_MIN
    st["cheat_index"] = 0
    st["session_end"] = 0
    save_state(st)

def cheat(st):
    # GOAL:       grant a short "cheat" break that gets shorter each use (5,5,5,5,5,0).
    # PARAMETER   st = the state dict. You READ st["cheat_index"] to see how many you've used,
    #                  then MODIFY st (bump the index, set unlock_until) and save.
    # RETURNS:    nothing.
    # ---- TODO 6 : DONE (written by you) ---------------------------------------
    i = min(st["cheat_index"], len(CHEAT_LADDER) - 1)
    mins = CHEAT_LADDER[i]
    if mins <= 0:
        return
    st["cheat_index"] = i + 1
    st["unlocked_until"] = time.time() + mins * 60
    save_state(st)


# ============================ UI + LOOP (done for you) ============================
def fmt(sec):
    sec = max(0, int(sec)); return f"{sec//60:02d}:{sec%60:02d}"

def cheats_left(st):
    i = min(st["cheat_index"], len(CHEAT_LADDER) - 1)
    return sum(1 for m in CHEAT_LADDER[i:] if m > 0)

class App:
    def __init__(self):
        self.st = load_state()
        self.root = tk.Tk()
        self.root.title("Focus (starter)")
        self.root.geometry("320x230")
        self.root.configure(bg="#122230")
        self.status = tk.Label(self.root, text="", bg="#122230", fg="#75dddd",
                               font=("Segoe UI", 16, "bold")); self.status.pack(pady=(18, 2))
        self.info = tk.Label(self.root, text="", bg="#122230", fg="#9fb4bd",
                             font=("Segoe UI", 10)); self.info.pack()
        self.btn_study = tk.Button(self.root, text="Start session", command=self.do_study,
                                   font=("Segoe UI", 11, "bold")); self.btn_study.pack(pady=(16, 4))
        tk.Button(self.root, text="Cheat break", command=self.do_cheat,
                  font=("Segoe UI", 11)).pack()
        self.tick()

    def do_study(self):
        start_or_stop_session(self.st); apply_enforcement(self.st); self.render()

    def do_cheat(self):
        cheat(self.st); apply_enforcement(self.st); self.render()

    def render(self):
        now = time.time()
        if self.st["session_end"]:
            self.status.config(text="STUDY " + fmt(self.st["session_end"] - now))
        elif self.st["unlock_until"] > now:
            self.status.config(text="BREAK " + fmt(self.st["unlock_until"] - now))
        elif sites_blocked(self.st):
            self.status.config(text="LOCKED IN")
        else:
            self.status.config(text="FREE")
        self.btn_study.config(text="Stop session" if self.st["session_end"] else "Start session")
        self.info.config(text=f"Bank: {self.st['time_bank_min']} min   ·   "
                              f"Cheats left: {cheats_left(self.st)}")

    def tick(self):
        # THE LOOP: every second, advance the session and reconcile reality to state.
        now = time.time()
        if self.st["session_end"] and now >= self.st["session_end"]:
            complete_session(self.st)
        apply_enforcement(self.st)     # keep the hosts file matching the state
        self.render()
        self.root.after(1000, self.tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
