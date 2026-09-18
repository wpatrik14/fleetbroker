"""Resilience tests using REAL subprocesses/sockets/files where practical,
not mocks - the point of this project is that it doesn't fall over when
part of the agent infrastructure actually dies (see docs/incidents.md).
A mocked exception proves the exception-handling code path exists; these
tests prove the real failure mode is caught the same way.

What's NOT covered here because it can't be a fast, hermetic unit test:
- tmux session kill + systemd watchdog restart across a real reboot
  (verified manually for incident #6 - see docs/chaos-testing.md for the
  documented, repeatable procedure).
- A full host reboot recovery test (same doc).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fleetbroker import runner, state
from fleetbroker.adapters.claude import remote_control as relay
from fleetbroker.adapters.claude import usage as claude_usage
from fleetbroker.probes import anthropic_usage


class TestRelaySurvivesRealProcessFailures(unittest.TestCase):
    """relay.relay() must never raise, and the runner must always reach
    save_state(), regardless of how the underlying `claude` process dies -
    this is a direct regression test for incident #5 (a timeout that used
    to skip save_state() entirely, defeating the cooldown)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_relay_survives_a_real_process_killed_by_signal(self):
        # A real subprocess that kills itself with SIGKILL - subprocess.run
        # does not raise for this, it just returns a negative returncode.
        # Confirms relay() doesn't assume a clean exit and still logs and
        # returns normally. The trailing prompt text relay.relay() appends
        # is passed as an unused extra argv element to `python -c` - harmless.
        fake_argv = [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"]
        with patch.object(relay, "RELAY_ARGV_PREFIX", fake_argv):
            ok = relay.relay(self.home, {"target_tmux_session": "claude"}, "x")
        self.assertIn(ok, (True, False))
        log = (self.home / "log.txt").read_text()
        self.assertIn("notify_home rc=", log)

    def test_relay_timeout_with_a_real_hanging_subprocess(self):
        # A real subprocess that sleeps well past the configured timeout -
        # not a mocked TimeoutExpired. Confirms subprocess.run's real
        # timeout path is caught and relay() returns False without raising.
        fake_argv = [sys.executable, "-c", "import time; time.sleep(5)"]
        with patch.object(relay, "RELAY_ARGV_PREFIX", fake_argv):
            ok = relay.relay(self.home, {"target_tmux_session": "claude", "timeout_seconds": 1}, "x")
        self.assertFalse(ok)
        log = (self.home / "log.txt").read_text()
        self.assertIn("notify_home failed to run", log)

    def test_runner_reaches_save_state_even_when_relay_process_is_killed(self):
        import sys as _sys
        import types

        mod_name = "fake_resilience_probe"
        mod = types.ModuleType(mod_name)
        mod.default_state = lambda: {"marker": "untouched"}
        mod.gather = lambda cfg: {}
        mod.prepare_state = lambda st, data, now: None
        from fleetbroker.probe import Decision
        mod.decide = lambda data, derived, now: Decision(True, 45, "test reason")
        mod.build_body = lambda data, derived, decision: "test body"
        _sys.modules[mod_name] = mod
        try:
            fake_argv = [_sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"]
            with patch.object(relay, "RELAY_ARGV_PREFIX", fake_argv):
                config = {
                    "home": str(self.home),
                    "probe": mod_name,
                    "relay": {"target_tmux_session": "claude"},
                }
                runner.run(config)
            # state.json must exist and be valid JSON - proves save_state()
            # was reached despite the relay subprocess dying by signal.
            saved = json.loads((self.home / "state.json").read_text())
            self.assertIn("last_notify_epoch", saved)
        finally:
            del _sys.modules[mod_name]


class TestStateAtomicity(unittest.TestCase):
    """state.save_state() writes to a tmp file then os.replace()s it -
    confirms a crash between those two steps never corrupts the real
    state.json (the file left behind is either the old value or the new
    one, never a half-written one)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_original_state_survives_a_crash_during_replace(self):
        state.save_state(self.home, {"value": "original"})

        with patch("fleetbroker.state.os.replace", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                state.save_state(self.home, {"value": "new"})

        # The real state.json must still be exactly the last successfully
        # committed value - not truncated, not partially written.
        recovered = json.loads((self.home / "state.json").read_text())
        self.assertEqual(recovered, {"value": "original"})

    def test_tmp_file_never_left_readable_as_the_real_state_after_a_crash(self):
        with patch("fleetbroker.state.os.replace", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                state.save_state(self.home, {"value": "new"})
        self.assertFalse((self.home / "state.json").exists())
        self.assertTrue((self.home / "state.json.tmp").exists())


class TestRealNetworkFailureHandling(unittest.TestCase):
    """anthropic_usage.gather() hitting a real closed port (not a mocked
    exception) must still be caught cleanly by the runner's guarded gather,
    exactly like any other probe failure."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self._tmpdir.name)
        creds_dir = self.home / "creds"
        creds_dir.mkdir()
        self.creds_path = creds_dir / ".credentials.json"
        self.creds_path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "fake-token"}}))

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_real_connection_refused_is_caught_not_raised(self):
        # Port 1 is a real, guaranteed-closed low port - a real
        # ConnectionRefusedError/URLError, not a mock. Patched on the
        # adapter module, where the constant is actually read from at call
        # time - anthropic_usage.gather() just delegates to it.
        with patch.object(claude_usage, "USAGE_API_URL", "http://127.0.0.1:1/"):
            with self.assertRaises((urllib.error.URLError, ConnectionRefusedError, OSError)):
                anthropic_usage.gather({"credentials_path": str(self.creds_path)})

    def test_runner_survives_the_same_real_failure(self):
        import sys as _sys
        _sys.modules["fleetbroker.probes.anthropic_usage"] = anthropic_usage
        with patch.object(claude_usage, "USAGE_API_URL", "http://127.0.0.1:1/"):
            config = {
                "home": str(self.home),
                "probe": "fleetbroker.probes.anthropic_usage",
                "probe_config": {"credentials_path": str(self.creds_path)},
                "relay": {"target_tmux_session": "claude"},
            }
            runner.run(config)  # must not raise
        log = (self.home / "log.txt").read_text()
        self.assertIn("ERROR gathering data:", log)


