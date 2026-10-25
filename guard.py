"""
guard.py - the headless "forever" enforcer.

Run by a scheduled task (as YOU, elevated, every minute). It reads the shared state and
makes the machine match it: blocks/unblocks sites and kills game launchers according to
the schedule, the active break, and nuclear mode. It also relaunches the Focus app if it
has been closed, so it's effectively always on. No window, no output.

    pythonw guard.py            # enforce once
    pythonw guard.py --off      # remove all blocking (used by uninstall)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core


def main(argv=None):
    """Returns a short string describing what it did (handy for tests and logs)."""
    argv = sys.argv if argv is None else argv
    if os.name != "nt":
        return "unsupported"
    if not core.is_admin():
        core.relaunch_as_admin()
        return "relaunched"
    if "--off" in argv:
        core.off()
        return "off"
    core.apply_enforcement(core.load_state())
    try:
        if not core.app_running():
            core.log_event("guard: Focus was not running - relaunching it")
            core.launch_app()
            return "enforced+launched"
    except Exception:
        pass
    return "enforced"


if __name__ == "__main__":
    main()
