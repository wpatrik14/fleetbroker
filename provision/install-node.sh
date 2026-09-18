#!/bin/bash
# Standalone installer: turns a fresh Debian host/container into a fleetbroker
# node. Works on any Debian box (Proxmox LXC or otherwise) - it does not
# assume it's running under Proxmox. Run as root, inside the target machine.
#
# Usage: install-node.sh <FleetName> [--profile <profile-dir>]
#   <FleetName> is the Remote Control identity (claude rc --name ...); it is
#   NOT the tmux session name, which is always "claude" by convention (see
#   docs/addressing.md) so the relay's allow-list target stays constant
#   across every fleet member.
#   --profile <profile-dir> optionally seeds this node's persona (CLAUDE.md),
#   Skills, and MCP-server roster from a profiles/<name>/ directory - see
#   provision/profiles/README.md. Secrets referenced as ${VAR} inside a
#   profile's mcp.json are read from THIS shell's environment, never from
#   the profile file itself.
set -euo pipefail

FLEET_NAME=""
PROFILE_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile) PROFILE_DIR="${2:?--profile needs a directory}"; shift 2 ;;
        *) FLEET_NAME="$1"; shift ;;
    esac
done
: "${FLEET_NAME:?Usage: install-node.sh <FleetName> [--profile <profile-dir>]}"
WORKDIR="/root/${FLEET_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GN='\033[1;92m'; YW='\033[33m'; RD='\033[01;31m'; CL='\033[m'
msg_info()  { echo -e " ${YW}i${CL} $1"; }
msg_ok()    { echo -e " ${GN}\xe2\x9c\x93${CL} $1"; }
msg_error() { echo -e " ${RD}x${CL} $1"; }

if [[ -n "$PROFILE_DIR" && ! -d "$PROFILE_DIR" ]]; then
    msg_error "Profile directory not found: $PROFILE_DIR"
    exit 1
fi

msg_info "Installing dependencies"
apt-get update -qq
apt-get install -y -qq curl git tmux python3 python3-venv ca-certificates >/dev/null
msg_ok "Installed dependencies"

if ! command -v node >/dev/null 2>&1; then
    msg_info "Installing Node.js 22"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
    apt-get install -y -qq nodejs >/dev/null
    msg_ok "Installed Node.js 22"
else
    msg_ok "Node.js already present ($(node --version))"
fi

if ! command -v claude >/dev/null 2>&1; then
    msg_info "Installing Claude Code CLI"
    npm install -g @anthropic-ai/claude-code >/dev/null 2>&1
    msg_ok "Installed Claude Code CLI"
else
    msg_ok "Claude Code CLI already present"
fi

mkdir -p "$WORKDIR"
msg_ok "Working directory: $WORKDIR (never /root itself - see docs/incidents.md #2)"

msg_info "Pre-seeding workspace trust for $WORKDIR"
python3 - "$WORKDIR" <<'PYEOF'
import json
import pathlib
import sys

workdir = sys.argv[1]
path = pathlib.Path.home() / ".claude.json"
data = json.loads(path.read_text()) if path.exists() else {}
data.setdefault("projects", {})
data["projects"].setdefault(workdir, {})
data["projects"][workdir]["hasTrustDialogAccepted"] = True
data["remoteDialogSeen"] = True
path.write_text(json.dumps(data, indent=2))
PYEOF
msg_ok "Trust pre-seeded (prevents the trust-dialog restart loop, docs/incidents.md #2)"
msg_ok "Remote Control first-run prompt pre-seeded (docs/incidents.md #6)"

echo
echo "=== Manual step required: interactive login ==="
echo "A node that must be discoverable via ListAgents cannot be provisioned"
echo "headlessly - Remote Control requires a full-scope login token, and"
echo "'claude setup-token' / CLAUDE_CODE_OAUTH_TOKEN are inference-only and"
echo "will be refused (see docs/auth.md). This works fine over this SSH"
echo "session - no browser or port-forward needed on this box itself."
echo
echo "Run in another shell on this same machine, or right here:"
echo "    claude auth login"
echo
read -rp "Press Enter once 'claude auth login' has completed successfully..."

