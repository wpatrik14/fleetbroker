#!/bin/bash
# Watchdog for the persistent 'claude' tmux session. Checks the actual pane
# process, not `systemctl is-active` - a forking/RemainAfterExit unit reports
# "active (exited)" even when the pane inside it has died, so that check
# alone is not trustworthy. See docs/incidents.md #4.
set -u

if tmux has-session -t claude 2>/dev/null; then
    if tmux list-panes -t claude -F '#{pane_current_command}' 2>/dev/null | grep -q '^claude$'; then
        exit 0
    fi
fi

echo "tmux-watchdog: 'claude' session missing or dead -> restarting claude-tmux.service"
if [ -n "${WATCHDOG_DRYRUN:-}" ]; then
    echo "tmux-watchdog: DRYRUN - not restarting"
    exit 0
fi
systemctl restart claude-tmux.service
