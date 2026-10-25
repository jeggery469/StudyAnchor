"""Click the real buttons in every dialog (nuclear, bank, day-off code, popups, notifier)."""
import tkinter as tk
import unittest
from unittest import mock

from appsupport import AppCase
from support import MORNING
import core
import focusapp as fa


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


def button_text(widget):
    """The label of a clickable widget, or None if it is not a labelled button."""
    if not hasattr(widget, "invoke"):
        return None
    try:
        return widget.cget("text")
    except Exception:
        return None


class DialogCase(AppCase):
    def dialogs(self):
        a = self.app
        skip = {a.popout}
        if a.notifier.win is not None:
            skip.add(a.notifier.win)
        skip.update(a.notifier.decoys)
        return [w for w in a.root.winfo_children() if isinstance(w, tk.Toplevel) and w not in skip]

    def only_dialog(self):
        d = self.dialogs()
        self.assertEqual(len(d), 1, d)
        return d[0]

    def buttons(self, dlg):
        return {button_text(b): b for b in walk(dlg) if button_text(b)}

    def entry(self, dlg):
        for w in walk(dlg):
            if hasattr(w, "insert") and hasattr(w, "get") and not hasattr(w, "tag_add"):
                return w
        self.fail("no entry field in the dialog")

    def labels(self, dlg):
        out = []
        for w in walk(dlg):
            try:
                t = w.cget("text")
            except Exception:
                continue
            if t and not hasattr(w, "invoke"):
                out.append(t)
        return out

    def alive(self, dlg):
        try:
            return bool(dlg.winfo_exists())
        except Exception:
            return False


@both
class NuclearDialog(DialogCase):
    def open(self):
        before = set(self.dialogs())
        self.app.go_nuclear()
        new = [d for d in self.dialogs() if d not in before]
        self.assertEqual(len(new), 1)
        return new[0]

    def test_every_option_is_offered(self):
        b = self.buttons(self.open())
        self.assertEqual(set(b), {"30 minutes", "1 hour", "2 hours", "4 hours", "Rest of the day", "Cancel"})

    def test_each_duration_arms_the_right_lockdown(self):
        for label, minutes in (("30 minutes", 30), ("1 hour", 60), ("2 hours", 120), ("4 hours", 240)):
            self.st["nuclear_until"] = 0
            self.popups.clear()
            dlg = self.open()
            self.buttons(dlg)[label].invoke()
            self.assertEqual(self.st["nuclear_until"], MORNING + minutes * 60, label)
            self.assertFalse(self.alive(dlg), label)
            self.assertEqual(self.popup_titles(), ["☢ Nuclear armed"], label)

    def test_rest_of_the_day(self):
        self.buttons(self.open())["Rest of the day"].invoke()
        self.assertEqual(self.st["nuclear_until"], core.next_midnight(MORNING))

    def test_cancel_changes_nothing(self):
        dlg = self.open()
        self.buttons(dlg)["Cancel"].invoke()
        self.assertFalse(self.alive(dlg))
        self.assertEqual(self.st["nuclear_until"], 0)
        self.assertEqual(self.enforced, [])

    def test_a_stale_second_dialog_cannot_shorten_the_lockdown(self):
        first = self.open()
        second = self.open()
        self.buttons(first)["4 hours"].invoke()
        self.buttons(second)["30 minutes"].invoke()
        self.assertEqual(self.st["nuclear_until"], MORNING + 4 * 3600)


@both
class BankDialog(DialogCase):
    def open(self, bank):
        self.st["time_bank_minutes"] = bank
        self.app.spend_bank()
        return self.only_dialog()

    def test_offers_only_affordable_amounts_plus_all(self):
        self.assertEqual(set(self.buttons(self.open(7))), {"5 min", "All (7 min)"})

    def test_offers_every_amount_when_rich(self):
        self.assertEqual(set(self.buttons(self.open(100))), {"5 min", "15 min", "30 min", "All (100 min)"})

    def test_clicking_spends_and_closes(self):
        dlg = self.open(40)
        self.buttons(dlg)["15 min"].invoke()
        self.assertEqual(self.st["time_bank_minutes"], 25)
        self.assertEqual(self.st["unlock_until"], MORNING + 900)
        self.assertFalse(self.alive(dlg))

    def test_all_spends_everything(self):
        dlg = self.open(23)
        self.buttons(dlg)["All (23 min)"].invoke()
        self.assertEqual(self.st["time_bank_minutes"], 0)
        self.assertFalse(self.alive(dlg))

    def test_a_break_started_while_the_dialog_was_open_wins(self):
        dlg = self.open(40)
        self.st["unlock_until"] = MORNING + 5000
        self.buttons(dlg)["5 min"].invoke()
        self.assertEqual(self.st["time_bank_minutes"], 40)          # nothing was charged
        self.assertEqual(self.st["unlock_until"], MORNING + 5000)
        self.assertTrue(self.alive(dlg))

    def test_a_session_started_while_open_blocks_the_spend(self):
        dlg = self.open(40)
        self.app.session_active = True
        self.buttons(dlg)["5 min"].invoke()
        self.assertEqual(self.st["time_bank_minutes"], 40)

    def test_double_click_only_charges_once(self):
        dlg = self.open(40)
        b = self.buttons(dlg)["15 min"]
        b.invoke()
        try:
            b.invoke()
        except tk.TclError:
            pass                                                     # already destroyed
        self.assertEqual(self.st["time_bank_minutes"], 25)


