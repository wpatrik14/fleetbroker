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

**Fleet (`fleetagents.dev`, source at `derekennyAI/agent-platform`)** - the
closest conceptual neighbor at the deployment-shape level: persistent Claude
Code agents as background daemons (launchd+tmux, bring-your-own
subscription, "run 24/7"). Checked directly against its README and file
layout (not just its marketing page) to be sure: it's a full agent
platform - a Supabase backend with 11 tables, a Node.js MCP admin server, a
per-agent credential vault, OAuth connection flows, Telegram/iMessage/email
channels, a skill validator, and an admin task queue for delegating work
between agents. None of its documented features are about quota or rate
limits - there is no mention of usage caps, fair-share scheduling, or
protecting one instance's interactive use from another's background load
anywhere in it, because it isn't solving that problem. It also brings in
real infrastructure fleetbroker deliberately has none of (a database, a
Node.js service, macOS/launchd as a hard requirement). The overlap really is
just "keep a Claude Code process alive in tmux under your own subscription,"
which is closer to a shared necessity than a shared design - fleetbroker's
own version of that pattern predates any awareness of Fleet, driven by this
project's own dated production incidents (`incidents.md`), not by its code.

**Claude Code's built-in "Agent Teams"** - native multi-instance
coordination for several sessions collaborating on **one task in one repo**
(git-based task claiming). It solves parallelizing a single piece of work,
not coordinating unrelated, independently-scheduled automations across
separate machines and sites over time.

## What's actually unique here

fleetbroker deliberately operates below the agent orchestration layer - it
schedules *whether and when* an existing agent gets safely woken, not what
that agent does once it's awake.

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
