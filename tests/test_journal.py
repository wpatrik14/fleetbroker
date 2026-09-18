import tempfile
import unittest
from pathlib import Path

from fleetbroker import journal


class TestJournal(unittest.TestCase):
    def test_creates_home_dir_if_missing(self):
        # Regression: fleetbroker doctor checks but does not create `home`,
        # so a heartbeat-push failure logged before the node's first real
        # `run` used to crash with FileNotFoundError instead of just logging.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "not-created-yet" / "nested"
            self.assertFalse(home.exists())
            journal.log(home, "hello")
            self.assertEqual((home / "log.txt").read_text().strip().split(" ", 1)[1], "hello")

    def test_appends_to_existing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            journal.log(home, "first")
            journal.log(home, "second")
            lines = (home / "log.txt").read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].endswith("first"))
            self.assertTrue(lines[1].endswith("second"))


if __name__ == "__main__":
    unittest.main()