@both
class CodeDialog(DialogCase):
    def open(self):
        self.app.disable_dialog()
        return self.only_dialog()

    def test_shows_the_instructions_and_a_three_digit_secret(self):
        dlg = self.open()
        self.assertIn("Guess the 3-digit code", self.labels(dlg))
        self.assertRegex(self.app.secret, r"^\d{3}$")

    def test_wrong_guess_clears_the_field_and_says_so(self):
        dlg = self.open()
        e = self.entry(dlg)
        e.insert(0, "abc")
        self.buttons(dlg)["Try"].invoke()
        self.assertEqual(e.get(), "")
        self.assertTrue(any("Wrong" in t for t in self.labels(dlg)))
        self.assertIn(("beeps", 1, 300, 120), self.beeped)
        self.assertTrue(self.alive(dlg))
        self.assertEqual(self.st["unlock_until"], 0)

    def test_right_guess_grants_a_break_until_midnight_and_closes(self):
        dlg = self.open()
        e = self.entry(dlg)
        e.insert(0, self.app.secret)
        self.buttons(dlg)["Try"].invoke()
        self.assertEqual(self.st["unlock_until"], core.next_midnight(MORNING))
        self.assertFalse(self.alive(dlg))
        self.assertEqual(self.popup_titles(), ["🌴 Break until midnight"])

    def test_the_code_changes_after_a_miss(self):
        dlg = self.open()
        seen = {self.app.secret}
        e = self.entry(dlg)
        for _ in range(40):
            e.delete(0, "end"); e.insert(0, "x")
            self.buttons(dlg)["Try"].invoke()
            seen.add(self.app.secret)
        self.assertGreater(len(seen), 5)

    def test_enter_key_submits(self):
        self.app._show_full()
        self.app.root.update()
        dlg = self.open()
        dlg.update()
        e = self.entry(dlg)
        e.insert(0, self.app.secret)
        inner = getattr(e, "_entry", e)
        inner.focus_force()
        dlg.update()
        inner.event_generate("<Return>", when="now")
        dlg.update()
        self.assertEqual(self.st["unlock_until"], core.next_midnight(MORNING))


@both
class RealPopup(DialogCase):
    def test_popup_shows_title_body_and_an_ok_button(self):
        type(self.app)._popup(self.app, "Hello", "world body", "#ffffff")
        dlg = self.only_dialog()
        self.assertEqual(dlg.title(), "Hello")
        self.assertIn("world body", self.labels(dlg))
        self.buttons(dlg)["OK"].invoke()
        self.assertFalse(self.alive(dlg))

    def test_several_popups_can_coexist(self):
        for i in range(3):
            type(self.app)._popup(self.app, f"T{i}", "b", "#fff")
        self.assertEqual(len(self.dialogs()), 3)


@both
class MiscWiring(DialogCase):
    def test_run_starts_the_mainloop(self):
        with mock.patch.object(self.app.root, "mainloop") as ml:
            self.app.run()
        ml.assert_called_once()

    def test_tab_change_without_a_name_reads_the_current_tab(self):
        with mock.patch.object(self.app, "_render_learning") as learn, mock.patch.object(self.app, "refresh_ui"):
            if self.CTK:
                self.app.tabs.set("Learning")
                self.app._on_tab_changed()
                learn.assert_called_once()
                self.app.tabs.set("Dashboard")
                self.app._on_tab_changed()
                learn.assert_called_once()
            else:
                self.app._on_tab_changed()                      # no tab widget: must not raise
                learn.assert_not_called()

    def test_closing_the_notifier_window_with_its_x_dismisses_the_alert(self):
        self.app.notifier.update(1, "H", "S")
        cmd = self.app.notifier.win.protocol("WM_DELETE_WINDOW")
        self.app.notifier.win.tk.call(cmd)
        self.assertIsNone(self.app.notifier.win)

    def test_notifier_buttons_are_wired(self):
        got = []
        n = self.app.notifier
        n.on_start = lambda: got.append("start")
        n.on_snooze = lambda: got.append("snooze")
        n.update(1, "H", "S")
        n._start_btn.invoke()
        n.update(1, "H", "S")
        n._snooze_btn.invoke()
        self.assertEqual(got, ["start", "snooze"])


