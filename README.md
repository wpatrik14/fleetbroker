# fleetbroker

[![tests](https://github.com/wpatrik14/fleetbroker/actions/workflows/tests.yml/badge.svg)](https://github.com/wpatrik14/fleetbroker/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Run a fleet of persistent Claude Code agents against one Anthropic account —
without letting background automation starve your interactive use or take
down the host.

fleetbroker is a small, quota-aware coordination and relay layer around
Claude Code. It does not replace Claude Code, provide another agent runtime,
or orchestrate your agents' work — it makes running multiple independent
instances against shared resources safer.

```text
                         Anthropic account
                                │
                         shared usage quota
                                │
                   ┌────────────┴────────────┐
                   │        fleetbroker       │
                   │   (runs locally per node) │
                   │   probe → policy → relay  │
                   └────────┬──────────┬───────┘
                            │          │
                    ┌───────▼──┐   ┌───▼───────┐
                    │  Node A  │   │  Node B   │
                    │  Claude  │   │  Claude   │
                    │  Code    │   │  Code     │
                    └───────┬──┘   └───┬───────┘
                            │          │
                            └────┬─────┘
                                 │
                     Claude Code Remote Control
                     (ListAgents / SendMessage)
```

fleetbroker schedules and safely wakes agents; Claude Code remains the agent
runtime and the cross-instance communication layer.

## Why fleetbroker?

```text
I have several persistent Claude Code agents.
They share one Anthropic account.
I want them to cooperate.
I don't want background automation to consume my interactive quota.
And I definitely don't want another agent invocation to take down the host.

fleetbroker is the small, boring layer that makes that safe.
```

Running more than one Claude Code agent under the same subscription is
increasingly normal — a home-lab node, a side project, a second site you
help maintain. Nothing in Claude Code itself stops those instances from
fighting over one rate limit, and a naive scheduler can crash the box they
run on. Both of these happened in production before this project existed —
see [`docs/incidents.md`](docs/incidents.md) for the real incidents this
project fixes, not hypothetical ones. This is a narrower problem than most
adjacent projects solve — see [`docs/related-work.md`](docs/related-work.md)
for how it compares to team-quota tools, multi-account rotation, and full
agent platforms.

> [!WARNING]
> v1 supports exactly **one quota-broker node per Anthropic account**.
> Fleet-wide quota accounting is not yet distributed — see
> [Limitations](#limitations).

## What fleetbroker does

1. A cheap, non-Claude **probe** (e.g. reading your account's usage straight
   from Anthropic's own usage endpoint, using the same OAuth token the
   `claude` CLI already has) runs every tick and decides, via a pure policy
   function, whether there's spare quota right now.
2. On a green light, it fires a **one-shot, MCP-free Claude invocation**
   (`claude -p --strict-mcp-config --mcp-config '{"mcpServers":{}}'`) — cheap,
   fast, and explicitly isolated from the MCP roster that crashed a
   container in this project's own history.
3. That one-shot process does **not** contact anything itself. Its only job is
   to relay a message, via the already-authenticated `ListAgents`/`SendMessage`
   tools, to exactly one allow-listed peer: the persistent, full-context
   session running in a specific, stable tmux session (by convention, named
   `claude`). That peer — which has the full conversation context a throwaway
   one-shot never will — decides what, if anything, to do next.

Cross-instance discovery and messaging is **not** something this project
builds — `ListAgents`/`SendMessage` already work across independent hosts,
even on different networks/sites, as a built-in Claude Code capability, and
it's the same mechanism the official mobile and desktop apps use to reach
your terminal sessions. This project only supplies the safe scheduling,
policy, and narrow-relay pattern on top of it — see
[`docs/architecture.md`](docs/architecture.md) for the whole picture.

## What fleetbroker is not

fleetbroker is not:

- an agent framework
- an agent swarm
- a Claude Code replacement
- a multi-account quota rotator
- a central task orchestrator
- an MCP server manager

Claude Code remains responsible for the agent, its tools, context, and
cross-instance messaging. fleetbroker only decides when and how background
work is allowed to wake an existing agent.

## Why it matters

```text
Without fleetbroker:

  cron
   └─ claude
       ├─ MCP servers
       ├─ tools
       ├─ context
       └─ potentially another full agent process

With fleetbroker:

  cron
   └─ cheap probe
        └─ quota available?
             └─ yes → MCP-free relay
                      └─ existing persistent Claude session
```

## Quickstart

```bash
curl -fsSL https://raw.githubusercontent.com/wpatrik14/fleetbroker/master/install.sh | bash
```

This installs the `fleetbroker` package (a venv under `/opt/fleetbroker`,
zero runtime dependencies) and puts a `fleetbroker` command on your PATH.
Then:

```bash
cp examples/quota-broker.json /root/.fleetbroker-quota/config.json  # edit placeholders
fleetbroker doctor /root/.fleetbroker-quota/config.json
fleetbroker run /root/.fleetbroker-quota/config.json --dry-run
```

Once it's running, `fleetbroker status <config>` shows the current decision,
whether it would relay right now, and the last few log lines — read-only,
spends nothing, never touches `state.json`.

Then wire it into cron — see [`examples/crontab.example`](examples/crontab.example).
`quota-broker.json` needs nothing but a logged-in `claude` CLI. Prefer to
install by hand instead? `install.sh` is just `python3 -m venv` + `pip
install -e .` — read it, it's short.

## Provisioning a new fleet node

Starting from a bare Proxmox host with no containers yet? See
[`docs/getting-started.md`](docs/getting-started.md) for the full
step-by-step walkthrough.

See [`provision/`](provision) for `create-ct.sh` (Proxmox LXC) and
`install-node.sh` (standalone, works on any Debian host). **Read
[`docs/auth.md`](docs/auth.md) first** — a node that needs to be discoverable
via `ListAgents` cannot be provisioned fully non-interactively; there is a
real, unavoidable ~60-second manual login step, and the docs explain exactly
why and how to make it the *only* manual step. `install-node.sh` writes a
working default quota-broker config, wires up cron, and self-checks with
`fleetbroker doctor` automatically — there's nothing to edit unless you want
to customize it.

Optionally give the node its own persona, Skills, and MCP-server roster with
`--profile <dir>` (`install-node.sh`) or a profile name (`create-ct.sh`) —
see [`provision/profiles/README.md`](provision/profiles/README.md). This is
a thin layer over Claude Code's own per-instance config, not a fleetbroker
concept; secrets referenced in a profile are never stored in the profile
file itself, only substituted from the installer's environment.

## Custom probes

The quota policy (`fleetbroker.probes.quota_policy`) is the flagship, and
ships with one data source — `fleetbroker.probes.anthropic_usage`, which
reads straight from Anthropic's own OAuth usage endpoint using the
already-authenticated `claude` CLI's own credentials, no extra dependency
to stand up. The probe interface itself is generic — see
[`docs/writing-a-probe.md`](docs/writing-a-probe.md) and the simpler
`fleetbroker.probes.gh_repo_watch` reference implementation (no policy
engine at all, just a watermark comparison).

For multi-site setups, `fleetbroker.probes.gh_backlog` turns a GitHub Issues
repo into a shared backlog with priority/size labels and a fairness check
(so one site can't keep claiming work while a peer's queue sits idle) — see
[`docs/backlog-fairness.md`](docs/backlog-fairness.md).

## Documentation

| Goal | Start here |
| --- | --- |
| Stand up the first node from a bare Proxmox host | [`docs/getting-started.md`](docs/getting-started.md) |
| See the whole picture (deployment, cross-node comms, personas, backlog, secrets) | [`docs/architecture.md`](docs/architecture.md) |
| See how this compares to similar-looking projects | [`docs/related-work.md`](docs/related-work.md) |
| Understand why each safety mechanism exists | [`docs/incidents.md`](docs/incidents.md) |
| See what's tested against real failures vs. manual-only | [`docs/chaos-testing.md`](docs/chaos-testing.md) |
| Check Claude CLI version compatibility, run a smoke test | [`docs/compatibility.md`](docs/compatibility.md) |
| Provision a new node's login correctly | [`docs/auth.md`](docs/auth.md) |
| Understand relay addressing (tmux vs. peer name) | [`docs/addressing.md`](docs/addressing.md) |
| Write a new probe | [`docs/writing-a-probe.md`](docs/writing-a-probe.md) |
| Share a backlog fairly across sites | [`docs/backlog-fairness.md`](docs/backlog-fairness.md) |
| Source node secrets without committing them | [`docs/secrets-management.md`](docs/secrets-management.md) |

## Limitations

The daily spending cap in the quota probe is **per broker node, not
per-account**. Running two quota-broker nodes against the same account
silently doubles the effective daily cap. v1's supported topology is exactly
one quota-broker node per Anthropic account; every other fleet participant
runs non-quota probes and is a relay recipient only. Fleet-wide quota
accounting is a natural v2, not silently glossed over here. This is a hard
architectural invariant, not a soft gap — see
[`docs/architecture.md`](docs/architecture.md#invariant-one-quota-authority-per-account).

## Status

This is an early-stage, opinionated tool built around Claude Code's current
CLI and Remote Control behavior. Expect the integration surface to evolve as
Claude Code evolves — see [`docs/compatibility.md`](docs/compatibility.md)
for the verified CLI version range.

## License

MIT
