#!/bin/bash
# Watchdog for the persistent 'claude' tmux session. Checks the actual pane
# process, not `systemctl is-active` - a forking/RemainAfterExit unit reports
# "active (exited)" even when the pane inside it has died, so that check
# alone is not trustworthy. See docs/incidents.md #4.
set -u

# Overridable only for tests (test_resilience.py) - every real deployment
# uses the fixed "claude" session name by convention (docs/addressing.md).
SESSION="${FLEETBROKER_WATCHDOG_SESSION:-claude}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    if tmux list-panes -t "$SESSION" -F '#{pane_current_command}' 2>/dev/null | grep -q '^claude$'; then
        exit 0
    fi
fi

echo "tmux-watchdog: '$SESSION' session missing or dead -> restarting claude-tmux.service"
if [ -n "${WATCHDOG_DRYRUN:-}" ]; then
    echo "tmux-watchdog: DRYRUN - not restarting"
    exit 0
fi
systemctl restart claude-tmux.service
