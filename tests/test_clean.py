"""StudyAnchor ships family-friendly: no profanity in anything it says, shows or documents."""
import ast
import os
import re
import unittest

import support  # noqa: F401  (puts the project on sys.path and sandboxes core)
import core
import focusapp as fa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# whole words only, so "class", "shell" or "assume" never trip it
BANNED = ["fuck", "fucking", "fucker", "shit", "shitty", "damn", "goddamn", "dammit", "bitch", "bastard",
          "asshole", "ass", "dumbass", "jackass", "crap", "piss", "pissed", "dick", "cunt", "bullshit", "wtf"]
PATTERN = re.compile(r"\b(" + "|".join(BANNED) + r")\b", re.IGNORECASE)


def literals(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


class NoProfanity(unittest.TestCase):
    def test_the_filter_catches_what_it_should(self):
        for bad in ("Get the fuck back to work", "lazy shit", "goddamn phone", "you dumbass", "WTF"):
            self.assertTrue(PATTERN.search(bad), bad)

    def test_the_filter_leaves_ordinary_words_alone(self):
        for ok in ("class assignment", "the shell", "assume nothing", "Hello", "classic", "passed", "massive"):
            self.assertFalse(PATTERN.search(ok), ok)

    def test_no_string_in_the_code_is_profane(self):
        for name in ("core.py", "focusapp.py", "guard.py", "run_tests.py"):
            for text in literals(os.path.join(ROOT, name)):
                self.assertIsNone(PATTERN.search(text), f"{name}: {text!r}")

    def test_the_docs_are_clean(self):
        for name in ("README.md", "FEATURES.md", "ARCHITECTURE.md"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    self.assertIsNone(PATTERN.search(line), f"{name}:{n}: {line.strip()}")

    def test_the_spoken_lines_are_clean_and_non_empty(self):
        n = fa.Notifier
        for group in (n.NAG_LINES, n.MAD_LINES, fa.FocusApp.START_LINES):
            self.assertTrue(group)
            for line in group:
                self.assertTrue(line.strip())
                self.assertIsNone(PATTERN.search(line), line)

    def test_the_top_level_lines_are_still_firm(self):
        # clean does not mean toothless: the "really mad" set stays distinct from the normal nags
        self.assertEqual(len(fa.Notifier.MAD_LINES), len(set(fa.Notifier.MAD_LINES)))
        self.assertFalse(set(fa.Notifier.MAD_LINES) & set(fa.Notifier.NAG_LINES))

    def test_default_text_in_the_state_is_clean(self):
        st = core.default_state()
        for value in st.values():
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, str):
                    self.assertIsNone(PATTERN.search(item), item)


class ShipsWithNoPersonalRecordings(unittest.TestCase):
    def test_the_recordings_feature_is_still_there_but_empty_folder_is_fine(self):
        self.assertTrue(callable(fa.list_customs))
        self.assertEqual(fa.list_customs() if not os.path.isdir(fa.SOUNDS_DIR) else
                         [p for p in fa.list_customs() if not p.lower().endswith(".wav")], [])

    def test_the_sounds_readme_explains_how_to_add_your_own(self):
        with open(os.path.join(ROOT, "sounds", "README.txt"), encoding="utf-8") as f:
            self.assertIn(".wav", f.read())


if __name__ == "__main__":
    unittest.main()
