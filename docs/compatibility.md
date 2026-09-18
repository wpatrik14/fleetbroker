# Claude Code CLI compatibility

fleetbroker depends on several Claude Code CLI internals that are not a
documented, stable contract: `ListAgents`/`SendMessage` behavior, Remote
Control session semantics, `claude rc` flags, the `~/.claude.json`
structure (this project directly mutates
`projects["..."].hasTrustDialogAccepted` and `remoteDialogSeen` - see
[`incidents.md`](incidents.md) #2 and #6), and the `.credentials.json`
layout (`anthropic_usage.py`). A future CLI change to any of these could
break fleetbroker with no warning - this doc is about making that
distinguishable from an actual fleetbroker bug.

## Verified version range

Tracked in `fleetbroker.compat`: versions `>= 2.1.0, < 3.0.0` are the range
this project has actually been run against (including the live provisioning
run documented in `docs/getting-started.md`). This is a floor of evidence,
not a ceiling of support - a version outside this range is simply
*untested*, not necessarily broken.

`fleetbroker doctor` checks this automatically and prints `[WARN]` (never
`[FAIL]`) for a version outside the verified range - it doesn't block
`doctor`'s overall pass/fail, because an untested version might work fine.

## Manual smoke test

Unit tests cover the pure policy/state/relay-argv layer, but can't verify
real Claude CLI behavior (`ListAgents`, `SendMessage`, `claude rc`, the live
usage endpoint) without a real logged-in CLI and a live tmux session -
exactly the kind of environment CI deliberately doesn't have.
[`scripts/smoke-test.sh`](../scripts/smoke-test.sh) is a manual, opt-in
script for that: run it by hand after provisioning a new node, or after
upgrading the Claude Code CLI, to catch a real regression before it
surfaces silently in production.

```bash
scripts/smoke-test.sh /root/.fleetbroker-quota/config.json
```

It deliberately never fires a real `ListAgents`/`SendMessage` relay -
`fleetbroker run --dry-run` already exercises the prompt-building path
without spending anything or messaging a real peer, and that's as far as
an automated "test" should go.

## When a version mismatch is suspected

1. Run `fleetbroker doctor <config>` - a `[WARN]` on the version line is
   the first signal.
2. Run `scripts/smoke-test.sh <config>` for a fuller picture.
3. If something's actually broken, check `docs/incidents.md` first - it's
   entirely plausible a new CLI version reintroduces a previously-fixed
   failure mode (e.g. a changed first-run prompt reproducing incident #6).
