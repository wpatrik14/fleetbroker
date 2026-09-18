#!/usr/bin/env bash
# One-command install of the fleetbroker package itself (the `fleetbroker`
# CLI: run/doctor/explain). This is NOT full node provisioning - for turning
# a fresh host into a fleet participant (systemd, tmux, watchdog, claude CLI
# login), see provision/install-node.sh instead.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/wpatrik14/fleetbroker/master/install.sh | bash
#   (or, from an already-cloned checkout:)  ./install.sh
set -euo pipefail

REPO_URL="https://github.com/wpatrik14/fleetbroker.git"
INSTALL_DIR="${FLEETBROKER_DIR:-/opt/fleetbroker}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 is required (>=3.10) and was not found on PATH" >&2
    exit 1
fi

if [ -f "$(dirname "$0")/pyproject.toml" ]; then
    # Running from inside an already-cloned checkout - install in place.
    SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
else
    # Bootstrapped via curl|bash with no local checkout - fetch one.
    if ! command -v git >/dev/null 2>&1; then
        echo "error: git is required to fetch fleetbroker" >&2
        exit 1
    fi
    SRC_DIR="$INSTALL_DIR/src"
    if [ -d "$SRC_DIR/.git" ]; then
        git -C "$SRC_DIR" pull --ff-only
    else
        mkdir -p "$INSTALL_DIR"
        git clone --depth 1 "$REPO_URL" "$SRC_DIR"
    fi
fi

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -e "$SRC_DIR"

BIN_LINK="/usr/local/bin/fleetbroker"
if [ -w "$(dirname "$BIN_LINK")" ] 2>/dev/null; then
    ln -sf "$INSTALL_DIR/.venv/bin/fleetbroker" "$BIN_LINK"
    echo "fleetbroker installed - the 'fleetbroker' command is now on PATH."
else
    echo "fleetbroker installed at $INSTALL_DIR/.venv/bin/fleetbroker"
    echo "(could not symlink into /usr/local/bin - add it to PATH yourself, or run it by full path)"
fi

echo
echo "Next steps:"
echo "  cp $SRC_DIR/examples/quota-broker.json /root/.fleetbroker-quota/config.json  # edit placeholders"
echo "  fleetbroker doctor /root/.fleetbroker-quota/config.json"
echo "  fleetbroker run /root/.fleetbroker-quota/config.json --dry-run"