if ! claude auth status >/dev/null 2>&1; then
    msg_error "claude auth status failed - login did not complete. Aborting."
    exit 1
fi
msg_ok "claude auth status verified"

msg_info "Installing claude-tmux.service"
sed "s|__WORKDIR__|$WORKDIR|g; s|__FLEET_NAME__|$FLEET_NAME|g" \
    "$SCRIPT_DIR/claude-tmux.service.tmpl" > /etc/systemd/system/claude-tmux.service
systemctl daemon-reload
systemctl enable -q --now claude-tmux.service
msg_ok "claude-tmux.service enabled and started (tmux session 'claude')"

msg_info "Installing tmux watchdog"
install -m 755 "$SCRIPT_DIR/tmux-watchdog.sh" /usr/local/bin/tmux-watchdog.sh
install -m 644 "$SCRIPT_DIR/tmux-watchdog.service" /etc/systemd/system/tmux-watchdog.service
install -m 644 "$SCRIPT_DIR/tmux-watchdog.timer" /etc/systemd/system/tmux-watchdog.timer
systemctl daemon-reload
systemctl enable -q --now tmux-watchdog.timer
msg_ok "tmux-watchdog.timer enabled (1-min interval, checks pane state not systemctl status)"

msg_info "Installing fleetbroker"
FLEETBROKER_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
python3 -m venv /opt/fleetbroker/.venv
/opt/fleetbroker/.venv/bin/pip install -q -e "$FLEETBROKER_SRC"
msg_ok "fleetbroker installed at /opt/fleetbroker/.venv"

if [[ -n "$PROFILE_DIR" ]]; then
    msg_info "Applying profile: $PROFILE_DIR"

    if [[ -f "$PROFILE_DIR/CLAUDE.md" ]]; then
        mkdir -p ~/.claude
        cp "$PROFILE_DIR/CLAUDE.md" ~/.claude/CLAUDE.md
        msg_ok "Persona installed: ~/.claude/CLAUDE.md"
    fi

    if [[ -d "$PROFILE_DIR/skills" ]]; then
        mkdir -p ~/.claude/skills
        cp -r "$PROFILE_DIR/skills/." ~/.claude/skills/
        msg_ok "Skills installed: ~/.claude/skills/"
    fi

    if [[ -f "$PROFILE_DIR/mcp.json" ]]; then
        msg_info "Registering MCP servers from profile"
        python3 - "$PROFILE_DIR/mcp.json" <<'PYEOF'
import json
import os
import re
import subprocess
import sys

path = sys.argv[1]
entries = json.loads(open(path).read())


def substitute(value):
    if isinstance(value, dict):
        return {k: substitute(v) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v) for v in value]
    if isinstance(value, str):
        def repl(m):
            var = m.group(1)
            if var not in os.environ:
                raise SystemExit(
                    f"mcp.json references ${{{var}}} but it is not set in the "
                    "environment - export it before running install-node.sh"
                )
            return os.environ[var]
        return re.sub(r"\$\{(\w+)\}", repl, value)
    return value


for entry in entries:
    name = entry["name"]
    scope = entry.get("scope", "user")
    server_json = json.dumps(substitute(entry["json"]))
    result = subprocess.run(
        ["claude", "mcp", "add-json", name, server_json, "--scope", scope],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  x failed to add MCP server '{name}': {result.stderr.strip()}", file=sys.stderr)
    else:
        print(f"  registered MCP server '{name}' (scope={scope})")
PYEOF
        msg_ok "MCP servers registered from profile"
    fi

    msg_ok "Profile applied"
fi

echo
echo "=== Node ready: '$FLEET_NAME' ==="
echo "Next steps:"
echo "  1. Copy an example config from examples/ into a probe home dir, edit placeholders"
echo "  2. /opt/fleetbroker/.venv/bin/fleetbroker doctor <config.json>"
echo "  3. Add the matching line from examples/crontab.example to root's crontab"
echo "  4. From another fleet node: ListAgents should now list '$FLEET_NAME'"
