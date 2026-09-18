import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fleetbroker import relay


class TestRelayArgv(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_argv_has_strict_mcp_config_and_empty_server_map(self):
        # Load-bearing regression test: an earlier design without
        # --strict-mcp-config spawned a full MCP-server roster on every
        # one-shot fire and hard-crashed the host container. This flag
        # combination must never regress silently.
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            relay.relay(self.home, {"target_tmux_session": "claude"}, "hello")

        argv = captured["argv"]
        self.assertEqual(argv[0], "claude")
        self.assertIn("-p", argv)
        self.assertIn("--strict-mcp-config", argv)
        mcp_idx = argv.index("--mcp-config")
        self.assertEqual(argv[mcp_idx + 1], '{"mcpServers":{}}')
        self.assertEqual(argv[-2], "--")  # separator immediately before the prompt
        self.assertEqual(captured["kwargs"].get("timeout"), 180)

    def test_timeout_is_configurable_but_defaults_to_180(self):
        captured = {}

        def fake_run(argv, **kwargs):
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            relay.relay(self.home, {"target_tmux_session": "claude", "timeout_seconds": 60}, "x")
        self.assertEqual(captured["kwargs"]["timeout"], 60)

    def test_relay_never_raises_on_timeout(self):
        # Regression: a TimeoutExpired here used to kill the whole run before
        # state was saved, so the cooldown never engaged and a new hung
        # process was spawned every subsequent tick.
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=180)):
            ok = relay.relay(self.home, {"target_tmux_session": "claude"}, "x")
        self.assertFalse(ok)

    def test_relay_never_raises_on_missing_binary(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            ok = relay.relay(self.home, {"target_tmux_session": "claude"}, "x")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
