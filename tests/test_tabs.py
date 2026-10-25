"""The tab layout: Dashboard, Bank, Learning, Reminders, Settings. The old Usage tab is gone and the
old Schedule tab's (read-only) hours now sit at the top of Settings, which scrolls."""
import unittest

from appsupport import AppCase
import core
import focusapp as fa

TABS = ["Dashboard", "Bank", "Learning", "Reminders", "Settings"]


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


def ancestors(w):
    out = []
    while w is not None:
        out.append(w)
        w = getattr(w, "master", None)
    return out


def every_widget(w):
    for c in w.winfo_children():
        yield c
        yield from every_widget(c)


def texts(root_widget):
    out = []
    for w in every_widget(root_widget):
        try:
            out.append(str(w.cget("text")))
        except Exception:
            pass
    return out


@both
class TheTabs(AppCase):
    def tab_names(self):
        if self.CTK:
            return list(self.app.tabs._tab_dict.keys())
        nb = self.app._nb
        return [nb.tab(t, "text") for t in nb.tabs()]

    def test_the_tabs_in_order(self):
        self.app._show_full()
        self.assertEqual(self.tab_names(), TABS)

    def test_there_is_no_usage_or_schedule_tab(self):
        self.app._show_full()
        for gone in ("Usage", "Schedule"):
            self.assertNotIn(gone, self.tab_names())
        self.assertFalse(hasattr(self.app, "tab_sched"))
        self.assertFalse(hasattr(self.app, "tab_usage"))

    def test_every_remaining_tab_has_content(self):
        self.app._show_full()
        for tab in (self.app.tab_dash, self.app.tab_bank, self.app.tab_learn, self.app.tab_rem, self.app.tab_set):
            self.assertTrue(tab.winfo_children())


@both
class HoursInSettings(AppCase):
    def setUp(self):
        super().setUp()
        self.app._show_full()
        self.app._render_schedule()

    def test_the_hours_live_inside_the_settings_tab(self):
        for name in ("s_hours", "s_hours_weekend", "s_clock"):
            self.assertIn(self.app.tab_set, ancestors(getattr(self.app, name)), name)

    def test_they_show_the_real_hours(self):
        self.assertEqual(self.text_of(self.app.s_hours), "07:00  →  00:00")
        self.assertEqual(self.text_of(self.app.s_hours_weekend), "10:00  →  18:00")
        self.assertIn("23:59", self.text_of(self.app.s_clock))

    def test_they_follow_the_state(self):
        self.st["clockout_time"] = ""
        self.app._render_schedule()
        self.assertIn("off", self.text_of(self.app.s_clock))

    def test_the_hours_are_read_only(self):
        for name in ("save_schedule", "s_start", "s_end", "s_clockout"):
            self.assertFalse(hasattr(self.app, name), name)

    def test_it_says_they_are_locked(self):
        all_text = " ".join(texts(self.app.tab_set))
        self.assertIn("Active hours", all_text)
        self.assertIn("Locked", all_text)
        self.assertIn("can't be changed", all_text)

    def test_the_hours_are_the_first_thing_in_the_tab(self):
        # the hours block comes before the settings fields in pack order
        every = [w for w in every_widget(self.app._set_scroll)]
        hours_i = every.index(self.app.s_hours)
        entry_i = every.index(self.app.set_entries["session_length_min"])
        self.assertLess(hours_i, entry_i)

    def test_all_the_old_settings_are_still_there(self):
        self.assertEqual(set(self.app.set_entries),
                         {"session_length_min", "snooze_min", "daily_study_cap_min", "steam_break_min",
                          "steam_cooldown_min"})
        for name in ("strobe_var", "add_site", "set_block", "set_msg", "slider_widgets"):
            self.assertTrue(hasattr(self.app, name), name)
        all_text = " ".join(texts(self.app.tab_set))
        for needle in ("Save settings", "Test notification", "Add site", "Blocked sites"):
            self.assertIn(needle, all_text)

    def test_the_hours_stay_in_sync_when_the_state_changes_via_refresh(self):
        self.st["weekend_schedule_end"] = "17:00"
        self.app._render_schedule()
        self.assertIn("17:00", self.text_of(self.app.s_hours_weekend))


