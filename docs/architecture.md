# Architecture: how a fleet actually runs

This ties together pieces documented separately elsewhere - the goal here is
the whole picture, not any one mechanism in isolation.

## Invariant: one quota authority per account

**One Anthropic account MUST have exactly one quota authority** - exactly
one node running a quota-aware probe (`fleetbroker.probes.anthropic_usage`
or any future quota probe) against that account. Every other fleet
participant runs non-quota probes (`gh_backlog`, `gh_repo_watch`, or a
custom one) and is a relay recipient only.

This is not a soft limitation to work around later - it's a hard constraint
on which topologies are valid at all. The daily spending cap tracked by the
quota policy (`docs/README`'s "Current limitation") is per-node state, not
account-wide state; two quota-broker nodes against the same account don't
coordinate with each other, so each independently believes it has the full
daily cap available, and the account's real effective daily cap silently
doubles (or worse, with more nodes) - see the README's "Current limitation"
section. There is currently no mechanism that detects or prevents this
misconfiguration - avoiding it is entirely on whoever wires up a fleet's
node configs.

Fleet-wide quota accounting that would let this constraint be relaxed is a
deliberate v2, not an oversight - see
[issue #4](https://github.com/wpatrik14/fleetbroker/issues/4) for the open
design question.

## A single node, internally

Every node (a Proxmox LXC, a bare VM, any Debian host) runs the same three
independent pieces, wired together by `provision/install-node.sh`:

```mermaid
flowchart TB
    subgraph Node["Fleet node (LXC / VM / bare host)"]
        systemd["claude-tmux.service<br/>(systemd, Type=forking)"]
        tmux["tmux session 'claude'<br/>persistent, full-context<br/>claude rc --name &lt;FleetName&gt;"]
        watchdog["tmux-watchdog.timer<br/>(1 min interval)<br/>checks pane_current_command,<br/>not systemctl status"]
        cron["cron<br/>fleetbroker run &lt;config&gt;<br/>one probe tick"]
        oneshot["one-shot relay<br/>claude -p --strict-mcp-config<br/>--mcp-config '{}'"]
        systemd -->|starts, keeps alive| tmux
        watchdog -->|restarts if pane is dead| systemd
        cron -->|on green light| oneshot
        oneshot -->|SendMessage, local only| tmux
    end
```

The persistent tmux session is the only thing with real conversation
context. Everything else - cron, the one-shot relay - is disposable and
policy-free; it only ever hands a message to the one persistent session and
gets out of the way. See [`docs/incidents.md`](incidents.md) for why each of
these pieces exists (the MCP-spawn-storm crash, the trust-dialog restart
loop, the tmux-server environment race).

## Claude-agnostic core vs. adapter

Everything that depends on undocumented Claude Code CLI internals - the
relay's exact argv, `~/.claude.json`/`.credentials.json` shapes, `claude
auth status`/`--version` output parsing, tmux pane inspection - lives under
`src/fleetbroker/adapters/claude/`:

- `remote_control.py` - the relay (moved from the former top-level
  `relay.py`): argv construction, prompt building, the one-shot invocation.
- `usage.py` - reads `.credentials.json` and calls the OAuth usage endpoint.
- `compat.py` - the verified Claude Code version range (moved from the
  former top-level `compat.py`).
- `status.py` - `claude auth status`/`--version` parsing and tmux session
  health checks, used by `fleetbroker doctor`/`status`.

Everything else - `runner.py`'s scheduling loop, `probes/quota_policy.py`'s
decision logic, `state.py`, `journal.py` - has no idea what "Claude Code" is;
it only knows about probes, decisions, and a `relay()` call it hands a
prompt to. A probe's own dotted config path (e.g.
`fleetbroker.probes.anthropic_usage`) is unaffected by this split and never
changes - only the internal import of *how* that probe gathers data moved.

The payoff: a future Claude Code CLI change (a renamed flag, a different
credentials file shape) is isolated to one file under `adapters/claude/`,
never to the scheduling or policy code. This split has no bearing on
multi-backend support - it's about test isolation and blast radius, not a
plan to add non-Claude backends.

## Cross-node communication

Nodes never talk to each other directly - there is no custom transport in
this project, and none is needed:

```mermaid
flowchart LR
    subgraph SiteA["Site A"]
        A_tmux["tmux 'claude'<br/>(persistent session)"]
    end
    subgraph SiteB["Site B (different network/host)"]
        B_tmux["tmux 'claude'<br/>(persistent session)"]
    end
    You["You<br/>(mobile app / desktop app /<br/>another terminal)"]
    A_tmux <-->|ListAgents / SendMessage<br/>cloud-mediated, outbound-only| Cloud[("Claude Code<br/>Remote Control backend")]
    B_tmux <-->|ListAgents / SendMessage| Cloud
    You <-->|ListAgents / SendMessage| Cloud
```

`ListAgents`/`SendMessage` are a built-in Claude Code capability: each
node's Remote Control session holds an outbound-only connection to
Anthropic's backend, and discovery/messaging is relayed through it - no
shared network, VPN, or port-forwarding required, and it works across
independent sites. See [`docs/addressing.md`](addressing.md) for why a
relay targets a stable **tmux session name**, not the harness-generated
peer name, and [`docs/auth.md`](auth.md) for the one real provisioning
constraint this depends on (a node needs a full interactive login to be
discoverable this way).

This is the same Remote Control mechanism the official Claude Code mobile
and desktop apps use to reach your terminal sessions - so any of those
clients, logged into the same account, can list and message your fleet
nodes directly too. Checking on a node or nudging it from your phone isn't
a fleetbroker feature to build; it falls out of using a standard platform
primitive instead of a custom transport.

## Personas: one identity per node, not one for the whole fleet

Nothing about a node's persona is fleetbroker's concern - it's Claude Code's
own per-instance configuration (`CLAUDE.md`, Skills, MCP servers), which
already differs node to node with zero fleetbroker involvement. What this
project adds is a repeatable way to *seed* that at provisioning time: an
optional `--profile <dir>` seeds a node's `CLAUDE.md`, copies Skills into
`~/.claude/skills/`, and registers MCP servers - see
[`provision/profiles/README.md`](../provision/profiles/README.md). A node
that plays a different role (say, one that only triages a specific set of
repos) can get a different persona and toolset without touching
fleetbroker's own code at all.

## Shared backlog: an external issue tracker as the synchronized state

For multi-site coordination beyond "here's spare quota, do something,"
[`fleetbroker.probes.gh_backlog`](../src/fleetbroker/probes/gh_backlog.py)
turns any Git-forge issue tracker (GitHub Issues is what's implemented;
GitLab/Gitea would follow the same shape) into the one shared,
independently-readable backlog. Labels carry priority/size/reservation, and
an assignee-style label is the claim - see
[`docs/backlog-fairness.md`](backlog-fairness.md) for the fairness algorithm
that stops one site from permanently outpacing another. No new database, no
cross-node sync layer: the issue tracker already is the synchronized store
both sites poll.

## Specialized nodes instead of a swarm orchestrator

Combining the two sections above - per-node personas and a shared backlog -
already gets you most of what a "swarm" of specialized agents would look
like, without adding an orchestrator, a task-decomposition engine, or a
worker-pool abstraction: give each node a different `--profile` (a
frontend-triage node, a security-review node, an infra-monitoring node,
whatever roles you actually need), point all of them at the same
`gh_backlog` repo, and each node's own quota-aware probe picks up backlog
items independently, in its own idle windows. There is no central scheduler
deciding who does what - each node decides for itself whether it has spare
quota and eligible work, exactly as it would running solo.

This is a deliberate non-goal, not a missing feature: routing a specific
backlog item to the node with the right skill currently relies on you
partitioning work sensibly (e.g. via `site:` reservation, or simply not
filing a frontend task in a backlog only infra nodes poll). A `skill:`-style
label for finer-grained routing is a plausible, low-risk future addition to
`gh_backlog` if a real multi-persona fleet needs it - it is not implemented
today because no concrete use case has needed it yet, and it doesn't require
any architectural change when it does.

## Secrets: never fleetbroker's problem to solve, but a pattern that fits

A profile's `mcp.json` never contains a real secret value, only `${VAR}`
placeholders substituted from the installer's environment at install time
(see [`provision/profiles/README.md`](../provision/profiles/README.md)).
Where those environment variables come from is deliberately outside this
project's scope, but a self-hosted secrets manager (a password manager with
a scriptable CLI, or a dedicated secrets store) is a natural fit for
populating them without ever committing a real value anywhere - see
[`docs/secrets-management.md`](secrets-management.md) for the pattern.

## Design philosophy: guardrails for what this project doesn't become

The core abstraction - `gather() -> prepare_state() -> decide() -> build_body()`
feeding a structurally-restricted `relay()` - is a stable interface, not an
implementation detail (see [`docs/writing-a-probe.md`](writing-a-probe.md)).
Quota is its first, flagship resource, not its whole identity; a future probe
guarding a different scarce resource is a natural extension of the same
interface. That said, three things are deliberately *not* on this project's
roadmap, because adding them would blur the one distinction that makes it
useful:

- **No custom messaging or transport.** Claude Code's own
  `ListAgents`/`SendMessage` (Remote Control) already solves cross-instance
  discovery and delivery, including across independent sites - see
  [Cross-node communication](#cross-node-communication) above. Building a
  parallel transport would only be justified by a concrete capability gap in
  that primitive, not by convenience or symmetry with other fleet tools.
- **No task queue, dashboard, or orchestration engine.** Those are what an
  agent orchestration framework provides; fleetbroker sits *below* that
  layer (see [`docs/related-work.md`](related-work.md)) and only answers one
  question - is it currently safe to wake an existing agent - not what that
  agent should do next.
- **No feature added to look more complete.** The guiding question for any
  new capability is: does it make running several persistent Claude Code
  instances against a shared resource *more reliably safe*, not merely more
  capable? A failure mode caught and regression-tested (see
  [`docs/chaos-testing.md`](chaos-testing.md)) is worth more to this project
  than a new integration.

If a proposed change starts needing its own task model, agent registry, or
chat layer to make sense, that's a signal to stop and ask why an existing
agent orchestration project isn't a better fit for that need, rather than
growing this one to cover it.
