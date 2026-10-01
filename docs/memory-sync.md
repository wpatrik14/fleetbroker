# Optional: syncing memory across the fleet

Claude Code's auto-memory system (`~/.claude/projects/<slug>/memory/`) is
per-node by design - fleetbroker deliberately has no shared filesystem (see
[`docs/architecture.md`](architecture.md)), so two nodes never automatically
learn the same thing. For a single-user fleet that's often wrong: a fact
about *you* - your role, a standing preference, a fleet-wide project
decision - is worth having on every node, not just the one that happened to
learn it first.

`provision/memory-sync.sh` is a small, optional, git-based answer to that -
not a fleetbroker probe (it doesn't touch the probe/policy/relay pipeline
at all), just another standalone cron script in the same spirit as
`tmux-watchdog.sh`.

## The scope:global convention

Tag a memory file as fleet-wide by adding `scope: global` to its
`metadata:` frontmatter block, next to the existing `type:` field:

```yaml
---
name: example-memory
description: "..."
metadata:
  type: feedback
  scope: global
---
```

Untagged files are local by default - safe, and zero effort for the common
case of host/project-specific memory nobody else needs. Reach for
`scope: global` for memories about the user (role, standing preferences,
feedback) and for decisions that affect the whole fleet (shared backlog
conventions, cross-node policy) - not for anything tied to one node's own
infra or project.

## How the sync works

```
memory-sync.sh <owner/repo> <memory-dir>
```

Each run:

1. `git pull --ff-only` a private repo you already own (a dedicated one, or
   reuse whatever repo already backs up this node's Claude config).
2. Copies every local `scope: global` file into that repo's `global-memory/`
   directory, overwriting the repo's copy - **local wins on conflict**. If
   two nodes edit the same file's global content in the same sync window,
   whichever syncs last overwrites the other. Memory edits are infrequent
   enough in practice that this hasn't been worth building real merge logic
   for; a future version could add one if that stops being true.
3. Adopts any file present in the repo's `global-memory/` but missing from
   this node's own memory directory entirely - i.e. new knowledge another
   node wrote. The receiving node still needs a `MEMORY.md` index line for
   anything adopted this way; the script only drops the file in and says so.
4. Commits and pushes if anything changed, after a secret-pattern scan over
   everything about to be committed (same idea as
   [`docs/secrets-management.md`](secrets-management.md) - this script
   aborts rather than push a file that looks like it contains a live
   credential).

## Setup

Requires the `gh` CLI authenticated on the node (same prerequisite as the
`gh_backlog` probe - see [`docs/auth.md`](auth.md)) and a private repo you
control.

```bash
chmod +x provision/memory-sync.sh
./provision/memory-sync.sh YOUR_ORG/YOUR_MEMORY_REPO \
    ~/.claude/projects/-root-<FleetName>/memory
```

Then add it to cron on each node that should participate (every node's
crontab points at the same repo):

```cron
15 */6 * * * /path/to/fleetbroker/provision/memory-sync.sh YOUR_ORG/YOUR_MEMORY_REPO ~/.claude/projects/-root-<FleetName>/memory >> /root/.cache/fleetbroker-memory-sync.log 2>&1
```

Not wired into `install-node.sh` - unlike the quota-broker cron entry,
this needs a repo only you can provide, so it stays a manual, opt-in step
per node rather than a default every fresh install gets.