@both
class SettingsScrolls(AppCase):
    def setUp(self):
        super().setUp()
        self.app._show_full()

    def canvas(self):
        sc = self.app._set_scroll
        return getattr(sc, "_parent_canvas", None) or getattr(sc, "_canvas", None)

    def test_the_settings_tab_is_a_scroll_area(self):
        self.assertIn(self.app.tab_set, ancestors(self.app._set_scroll))
        self.assertIsNotNone(self.canvas())

    def test_everything_is_built_inside_the_scroll_area(self):
        for w in (self.app.s_hours, self.app.add_site, self.app.set_block, self.app.set_entries["snooze_min"]):
            self.assertIn(self.app._set_scroll, ancestors(w))

    def test_the_save_button_is_reachable_by_scrolling(self):
        found = [w for w in every_widget(self.app._set_scroll) if hasattr(w, "invoke")
                 and str(w.cget("text")) == "Save settings"]
        self.assertEqual(len(found), 1)
        self.assertIn(self.app._set_scroll, ancestors(found[0]))

    def test_the_scroll_area_scrolls_when_content_is_taller_than_the_tab(self):
        self.app.root.update()
        self.app.root.update_idletasks()
        canvas = self.canvas()
        region = canvas.bbox("all")
        self.assertIsNotNone(region)
        content_h = region[3] - region[1]
        self.assertGreater(content_h, canvas.winfo_height())       # taller than what's visible...
        canvas.yview_moveto(0.0)
        top = canvas.yview()
        canvas.yview_moveto(1.0)
        bottom = canvas.yview()
        self.assertEqual(top[0], 0.0)
        self.assertGreater(bottom[0], top[0])                       # ...so scrolling moves the view
        self.assertAlmostEqual(bottom[1], 1.0, places=2)

    def test_the_save_button_is_fully_on_screen_once_scrolled_to_the_bottom(self):
        import time as real_time                      # (the app's own `time` is faked in these tests)
        # losing focus folds the full window into the popout (correct, but it would move everything we
        # measure), so keep that out of this measurement
        self.app._check_root_focus_lost = lambda: None
        if self.CTK:
            self.app.tabs.set("Settings")
        else:
            self.app._nb.select(self.app.tab_set)

        def settle(done, tries=80):
            for _ in range(tries):
                self.app.root.update_idletasks()
                self.app.root.update()
                if done():
                    return True
                real_time.sleep(0.05)
            return done()
        canvas = self.canvas()
        self.assertTrue(settle(lambda: canvas.winfo_height() > 100), "the Settings area never got a height")
        save = [w for w in every_widget(self.app._set_scroll) if hasattr(w, "invoke")
                and str(w.cget("text")) == "Save settings"][0]
        canvas.yview_moveto(1.0)
        settle(lambda: canvas.yview()[0] > 0.0)
        settle(lambda: False, tries=6)
        root = self.app.root
        bottom = save.winfo_rooty() - root.winfo_rooty() + save.winfo_height()
        self.assertLessEqual(bottom, root.winfo_height(), f"Save button bottom at {bottom}px")
        self.assertGreater(save.winfo_rooty(), root.winfo_rooty())

    def test_saving_works_from_the_merged_tab(self):
        self.st["snooze_min"] = 10
        for key, ent in self.app.set_entries.items():
            self.app._set_entry(ent, str(self.st[key]))
        self.app._set_entry(self.app.set_entries["session_length_min"], "60")
        self.app.save_settings()
        self.assertEqual(self.st["session_length_min"], 60)
        self.assertEqual(core.load_state()["session_length_min"], 60)

    def test_adding_a_site_works_from_the_merged_tab(self):
        self.app._set_entry(self.app.add_site, "example-merge-test.com")
        self.app.add_blocked_site()
        self.assertIn("example-merge-test.com", self.st["blocklist"])


if __name__ == "__main__":
    unittest.main()
