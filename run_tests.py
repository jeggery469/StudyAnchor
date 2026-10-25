"""Run the whole Focus test suite.

    python run_tests.py            # everything (~2 minutes: it opens real, hidden windows)
    python run_tests.py --fast     # skip the window tests (~10 seconds)
    python run_tests.py -v         # list every test as it runs

The tests never touch your real hosts file or state: every test works in a scratch folder.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(HERE, "tests")
sys.path.insert(0, TESTS)
sys.path.insert(0, HERE)

WINDOW_TESTS = ("test_app_actions.py", "test_app_runtime.py")


def build(fast=False):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in sorted(os.listdir(TESTS)):
        if name.startswith("test_") and name.endswith(".py"):
            if fast and name in WINDOW_TESTS:
                continue
            suite.addTests(loader.loadTestsFromName(name[:-3]))
    return suite


def main(argv):
    fast = "--fast" in argv
    verbosity = 2 if "-v" in argv else 1
    result = unittest.TextTestRunner(verbosity=verbosity).run(build(fast))
    print("\n%s  (%d tests%s)" % ("ALL PASSED" if result.wasSuccessful() else "FAILED",
                                  result.testsRun, ", window tests skipped" if fast else ""))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
