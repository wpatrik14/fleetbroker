# fleetbroker

[![tests](https://github.com/wpatrik14/fleetbroker/actions/workflows/tests.yml/badge.svg)](https://github.com/wpatrik14/fleetbroker/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Safely share one Anthropic account's Claude Code usage quota across multiple
independent, cooperating Claude Code instances — without starving your own
interactive use, and without crashing shared infrastructure.

**Why this exists.** Running more than one Claude Code agent under the same
subscription is increasingly normal — a home-lab node, a side project, a
second site you help maintain. Nothing in Claude Code itself stops those
instances from fighting over one rate limit, and a naive scheduler can crash
the box they run on. fleetbroker is the small, boring layer in between: a
pure decision function that knows when there's room, and a relay mechanism
that's structurally incapable of repeating the failures that motivated it —
see [`docs/incidents.md`](docs/incidents.md) for the real production
incidents this project fixes, not hypothetical ones.

## The problem

If you run more than one Claude Code instance under the same account (multiple
containers/VMs, a home-lab node plus a side-project node, whatever your setup
looks like), they all draw from the same rate-limited quota. Nothing stops one
instance's background automation from burning through your budget while you're
in the middle of interactive work — and naively scheduling background agent
invocations (e.g. via a cloud-triggered routine) can spawn a full MCP-server
roster on every fire and take down the host container. Both of these happened
in production before this project existed; see [`docs/incidents.md`](docs/incidents.md).

## What this is

A small, cron-driven daemon pattern:

1. A cheap, non-Claude **probe** (e.g. reading your account's usage straight
   from Anthropic's own usage endpoint, using the same OAuth token the
   `claude` CLI already has) runs every tick and decides, via a pure policy
   function, whether there's spare quota right now.
2. On a green light, it fires a **one-shot, MCP-free Claude invocation**
   (`claude -p --strict-mcp-config --mcp-config '{"mcpServers":{}}'`) — cheap,
   fast, and structurally unable to spawn the MCP roster that crashed a
   container in this project's own history.
3. That one-shot process does **not** contact anything itself. Its only job is
   to relay a message, via the already-authenticated `ListAgents`/`SendMessage`
   tools, to exactly one allow-listed peer: the persistent, full-context
   session running in a specific, stable tmux session (by convention, named
   `claude`). That peer — which has the full conversation context a throwaway
   one-shot never will — decides what, if anything, to do next.

Cross-instance discovery and messaging is **not** something this project
builds — `ListAgents`/`SendMessage` already work across independent hosts,
even on different networks/sites, as a built-in Claude Code capability. This
project only supplies the safe scheduling, policy, and narrow-relay pattern on
top of it.

## Quickstart

```bash
python3 -m venv /opt/fleetbroker/.venv
/opt/fleetbroker/.venv/bin/pip install -e .
cp examples/quota-broker-direct.json /root/.fleetbroker-quota/config.json  # edit placeholders
/opt/fleetbroker/.venv/bin/fleetbroker doctor /root/.fleetbroker-quota/config.json
/opt/fleetbroker/.venv/bin/fleetbroker run /root/.fleetbroker-quota/config.json --dry-run
```

Then wire it into cron — see [`examples/crontab.example`](examples/crontab.example).
`quota-broker-direct.json` needs nothing but a logged-in `claude` CLI (see
[`docs/direct-api.md`](docs/direct-api.md)); `quota-broker.json` is the
Home-Assistant-sourced alternative, for anyone who already has that set up.

## Standing up a new fleet participant

See [`provision/`](provision) for `create-ct.sh` (Proxmox LXC) and
`install-node.sh` (standalone, works on any Debian host). **Read
[`docs/auth.md`](docs/auth.md) first** — a node that needs to be discoverable
via `ListAgents` cannot be provisioned fully non-interactively; there is a
real, unavoidable ~60-second manual login step, and the docs explain exactly
why and how to make it the *only* manual step.

Optionally give the node its own persona, Skills, and MCP-server roster with
`--profile <dir>` (`install-node.sh`) or a profile name (`create-ct.sh`) —
see [`provision/profiles/README.md`](provision/profiles/README.md). This is
a thin layer over Claude Code's own per-instance config, not a fleetbroker
concept; secrets referenced in a profile are never stored in the profile
file itself, only substituted from the installer's environment.

## Writing your own probe

The quota policy is the flagship, shipped as two probes sharing the exact
same `decide()`/`prepare_state()`/`build_body()` — only the data source
differs: `fleetbroker.probes.anthropic_usage` (recommended, no extra
dependency, see [`docs/direct-api.md`](docs/direct-api.md)) and
`fleetbroker.probes.ha_quota` (Home-Assistant-sourced). The probe interface
itself is generic — see [`docs/writing-a-probe.md`](docs/writing-a-probe.md)
and the simpler `fleetbroker.probes.gh_repo_watch` reference implementation
(no policy engine at all, just a watermark comparison).

For multi-site setups, `fleetbroker.probes.gh_backlog` turns a GitHub Issues
repo into a shared backlog with priority/size labels and a fairness check
(so one site can't keep claiming work while a peer's queue sits idle) — see
[`docs/backlog-fairness.md`](docs/backlog-fairness.md).

## Documentation

| Goal | Start here |
| --- | --- |
| See the whole picture (deployment, cross-node comms, personas, backlog, secrets) | [`docs/architecture.md`](docs/architecture.md) |
| Understand why each safety mechanism exists | [`docs/incidents.md`](docs/incidents.md) |
| Drop the Home Assistant dependency | [`docs/direct-api.md`](docs/direct-api.md) |
| Provision a new node's login correctly | [`docs/auth.md`](docs/auth.md) |
| Understand relay addressing (tmux vs. peer name) | [`docs/addressing.md`](docs/addressing.md) |
| Write a new probe | [`docs/writing-a-probe.md`](docs/writing-a-probe.md) |
| Share a backlog fairly across sites | [`docs/backlog-fairness.md`](docs/backlog-fairness.md) |
| Source node secrets without committing them | [`docs/secrets-management.md`](docs/secrets-management.md) |

## Current limitation

The daily spending cap in the quota probe is **per broker node, not
per-account**. Running two quota-broker nodes against the same account
silently doubles the effective daily cap. v1's supported topology is exactly
one quota-broker node per Anthropic account; every other fleet participant
runs non-quota probes and is a relay recipient only. Fleet-wide quota
accounting is a natural v2, not silently glossed over here.

## Support

If this saved you from repeating the incidents in
[`docs/incidents.md`](docs/incidents.md) the hard way:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-FFDD00?style=flat-square&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/wpatrik14e)

## License

MIT
