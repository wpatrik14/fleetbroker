# Related work, and where fleetbroker actually differs

"Multiple Claude Code instances" is a crowded enough topic that it's worth
being explicit about what already exists and why it doesn't cover this
project's problem, rather than letting the README imply this space is empty.

## The problem fleetbroker solves, precisely

Several **already-cooperating, already-independent** Claude Code instances
(different hosts, different purposes, no shared task) draw from **one**
Anthropic account's rate limit. Nothing stops one instance's background
automation from starving interactive use or another instance's automation,
and naively scheduling background invocations can crash the host that runs
them (see [`incidents.md`](incidents.md)). fleetbroker's whole job is: decide
per-instance whether there's spare room right now, and if so, hand a message
to the one persistent session that can act on it - safely, with no new
infrastructure.

That is a narrower problem than most adjacent projects solve, and the
narrowness is deliberate.

## Alternatives, and why they're solving something else

**`howincodes/claude-code-limiter`** - per-user quotas, credit budgets, and a
kill switch for a **team of humans** sharing one subscription, enforced by a
client-side hook talking to a self-hosted server with its own database and
dashboard. This solves *access control between people*, not *scheduling
between automations*. It also requires standing up and operating a separate
server/DB/dashboard stack - fleetbroker adds no new service at all.

**Multi-account rotation tools** (e.g. `israads/claude-multisession`,
`KarpelesLab/teamclaude`) - spread load across **several** Anthropic
accounts/subscriptions and rotate or proxy between them when one hits a
limit. This sidesteps a single account's rate limit rather than sharing it
fairly; fleetbroker assumes exactly one account and never tries to get
around its limit, only to divide the room inside it fairly.

**Fleet (`fleetagents.dev`)** - the closest conceptual neighbor: persistent
Claude Code agents as background daemons (launchd+tmux, bring-your-own
subscription, "run 24/7"), which is the same deployment shape fleetbroker
nodes use. But it's a full agent platform (per-agent credential vault,
scheduled tasks, multi-channel comms, macOS/launchd-specific) built around
*running* agents, not around the specific failure mode of **several such
agents silently exhausting one shared rate limit** - it has no fair-share
policy or quota-aware scheduling layer as far as its public documentation
shows, and no equivalent to the crash-safe one-shot relay this project's own
incident history forced into existence.

**Claude Code's built-in "Agent Teams"** - native multi-instance
coordination for several sessions collaborating on **one task in one repo**
(git-based task claiming). It solves parallelizing a single piece of work,
not coordinating unrelated, independently-scheduled automations across
separate machines and sites over time.

## What's actually unique here

- **The specific failure mode.** Fair quota-sharing *within a single
  Anthropic account* across independent, already-running automations,
  including a documented, crash-tested scheduling layer - not team billing
  control, not cross-account rotation, not single-task parallelism.
- **Zero new infrastructure.** No proxy, no database, no dashboard service.
  A cron tick, a pure decision function, and the platform's own
  `ListAgents`/`SendMessage` (already free and already cross-site) are the
  entire mechanism.
- **The relay is provably safe, not just assumed safe.** The one-shot
  relay's exact flag set (`--strict-mcp-config`, empty `mcpServers`) exists
  because an earlier design without it hard-crashed a production container -
  see [`incidents.md`](incidents.md) for that and six other real incidents
  this design is built to never repeat.
- **Works across independent sites with no shared network.** Two nodes on
  physically separate networks coordinate through Anthropic's own Remote
  Control backend - no VPN, no port-forwarding, nothing to operate.

If your problem is team access control, cross-account rotation, or
parallelizing one task, one of the projects above is a better fit than this
one. If your problem is "I run more than one Claude Code automation under
one account and they're stepping on each other," that's what this project
is for.
