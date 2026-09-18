#!/bin/bash
# Manual smoke test against a REAL, already-provisioned fleetbroker node.
# NOT run in CI - it needs a live logged-in `claude` CLI and a live tmux
# 'claude' session (see docs/getting-started.md), which a CI runner
# deliberately does not have. Run this by hand after provisioning a new
# node, or after a Claude Code CLI upgrade, to catch a CLI-behavior
# regression before it silently breaks in production.
#
# Deliberately does NOT fire a real ListAgents/SendMessage relay - that
# would either spend quota for real or send an unexpected message to a
# real peer, which a "test" script should never do blindly. `fleetbroker
# run --dry-run` already exercises the prompt-building path (including the
# ListAgents/SendMessage instructions themselves) without actually calling
# out, and that's as far as this script goes.
#
# Usage: scripts/smoke-test.sh [config.json]
set -uo pipefail

CONFIG="${1:-}"
FLEETBROKER_BIN="${FLEETBROKER_BIN:-/opt/fleetbroker/.venv/bin/fleetbroker}"
PASS=0
FAIL=0

check() {
    local label="$1"; shift
    local out
    if out="$("$@" 2>&1)"; then
        echo "[OK] $label"
        PASS=$((PASS + 1))
    else
        echo "[FAIL] $label"
        echo "$out" | sed 's/^/    /'
        FAIL=$((FAIL + 1))
    fi
}

echo "=== fleetbroker smoke test ==="
echo "claude version: $(claude --version 2>&1)"
echo

check "claude on PATH" bash -c "command -v claude"
check "claude auth status" claude auth status
check "claude --version reports a parseable version" bash -c "claude --version | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+'"

TARGET="${FLEETBROKER_SMOKE_TARGET_SESSION:-claude}"
check "tmux session '$TARGET' exists" tmux has-session -t "$TARGET"
check "tmux session '$TARGET' has a live claude pane" bash -c \
    "tmux list-panes -t '$TARGET' -F '#{pane_current_command}' | grep -qx claude"

if [[ -n "$CONFIG" ]]; then
    check "fleetbroker doctor" "$FLEETBROKER_BIN" doctor "$CONFIG"
    check "fleetbroker status" "$FLEETBROKER_BIN" status "$CONFIG"
    check "fleetbroker run --dry-run" "$FLEETBROKER_BIN" run "$CONFIG" --dry-run
else
    echo "(no config given - skipping fleetbroker doctor/status/run checks)"
fi

echo
echo "=== $PASS passed, $FAIL failed ==="
[[ "$FAIL" -eq 0 ]]
