#!/bin/bash
# Bidirectional sync of a node's scope:global Claude Code memory files
# against a private git repo shared by the whole fleet. See
# docs/memory-sync.md for the full design and the scope:global convention
# this depends on. Standalone and optional - not wired into
# install-node.sh by default, since it needs a repo you already own.
#
# Usage: memory-sync.sh <owner/repo> <memory-dir>
#   <owner/repo>  the shared private repo, e.g. YOUR_ORG/fleet-memory
#   <memory-dir>  this node's own memory directory, e.g.
#                 ~/.claude/projects/-root-<FleetName>/memory
#
# Requires the `gh` CLI authenticated on this node (same prerequisite as
# the gh_backlog probe - see docs/auth.md). Synced path inside the repo is
# always "global-memory/" at the repo root.
set -euo pipefail

REPO="${1:?Usage: memory-sync.sh <owner/repo> <memory-dir>}"
MEMORY_DIR="${2:?Usage: memory-sync.sh <owner/repo> <memory-dir>}"
CLONE_DIR="${FLEETBROKER_MEMORY_SYNC_CLONE:-/root/.cache/fleetbroker-memory-sync}"
REMOTE_DIR="$CLONE_DIR/global-memory"

if [ ! -d "$MEMORY_DIR" ]; then
    echo "memory-sync: $MEMORY_DIR does not exist - nothing to sync" >&2
    exit 1
fi

if [ ! -d "$CLONE_DIR/.git" ]; then
    gh repo clone "$REPO" "$CLONE_DIR" -- -q
fi
git -C "$CLONE_DIR" pull -q --ff-only
mkdir -p "$REMOTE_DIR"

# Push: every local file tagged scope:global -> repo (local wins on
# conflict - accepted tradeoff, see docs/memory-sync.md).
LOCAL_GLOBAL_FILES=$(grep -l '^  scope: global' "$MEMORY_DIR"/*.md 2>/dev/null || true)
for f in $LOCAL_GLOBAL_FILES; do
    cp "$f" "$REMOTE_DIR/$(basename "$f")"
done

# Pull: repo files this node doesn't have at all yet -> adopt them (new
# global knowledge written by another fleet node). A file that exists on
# both sides but differs is left alone here - that's the local-wins rule.
NEW_COUNT=0
for rf in "$REMOTE_DIR"/*.md; do
    [ -e "$rf" ] || continue
    bn="$(basename "$rf")"
    [ "$bn" = "README.md" ] && continue
    if [ ! -f "$MEMORY_DIR/$bn" ]; then
        cp "$rf" "$MEMORY_DIR/$bn"
        echo "memory-sync: pulled new global memory '$bn' - add a MEMORY.md index line for it"
        NEW_COUNT=$((NEW_COUNT + 1))
    fi
done

# Same secret patterns the fleetbroker-adjacent backup convention already
# checks for - refuse to push anything that looks like a live credential.
SECRET_RE='BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[abp]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|Basic [A-Za-z0-9+/]{16,}={0,2}'
if grep -rEIl "$SECRET_RE" "$REMOTE_DIR"; then
    echo "memory-sync: ABORT - possible secret in the file(s) above, nothing committed" >&2
    git -C "$CLONE_DIR" checkout -q -- global-memory
    git -C "$CLONE_DIR" clean -qfd global-memory
    exit 1
fi

git -C "$CLONE_DIR" add global-memory
if git -C "$CLONE_DIR" diff --cached --quiet; then
    echo "memory-sync: no changes"
    exit 0
fi
git -C "$CLONE_DIR" commit -q -m "global-memory sync $(date -u +%FT%TZ)"
git -C "$CLONE_DIR" push -q
echo "memory-sync: pushed ($NEW_COUNT new file(s) adopted this run)"
