import io
import json
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


class TestFleetStatus(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()
        for name in list(sys.modules):
            if name.startswith("fake_fleet_probe_"):
                del sys.modules[name]

    def _write_node_config(self, node_dir: str, probe_name: str) -> Path:
        home = self.root / node_dir
        home.mkdir()
        config = {
            "name": node_dir,
            "home": str(home),
            "probe": probe_name,
            "relay": {},
        }
        path = home / "config.json"
        path.write_text(json.dumps(config))
        return path

    def _write_fleet_config(self, nodes: list[dict]) -> Path:
        path = self.root / "fleet.json"
        path.write_text(json.dumps({"nodes": nodes}))
        return path

    def test_reports_each_node_without_side_effects(self):
        _install_fake_probe("fake_fleet_probe_a", notify=True, reason="room available")
        _install_fake_probe("fake_fleet_probe_b", notify=False, reason="no room")
        config_a = self._write_node_config("node-a", "fake_fleet_probe_a")
        config_b = self._write_node_config("node-b", "fake_fleet_probe_b")
        fleet_config = self._write_fleet_config([
            {"name": "node-a", "config": str(config_a)},
            {"name": "node-b", "config": str(config_b)},
        ])

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["fleet-status", str(fleet_config)])

        output = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("node-a", output)
        self.assertIn("room available", output)
        self.assertIn("would relay:   yes", output)
        self.assertIn("node-b", output)
        self.assertIn("no room", output)
        self.assertIn("would relay:   no", output)
        self.assertIn("last relay:    never", output)
        # fleet-status is read-only, same guarantee as `fleetbroker status`.
        self.assertFalse((self.root / "node-a" / "state.json").exists())
        self.assertFalse((self.root / "node-b" / "state.json").exists())

    def test_survives_one_node_gather_failure_without_aborting_the_rest(self):
        mod = _install_fake_probe("fake_fleet_probe_broken", notify=True)
        mod.gather = lambda cfg: (_ for _ in ()).throw(RuntimeError("network down"))
        _install_fake_probe("fake_fleet_probe_ok", notify=True, reason="fine")
        config_broken = self._write_node_config("node-broken", "fake_fleet_probe_broken")
        config_ok = self._write_node_config("node-ok", "fake_fleet_probe_ok")
        fleet_config = self._write_fleet_config([
            {"name": "node-broken", "config": str(config_broken)},
            {"name": "node-ok", "config": str(config_ok)},
        ])

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["fleet-status", str(fleet_config)])

        output = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("gather failed: network down", output)
        self.assertIn("node-ok", output)
        self.assertIn("fine", output)

    def test_missing_node_config_file_does_not_abort_the_rest(self):
        _install_fake_probe("fake_fleet_probe_ok2", notify=False, reason="fine")
        config_ok = self._write_node_config("node-ok2", "fake_fleet_probe_ok2")
        fleet_config = self._write_fleet_config([
            {"name": "node-missing", "config": str(self.root / "does-not-exist.json")},
            {"name": "node-ok2", "config": str(config_ok)},
        ])

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["fleet-status", str(fleet_config)])

        output = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("node-missing", output)
        self.assertIn("failed to load config", output)
        self.assertIn("node-ok2", output)

    def test_empty_fleet_config_reports_failure(self):
        fleet_config = self._write_fleet_config([])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["fleet-status", str(fleet_config)])
        self.assertEqual(rc, 1)
        self.assertIn("No nodes configured", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
