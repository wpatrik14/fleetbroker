"""This logic used to be inlined directly in cli.py's cmd_doctor/cmd_status
with zero test coverage of its own. Extracting it into
fleetbroker.adapters.claude.status (issue #1's core/adapter split) made it
directly testable in isolation - these are new tests, not moved ones."""

import subprocess
import unittest
from unittest.mock import patch

from fleetbroker.adapters.claude import status


class TestGetAuthStatus(unittest.TestCase):
    def test_parses_json_output_on_success(self):
        fake = subprocess.CompletedProcess(
            [], 0, stdout='{"loggedIn": true, "email": "x@example.com"}', stderr=""
        )
        with patch("subprocess.run", return_value=fake):
            result = status.get_auth_status()
        self.assertTrue(result.ok)
        self.assertEqual(result.info["email"], "x@example.com")

    def test_non_json_stdout_does_not_raise(self):
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="not logged in")
        with patch("subprocess.run", return_value=fake):
            result = status.get_auth_status()
        self.assertFalse(result.ok)
        self.assertIsNone(result.info)
        self.assertEqual(result.raw, "not logged in")


class TestGetVersionString(unittest.TestCase):
    def test_returns_stdout_when_present(self):
        fake = subprocess.CompletedProcess([], 0, stdout="2.1.267 (Claude Code)\n", stderr="")
        with patch("subprocess.run", return_value=fake):
            self.assertEqual(status.get_version_string(), "2.1.267 (Claude Code)")

    def test_falls_back_to_stderr_when_stdout_empty(self):
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="command not found\n")
        with patch("subprocess.run", return_value=fake):
            self.assertEqual(status.get_version_string(), "command not found")


class TestTmuxSessionHealth(unittest.TestCase):
    def test_missing_session_reports_not_exists(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            health = status.tmux_session_health("claude")
        self.assertFalse(health.exists)
        self.assertEqual(health.panes, [])
        self.assertFalse(health.has_live_claude_pane)

    def test_existing_session_with_live_pane(self):
        has_session = subprocess.CompletedProcess([], 0)
        list_panes = subprocess.CompletedProcess([], 0, stdout="claude\n", stderr="")
        with patch("subprocess.run", side_effect=[has_session, list_panes]):
            health = status.tmux_session_health("claude")
        self.assertTrue(health.exists)
        self.assertTrue(health.has_live_claude_pane)

    def test_existing_session_with_dead_pane(self):
        has_session = subprocess.CompletedProcess([], 0)
        list_panes = subprocess.CompletedProcess([], 0, stdout="bash\n", stderr="")
        with patch("subprocess.run", side_effect=[has_session, list_panes]):
            health = status.tmux_session_health("claude")
        self.assertTrue(health.exists)
        self.assertFalse(health.has_live_claude_pane)


class TestClaudeBinary(unittest.TestCase):
    def test_returns_none_when_not_found(self):
        with patch("shutil.which", return_value=None):
            self.assertIsNone(status.claude_binary())

    def test_returns_path_when_found(self):
        with patch("shutil.which", return_value="/usr/bin/claude"):
            self.assertEqual(status.claude_binary(), "/usr/bin/claude")


if __name__ == "__main__":
    unittest.main()
