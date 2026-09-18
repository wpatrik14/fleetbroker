import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fleetbroker import runner
from fleetbroker.probe import Decision


def _install_fake_probe(name: str, notify: bool):
    mod = types.ModuleType(name)
    mod.default_state = lambda: {"last_notify_epoch": 0}
    mod.gather = lambda cfg: {}
    mod.prepare_state = lambda state, data, now: None
    mod.decide = lambda data, derived, now: Decision(notify, 45, "test reason")
    mod.build_body = lambda data, derived, decision: "test body"
    sys.modules[name] = mod
    return mod


class TestRunnerCooldown(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()
        for name in list(sys.modules):
            if name.startswith("fake_probe_"):
                del sys.modules[name]

    def _config(self, probe_name: str, cooldown_seconds: int = 7200):
        return {
            "home": str(self.home),
            "probe": probe_name,
            "cooldown_seconds": cooldown_seconds,
            "relay": {"target_tmux_session": "claude"},
        }

    def _log_text(self) -> str:
        return (self.home / "log.txt").read_text()

    def test_decision_is_always_logged_even_when_no_notify(self):
        _install_fake_probe("fake_probe_no", notify=False)
        with patch.object(runner.relay, "relay") as mock_relay:
            runner.run(self._config("fake_probe_no"))
            mock_relay.assert_not_called()
        self.assertIn("no green light: test reason", self._log_text())

    def test_green_light_relays_and_logs(self):
        _install_fake_probe("fake_probe_go", notify=True)
        with patch.object(runner.relay, "relay") as mock_relay:
            runner.run(self._config("fake_probe_go"))
            mock_relay.assert_called_once()
        self.assertIn("GREEN LIGHT: test reason", self._log_text())

    def test_cooldown_suppresses_relay_but_still_logs_decision(self):
        _install_fake_probe("fake_probe_cd", notify=True)
        cfg = self._config("fake_probe_cd", cooldown_seconds=7200)
        with patch.object(runner.relay, "relay") as mock_relay:
            runner.run(cfg)  # first run: notifies, sets last_notify_epoch
            self.assertEqual(mock_relay.call_count, 1)
            runner.run(cfg)  # second run immediately after: cooldown active
            self.assertEqual(mock_relay.call_count, 1)  # not called again
        log = self._log_text()
        self.assertIn("green light but cooldown active", log)

    def test_gather_failure_logs_error_and_does_not_crash(self):
        mod = _install_fake_probe("fake_probe_err", notify=True)

        def boom(cfg):
            raise RuntimeError("HA is down")

        mod.gather = boom
        runner.run(self._config("fake_probe_err"))
        self.assertIn("ERROR gathering data: HA is down", self._log_text())

    def test_dry_run_never_calls_relay(self):
        _install_fake_probe("fake_probe_dry", notify=True)
        with patch.object(runner.relay, "relay") as mock_relay:
            runner.run(self._config("fake_probe_dry"), dry_run=True)
            mock_relay.assert_not_called()
        self.assertIn("[dry-run] would relay", self._log_text())

    def test_heartbeat_fires_once_per_tick_regardless_of_decision(self):
        _install_fake_probe("fake_probe_hb", notify=False)
        cfg = self._config("fake_probe_hb")
        cfg["heartbeat"] = {"url": "https://kuma.example.com/x"}
        with patch.object(runner.heartbeat, "push") as mock_push:
            runner.run(cfg)
        mock_push.assert_called_once_with(self.home, cfg["heartbeat"])

    def test_heartbeat_still_fires_on_gather_failure(self):
        mod = _install_fake_probe("fake_probe_hb_err", notify=True)
        mod.gather = lambda cfg: (_ for _ in ()).throw(RuntimeError("boom"))
        cfg = self._config("fake_probe_hb_err")
        cfg["heartbeat"] = {"url": "https://kuma.example.com/x"}
        with patch.object(runner.heartbeat, "push") as mock_push:
            runner.run(cfg)
        mock_push.assert_called_once_with(self.home, cfg["heartbeat"])

    def test_heartbeat_not_called_when_not_configured(self):
        _install_fake_probe("fake_probe_no_hb", notify=False)
        with patch.object(runner.heartbeat, "push") as mock_push:
            runner.run(self._config("fake_probe_no_hb"))
        mock_push.assert_called_once_with(self.home, None)


if __name__ == "__main__":
    unittest.main()
