import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fleetbroker import cli
from fleetbroker.probe import Decision


def _install_fake_probe(name: str, notify: bool, reason: str = "test reason"):
    mod = types.ModuleType(name)
    mod.default_state = lambda: {}
    mod.gather = lambda cfg: {}
    mod.prepare_state = lambda state, data, now: None
    mod.decide = lambda data, derived, now: Decision(notify, 45, reason)
    mod.build_body = lambda data, derived, decision: "test body"
    sys.modules[name] = mod
    return mod


class TestCliStatus(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()
        for name in list(sys.modules):
            if name.startswith("fake_status_probe_"):
                del sys.modules[name]

    def _write_config(self, probe_name: str) -> Path:
        import json
        config = {
            "name": "test-node",
            "home": str(self.home),
            "probe": probe_name,
            "relay": {"target_tmux_session": "claude"},
        }
        path = self.home / "config.json"
        path.write_text(json.dumps(config))
        return path

    def test_status_reports_probe_decision_without_side_effects(self):
        _install_fake_probe("fake_status_probe_go", notify=True, reason="room available")
        config_path = self._write_config("fake_status_probe_go")

        with patch("shutil.which", return_value=None):  # no claude on PATH in test env
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["status", str(config_path)])

        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("room available", output)
        self.assertIn("would relay:   yes", output)
        # status must never write state.json - it's read-only by design
        self.assertFalse((self.home / "state.json").exists())

    def test_status_survives_gather_failure(self):
        mod = _install_fake_probe("fake_status_probe_err", notify=True)

        def boom(cfg):
            raise RuntimeError("network down")

        mod.gather = boom
        config_path = self._write_config("fake_status_probe_err")

        with patch("shutil.which", return_value=None):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["status", str(config_path)])

        self.assertEqual(rc, 0)
        self.assertIn("gather failed: network down", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
