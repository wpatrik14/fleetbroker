# Incident history behind this project's design decisions

Every non-obvious flag, guard, or convention in this codebase traces back to
something that actually broke in production. This page exists so a future
contributor doesn't "simplify" one of these back into the bug it fixes.

## 1. The MCP-server-spawn-storm container crash

**What happened**: an early design scheduled a cloud-triggered routine that,
on every fire, started a genuinely new, additional Claude Code session inside
the host container — each spinning up its own full MCP-server roster (~6 node
processes: various integration servers). The container already ran several
concurrent sessions steady-state. Firing the routine 3 times within about 24
minutes added a 4th full stack each time on top of that; the container hung
hard enough to need a forced reboot.

**Fix**: the one-shot relay invocation uses
`claude -p --strict-mcp-config --mcp-config '{"mcpServers":{}}'`. This
combination starts a genuinely MCP-free one-shot session — core tools like
`ListAgents`/`SendMessage` still work (they aren't MCP-based), but the entire
"spin up a full integration roster" path is skipped. This is why
`fleetbroker.adapters.claude.remote_control` owns this argv construction and does not expose it for
probes to override.

**Gotcha to remember**: `--mcp-config` is variadic and will swallow a
following bare prompt argument unless separated with `--`, and its JSON value
must be shaped `{"mcpServers": {...}}`, not just `{}`.

## 2. The trust-dialog restart loop

**What happened**: after a host reboot, a Claude Code node's working directory
was missing from `~/.claude.json`'s `projects` trust list (only its parent
directory had been trusted). `claude rc` exited immediately with
`Error: Workspace not trusted...` — with no way to answer the interactive
trust prompt in a non-interactive systemd unit — which killed the pane, which
killed the tmux server (nothing else was keeping it alive), which meant the
watchdog restarted the service every minute, forever, hitting the exact same
failure each time.

**Fix**: the provisioning installer pre-seeds
`~/.claude.json` → `projects["/root/<FleetName>"].hasTrustDialogAccepted = true`
for the exact working directory the node will run in, *before* the first
`claude rc` invocation. This is why the installer insists on a dedicated
working directory per node and explicitly refuses to run the node out of
`/root` itself — home-directory trust cannot be made to persist that way.

## 3. The tmux-server global-environment boot race

**What happened**: on a multi-backend node (running more than one AI CLI
backend concurrently, each in its own tmux session), whichever systemd service
won the race to start the shared tmux *server* process at boot determined the
server's global environment — inherited by every pane, not just the one that
set it. One backend's `EnvironmentFile` set `ANTHROPIC_BASE_URL` to point at a
different API; when that service won the boot race by a few milliseconds, the
`claude` pane inherited that override and `claude rc` refused to start
("Remote Control is only available when using Claude via api.anthropic.com").

**Fix**: the node's tmux launch command explicitly `unset`s every
`ANTHROPIC_*` override before `exec`-ing `claude rc`, rather than relying on
not having set them in the first place. A single-backend node doesn't strictly
need this today, but the installer template carries it because adding a
second backend later is an easy, easy-to-regress addition.

## 4. "systemctl status lies"

**Recurring pattern, not a single incident**: `systemctl status` on the
tmux-hosting service can report `active (exited)` — technically true, since
`Type=forking`/`RemainAfterExit=yes` units report exit status, not whether the
thing inside the tmux pane is actually alive — while the pane itself is dead.
Anything that needs to know "is the node actually working" must check
`tmux has-session` **and** `tmux list-panes -F '#{pane_current_command}'`
for the expected process name, never just the systemd unit's own reported
state. This is why `fleetbroker doctor` and the watchdog template both check
the pane command directly.

## 5. A relay timeout silently defeating its own cooldown

**What happened, caught during this project's own extraction/refactor** (not
yet observed live, but directly reachable from the original code): the
original relay call had no timeout handling — a `TimeoutExpired` would
propagate straight out of `main()`, skipping the final `save_state()` call.
That meant `last_notify_epoch` was never written, so the cooldown never
engaged, so the *next* tick would spawn another one-shot relay against a
`claude` binary that might still be hung for the same reason — one new
stuck process per tick, indefinitely. This is the same failure shape as
incident #1, just reachable via a hang instead of a spawn storm.

**Fix**: `fleetbroker.adapters.claude.remote_control.relay()` catches `TimeoutExpired`/
`FileNotFoundError`/`OSError` itself and returns a plain success flag; it
never raises. The runner always reaches `save_state()` regardless of relay
outcome.

## 6. The silent "Enable Remote Control?" hang on a fresh node

**What happened**: on a brand-new node's very first `claude rc` launch, the
CLI asks a one-time interactive confirmation ("Enable Remote Control?
(y/n)") before the session actually starts serving. Started under a
non-interactive systemd unit inside a detached tmux pane, nothing ever
answers it - the pane sits there indefinitely, `claude rc` never reaches the
"Connected" state, and the node never becomes visible via `ListAgents`. This
is the exact same failure shape as incident #2 (a first-run interactive
prompt with no one to answer it) but for a different dialog, discovered only
once by provisioning a genuinely fresh node end to end - it can't be hit by
any workflow that reuses an already-answered account.

**Fix**: the same pre-seed step that answers the workspace trust dialog also
sets `remoteDialogSeen: true` in `~/.claude.json` before the first `claude
rc` invocation. Verified to survive a full `systemctl restart` of the
service, so the watchdog's restart-recovery path does not regress into this
hang either.

## 7. `claude-tmux.service` silently failing after switching to the native CLI installer

**What happened**: `install-node.sh` switched from a global npm install of
the Claude Code CLI to the native `curl | bash` installer, which places the
binary under `~/.local/bin` instead of a directory already on systemd's
default `PATH`. `claude-tmux.service`'s `ExecStart` ran `exec claude rc ...`
with no `claude` on `PATH` - the shell inside the freshly-created tmux pane
failed with "command not found" and exited, which killed the pane and, since
it was the session's only window, the whole `claude` tmux session with it.
`systemctl status` still reported `active (exited)` as a clean, expected
exit (`Type=forking`/`RemainAfterExit=yes` again cannot tell the difference -
see incident #4) - only `fleetbroker doctor`'s explicit `tmux has-session`
check caught it. Found by provisioning a real node end to end on a fresh
Proxmox host, not by inspection.

**Fix**: `install-node.sh` resolves the actual install directory
(`dirname "$(command -v claude)"`) once, right after installing the CLI, and
bakes it into an explicit `Environment=PATH=...` line in
`claude-tmux.service` - the same resolved directory is also reused for the
crontab's `PATH=` line (see [`auth.md`](auth.md) for that half of the same
class of bug). Neither the systemd unit nor cron may assume `claude` is
reachable through some ambient shell-only PATH.