class TestWatchdogWithRealTmux(unittest.TestCase):
    """Runs the actual provision/tmux-watchdog.sh against a real, disposable
    tmux session (never the live 'claude' session this test suite might
    itself be running under) via FLEETBROKER_WATCHDOG_SESSION."""

    WATCHDOG = str(Path(__file__).resolve().parent.parent / "provision" / "tmux-watchdog.sh")

    @classmethod
    def setUpClass(cls):
        if shutil.which("tmux") is None:
            raise unittest.SkipTest("tmux not available")

    def setUp(self):
        # Unique per test method, not just per process - os.getpid() alone
        # is constant across the whole (in-process) test run, which meant
        # every test in this class raced over the exact same session name
        # right after the previous test's tearDown killed it (observed
        # flaking in CI, not reproduced locally - a kill-then-recreate race
        # under this specific name, not a real watchdog bug).
        self.session = f"fleetbroker-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._fakebin_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        subprocess.run(["tmux", "kill-session", "-t", self.session], capture_output=True)
        self._fakebin_dir.cleanup()

    def _make_fake_claude_binary(self) -> Path:
        # A symlink named "claude" pointing at the real `sleep` binary,
        # invoked by absolute path. Linux sets a process's comm (what
        # tmux's pane_current_command reads) from the exact name passed to
        # execve() for a real ELF binary, regardless of symlink target -
        # this is well-defined and version-independent. A `#!/bin/bash`
        # shebang script named "claude" was tried first and rejected: comm
        # assignment for shebang scripts goes through binfmt_script and a
        # shell's "exec last command" optimization, and empirically gave
        # inconsistent results (passed in isolation, failed as part of the
        # full suite, failed in CI) - not reliable enough to depend on.
        fake_claude = Path(self._fakebin_dir.name) / "claude"
        fake_claude.symlink_to(shutil.which("sleep"))
        return fake_claude

    def _run_watchdog(self, dry_run: bool) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["FLEETBROKER_WATCHDOG_SESSION"] = self.session
        if dry_run:
            env["WATCHDOG_DRYRUN"] = "1"
        return subprocess.run(["bash", self.WATCHDOG], capture_output=True, text=True, env=env, timeout=10)

    def test_healthy_session_with_live_claude_pane_passes_silently(self):
        fake_claude = self._make_fake_claude_binary()
        subprocess.run(["tmux", "new-session", "-d", "-s", self.session, str(fake_claude), "100"], check=True)
        result = self._run_watchdog(dry_run=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_missing_session_is_detected_and_dry_run_does_not_restart(self):
        # Session was never created - the watchdog must detect this as
        # "missing," not crash on a nonexistent tmux target.
        result = self._run_watchdog(dry_run=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(f"'{self.session}' session missing or dead", result.stdout)
        self.assertIn("DRYRUN - not restarting", result.stdout)

    def test_dead_pane_in_existing_session_is_detected(self):
        # A session exists, but its pane is running something other than
        # `claude` (e.g. a fallen-back shell after `claude` itself exited) -
        # this is the exact "systemctl lies" scenario from incident #4:
        # the session/service can look alive while the real work is dead.
        subprocess.run(["tmux", "new-session", "-d", "-s", self.session, "sleep", "100"], check=True)
        result = self._run_watchdog(dry_run=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("session missing or dead", result.stdout)


if __name__ == "__main__":
    unittest.main()
