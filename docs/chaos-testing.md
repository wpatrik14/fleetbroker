# Chaos/resilience testing

This project's actual value isn't "works on the happy path" - every entry
in [`incidents.md`](incidents.md) is about what happens when part of the
agent infrastructure dies. This doc splits that claim into what's now an
automated regression test, and what can only be a documented manual
procedure.

## Automated (`tests/test_resilience.py`)

Uses real subprocesses, real sockets, and real tmux sessions - not mocks -
specifically because a mocked exception only proves the exception-handling
code exists, not that the real failure is actually caught the same way.

- **A real process killed by `SIGKILL` mid-relay** - `subprocess.run` never
  raises for this (it returns a negative returncode), and the runner still
  reaches `save_state()`. Direct regression test for incident #5.
- **A real hanging subprocess exceeding its timeout** - not a mocked
  `TimeoutExpired`, an actual `sleep` past a 1-second configured timeout.
- **`state.json`'s atomic write survives a crash mid-replace** - patches
  `os.replace` to fail after the tmp file is written, confirms the real
  `state.json` still holds the last good value, never a half-written one.
- **A real connection-refused network error** during `gather()` (a genuine
  socket error against a closed local port, not a mocked `RuntimeError`) is
  caught by the runner's guarded gather exactly like any other failure.
- **`provision/tmux-watchdog.sh` against a real, disposable tmux session**
  (never the live `claude` session) via `FLEETBROKER_WATCHDOG_SESSION`:
  detects a missing session, detects a session whose pane is running
  something other than `claude` (the exact "systemctl lies" scenario from
  incident #4), and stays silent when the session and pane are genuinely
  healthy.

## Manual only (can't be a fast, hermetic unit test)

### Watchdog restart recovery, end to end

The automated tests above verify the watchdog's *detection* logic. The full
loop - detection -> `systemctl restart claude-tmux.service` -> the restarted
session coming up clean without re-tripping the trust-dialog or
Remote-Control first-run hangs (incidents #2, #6) - needs a real systemd
unit and a real `claude` login, so it has to be exercised on a real node:

```bash
tmux kill-session -t claude
# within tmux-watchdog.timer's 1-minute interval:
systemctl status claude-tmux.service   # should show a recent restart
tmux list-panes -t claude -F '#{pane_current_command}'   # should print "claude"
```

### Full host reboot recovery

Verified manually once, for real, while fixing incident #6: provision a
node, confirm it's healthy, then `pct reboot` (or a real host reboot) it and
confirm `claude-tmux.service` and `tmux-watchdog.timer` both come back
without any manual intervention - no repeated trust-dialog or
Remote-Control first-run hang. Repeat this after any change to
`install-node.sh`'s pre-seed step or the systemd unit templates; it's the
strongest available regression test for that entire class of first-run-hang
bug.

### CLI-version-dependent behavior

See [`compatibility.md`](compatibility.md) - `scripts/smoke-test.sh` is the
manual, opt-in check for real CLI behavior (auth, version, tmux, `doctor`,
`status`, a dry-run relay) after a Claude Code CLI upgrade.
