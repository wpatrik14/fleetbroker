import subprocess
import unittest
from unittest.mock import patch

from fleetbroker.cli import _crontab_has_entry


def _fake_crontab(stdout: str):
    return subprocess.CompletedProcess(["crontab", "-l"], 0, stdout=stdout, stderr="")


class TestCrontabHasEntry(unittest.TestCase):
    def test_matches_exact_absolute_path(self):
        stdout = "5 * * * * /opt/fleetbroker/.venv/bin/fleetbroker run /root/.fleetbroker-quota/config.json\n"
        with patch("subprocess.run", return_value=_fake_crontab(stdout)):
            self.assertTrue(_crontab_has_entry("/root/.fleetbroker-quota/config.json"))

    def test_does_not_false_positive_on_shared_basename_in_different_dir(self):
        # Regression: two nodes both conventionally named "config.json" in
        # different home dirs used to make doctor() report a crontab entry
        # for a node that had none, because of an overly loose basename
        # fallback match.
        stdout = "5 * * * * ... /root/.fleetbroker-quota/config.json\n"
        with patch("subprocess.run", return_value=_fake_crontab(stdout)):
            self.assertFalse(_crontab_has_entry("/root/.fleetbroker-repowatch/config.json"))

    def test_relative_path_is_resolved_before_matching(self):
        import os
        stdout = f"5 * * * * ... {os.getcwd()}/config.json\n"
        with patch("subprocess.run", return_value=_fake_crontab(stdout)):
            self.assertTrue(_crontab_has_entry("config.json"))

    def test_no_crontab_returns_false_not_raise(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="no crontab")):
            self.assertFalse(_crontab_has_entry("/root/x/config.json"))


if __name__ == "__main__":
    unittest.main()