@both
class ClickEveryButton(DialogCase):
    """Press the real buttons in the mini popout and the full window and check what they do."""

    def click(self, text, root=None):
        root = root or self.app.root
        found = [b for b in walk(root) if button_text(b) == text]
        self.assertEqual(len(found), 1, f"{text!r}: {len(found)} buttons")
        found[0].invoke()

    def mini(self, text):
        self.click(text, self.app.popout)

    def test_mini_popout_buttons(self):
        self.mini("▶ Study")
        self.assertTrue(self.app.session_active)
        self.mini("■ Stop")
        self.assertFalse(self.app.session_active)
        self.app.refresh_ui()
        self.mini("⚡ Cheat")
        self.assertEqual(self.st["cheat_index"], 1)
        self.fake.advance(400)
        self.mini("☕ Bank")
        self.assertIn("Bank empty", self.popup_titles())
        self.mini("🎮 Games")
        self.assertGreater(self.st["steam_break_until"], self.fake.now)
        self.mini("🔒 Lock in")
        self.assertEqual(self.st["steam_break_until"], 0)
        self.mini("😴")
        self.assertGreater(self.st["snooze_until"], self.fake.now)
        before = set(self.dialogs())
        self.mini("☢ Nuclear")
        self.assertEqual(len(set(self.dialogs()) - before), 1)

    def test_mini_pause_button_appears_during_a_session(self):
        self.mini("▶ Study")
        self.app.refresh_ui()
        self.mini("⏸ Pause")
        self.assertTrue(self.app.session_manual_paused)
        self.app.refresh_ui()
        self.mini("▶ Resume")
        self.assertFalse(self.app.session_manual_paused)

    def test_expand_and_collapse_buttons(self):
        self.mini("⤢")
        self.assertFalse(self.app.is_mini)
        self.click("⤡ popout")
        self.assertTrue(self.app.is_mini)

    def test_full_window_dashboard_buttons(self):
        self.app._show_full()
        self.click("▶  Start study session")
        self.assertTrue(self.app.session_active)
        self.click("⏸ Pause")
        self.assertTrue(self.app.session_manual_paused)
        self.app.toggle_session()                                   # stop, so break buttons are allowed
        self.app.session_manual_paused = False
        before = set(self.dialogs())
        self.click("☢ GO NUCLEAR")
        self.assertEqual(len(set(self.dialogs()) - before), 1)
        self.st["nuclear_until"] = 0
        before = set(self.dialogs())
        self.click("🌴 Disable for the day")
        self.assertEqual(len(set(self.dialogs()) - before), 1)
        self.assertRegex(self.app.secret, r"^\d{3}$")

    def test_full_window_break_row(self):
        self.app._show_full()
        labels = {button_text(b) for b in walk(self.app.tab_dash) if button_text(b)}
        for want in ("⚡ Cheat break", "☕ Bank", "🎮 Games", "🔒 Lock in now"):
            hit = [t for t in labels if want.split()[0] in t]
            self.assertTrue(hit, (want, labels))

    def test_bank_tab_button(self):
        self.app._show_full()
        self.st["time_bank_minutes"] = 20
        before = set(self.dialogs())
        self.click("☕ Spend bank time now")
        self.assertEqual(len(set(self.dialogs()) - before), 1)

    def test_settings_tab_buttons(self):
        self.app._show_full()
        self.click("Save settings")
        self.assertEqual(self.text_of(self.app.set_msg), "Saved.")
        self.click("🔔 Test notification")
        self.assertIsNotNone(self.app.notifier.win)
        self.app._set_entry(self.app.add_site, "clicked-site.org")
        self.click("＋ Add site")
        self.assertIn("clicked-site.org", self.st["blocklist"])

    def test_reminder_tab_buttons(self):
        self.app._show_full()
        self.app.rem_text.delete("1.0", "end"); self.app.rem_text.insert("1.0", "alpha\nbeta")
        self.click("💾 Save")
        self.assertEqual(self.st["reminders"], "alpha\nbeta")
        self.click("🔊 Read all")
        self.assertEqual(self.said[-1][0], "alpha. beta")
        self.click("🔊 Read one")
        self.assertIn(self.said[-1][0], ("alpha", "beta"))
        self.click("▶ Test")
        self.assertEqual(self.said[-1][0], "This is the voice that will read your reminders.")
        with mock.patch.object(fa, "list_customs", return_value=[]):
            self.click("🔊 Test recordings")
        self.assertIn("No recordings", self.text_of(self.app.rem_msg))


if __name__ == "__main__":
    unittest.main()
