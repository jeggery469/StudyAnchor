"""One logo, everywhere: the anchor. Same artwork for the window icon, both headers, the tutorial and the docs."""
import os
import re
import unittest
from unittest import mock

import support  # noqa: F401
from appsupport import AppCase
import core
import focusapp as fa
import tutorial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNG = os.path.join(ROOT, "logo.png")
ICO = os.path.join(ROOT, "logo.ico")

MINT = (18, 201, 154)      # the app's green  (C["green"])
GOLD = (245, 196, 81)      # the app's gold   (C["gold"])
NAVY = (11, 57, 72)        # the app's background (C["bg"])


def both(cls):
    plain = type(cls.__name__ + "Plain", (cls,), {"CTK": False})
    globals()[plain.__name__] = plain
    return cls


def every_widget(w):
    for c in w.winfo_children():
        yield c
        yield from every_widget(c)


def logos(root_widget):
    return [w for w in every_widget(root_widget) if getattr(w, "is_logo", False)]


def texts(root_widget):
    out = []
    for w in every_widget(root_widget):
        try:
            out.append(str(w.cget("text")))
        except Exception:
            pass
    return out


def near(pixel, colour, tol=14):
    return all(abs(pixel[i] - colour[i]) <= tol for i in range(3))


class TheArtwork(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.Image = Image
        self.img = Image.open(PNG).convert("RGBA")

    def test_the_files_exist_and_the_old_one_is_gone(self):
        self.assertTrue(os.path.isfile(PNG))
        self.assertTrue(os.path.isfile(ICO))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "focus.png")))      # the old bullseye

    def test_it_is_a_big_square_with_transparency(self):
        w, h = self.img.size
        self.assertEqual(w, h)
        self.assertGreaterEqual(w, 256)
        self.assertEqual(self.img.getpixel((0, 0))[3], 0)                      # rounded corners are see-through
        self.assertEqual(self.img.getpixel((w // 2, h // 2))[3], 255)

    def test_it_uses_the_apps_own_colours(self):
        px = list(self.img.getdata())
        for name, colour in (("mint", MINT), ("gold", GOLD), ("navy", NAVY)):
            hits = sum(1 for p in px if p[3] == 255 and near(p, colour))
            self.assertGreater(hits, 400, f"not enough {name} in the logo")

    def test_it_is_not_just_a_flat_tile(self):
        # the anchor itself: mint should occupy a modest share of the image, not none and not everything
        px = [p for p in self.img.getdata() if p[3] == 255]
        mint = sum(1 for p in px if near(p, MINT)) / len(px)
        self.assertGreater(mint, 0.04)
        self.assertLess(mint, 0.40)

    def test_the_icon_file_has_the_usual_windows_sizes(self):
        ico = self.Image.open(ICO)
        sizes = set(ico.info.get("sizes", {ico.size}))
        for s in ((16, 16), (32, 32), (48, 48), (256, 256)):
            self.assertIn(s, sizes)

    def test_the_icon_and_png_are_the_same_picture(self):
        ico = self.Image.open(ICO)
        ico.size = (256, 256)
        big = ico.convert("RGBA").resize(self.img.size)
        a, b = list(self.img.getdata()), list(big.getdata())
        diff = sum(1 for x, y in zip(a, b) if abs(x[0] - y[0]) + abs(x[1] - y[1]) + abs(x[2] - y[2]) > 60)
        self.assertLess(diff / len(a), 0.02)


@both
class ShownInTheApp(AppCase):
    def test_the_app_points_at_the_one_logo_file(self):
        self.assertEqual(os.path.normcase(fa.LOGO_FILE), os.path.normcase(PNG))
        self.assertTrue(os.path.isfile(fa.LOGO_FILE))

    def test_the_window_icon_is_that_logo(self):
        self.assertIsNotNone(self.app._icon_img)
        self.assertEqual(self.app._icon_img.width(), 256)

    def test_the_popout_header_shows_the_logo_and_the_name(self):
        self.assertEqual(len(logos(self.app.popout)), 1)
        self.assertIn("StudyAnchor", texts(self.app.popout))

    def test_the_full_window_header_shows_the_logo_and_the_name(self):
        self.app._show_full()
        header = [w for w in self.app.full.winfo_children()][0]
        self.assertEqual(len(logos(header)), 1)
        self.assertIn("StudyAnchor", texts(header))

    def test_the_tutorial_shows_the_logo(self):
        t = self.app.show_tutorial()
        try:
            self.assertEqual(len(logos(t["win"])), 1)
        finally:
            self.app._tut_close()

    def test_every_logo_label_holds_its_image(self):
        self.app._show_full()
        for w in logos(self.app.popout) + logos(self.app.full):
            self.assertIsNotNone(w._logo)

    def test_the_old_diamond_mark_is_gone_from_the_headers(self):
        self.app._show_full()
        for t in texts(self.app.popout) + texts(self.app.full):
            self.assertNotIn("◆", t)

    def test_a_missing_logo_file_falls_back_to_the_anchor_symbol_not_a_crash(self):
        with mock.patch.object(fa, "LOGO_FILE", os.path.join(ROOT, "no_such_logo.png")):
            w = fa.WLogo(self.app.root, 20, fa.C["bg"])
        try:
            self.assertFalse(getattr(w, "is_logo", False))
            self.assertEqual(str(w.cget("text")), "⚓")
        finally:
            w.destroy()

    def test_the_logo_helper_makes_a_labelled_image_at_any_size(self):
        for size in (16, 20, 30, 52, 96):
            w = fa.WLogo(self.app.root, size, fa.C["bg"])
            try:
                self.assertTrue(w.is_logo, size)
            finally:
                w.destroy()


class OneMarkEverywhere(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_no_stray_old_marks_in_the_code_or_docs(self):
        for name in ("focusapp.py", "tutorial.py", "core.py", "guard.py", "README.md", "FEATURES.md",
                     "ARCHITECTURE.md"):
            text = self.read(name)
            self.assertNotIn("◆", text, name)
            self.assertNotIn("🎯", text, name)

    def test_nothing_still_points_at_the_old_logo_file(self):
        for name in ("focusapp.py", "README.md", "FEATURES.md", "ARCHITECTURE.md", "Setup.bat", "Start Focus.bat",
                     "Install Forever.bat", "Restart Focus.bat"):
            self.assertNotIn("focus.png", self.read(name), name)

    def test_the_readme_shows_the_logo_that_exists(self):
        readme = self.read("README.md")
        m = re.search(r'<img src="([^"]+)"', readme)
        self.assertIsNotNone(m)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, m.group(1))), m.group(1))
        self.assertEqual(m.group(1), "logo.png")
        self.assertIn("\n# StudyAnchor\n", readme)

    def test_the_readme_file_table_lists_the_logo_files(self):
        readme = self.read("README.md")
        self.assertIn("logo.png", readme)
        self.assertIn("logo.ico", readme)

    def test_the_tutorial_title_has_no_stray_emoji_in_front_of_the_name(self):
        first = tutorial.steps()[0][0]
        self.assertEqual(first, "Welcome to StudyAnchor")

    def test_the_footer_uses_the_anchor(self):
        self.assertIn("Study hard. ⚓", self.read("README.md"))

    def test_the_console_messages_use_the_new_name(self):
        for name in ("Restart Focus.bat", "Install Forever.bat"):
            text = self.read(name)
            self.assertIn("StudyAnchor", text, name)

    def test_the_docs_do_not_overclaim_platform_support(self):
        readme = self.read("README.md")
        self.assertIn("Windows 10/11 is the supported platform", readme)
        self.assertIn("untested", readme)
        features = self.read("FEATURES.md")
        self.assertIn("Windows 10/11 is the supported platform", features)
        self.assertNotIn("macOS / Linux** run the app too", readme)

    def test_the_internal_names_that_must_not_change_are_unchanged(self):
        # the install tasks, data folder and hosts markers keep their old names on purpose
        self.assertIn("FocusGuard", self.read("Install Forever.bat"))
        self.assertIn("FocusApp", self.read("Install Forever.bat"))
        self.assertIn("FOCUS-BLOCK START", core.MARK_START)
        self.assertTrue(core.DATA_DIR)                                  # (sandboxed here, but still set)


if __name__ == "__main__":
    unittest.main()
