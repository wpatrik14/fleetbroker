# Authentication reality for fleet nodes

## The short version

A node that needs to be **discoverable via `ListAgents`** (i.e. anything other
than a purely local, invisible worker) cannot be provisioned non-interactively.
There is no flag, environment variable, or config key that changes this as of
this writing.

## Why

`claude rc` (Remote Control) explicitly requires a full-scope login token.
Long-lived tokens from `claude setup-token` or the `CLAUDE_CODE_OAUTH_TOKEN`
environment variable are deliberately limited to inference-only use and are
refused by Remote Control for security reasons. Only an interactive
`claude auth login` produces a token with the scope Remote Control needs.

## Why this is fine in practice

The login is small: one `claude auth login` command, one URL opened on any
device (your laptop, your phone - it does not need to be opened on the node
itself), one code pasted back. It works over a plain SSH session with no
browser, X server, or port-forward required on the node. `provision/install-node.sh`
pauses for exactly this step and verifies it with `claude auth status` before
continuing, so it's a single deliberate checkpoint, not something scattered
across the install.

## What NOT to do

- **Do not copy `~/.claude/.credentials.json` between hosts.** It carries a
  rotating refresh token, and the CLI has account-mismatch reconciliation
  logic that assumes one set of credentials belongs to one identity. Treat
  each node's login as its own.
- **Do not run fleet nodes in Docker** if they need Remote Control visibility.
  `createCodeSession` has been observed returning 401 from containerized
  environments (likely attestation-related). LXC (or a bare VM) is the
  supported target.

## A related gotcha: cron's PATH is not your shell's PATH

`fleetbroker doctor` checks for `claude` using whatever PATH the shell you
ran it from has - normally your full interactive PATH. cron invocations use
a minimal PATH (`/usr/bin:/bin` or similar) that will not include `claude`
if it was installed anywhere else - the native/curl installer puts it under
`~/.local/bin`, distinct from a global npm install landing in `/usr/bin` or
similar. A node can pass `doctor` cleanly and still fail every actual relay
with "claude: command not found" from cron. Set `PATH=` explicitly at the
top of the crontab (see `examples/crontab.example`) to whatever directory
`which claude` reports interactively, don't assume `doctor` passing proves
the cron invocation will also find it.

## Open question, not yet settled

Whether a **relay-only** node - one that only needs to run probes and relay
into its *own* local tmux session, without ever needing to be visible from
outside that host - can use the lighter-weight `CLAUDE_CODE_OAUTH_TOKEN` path
is unverified. If local peer discovery turns out not to depend on the Remote
Control account bridge, this could become a genuinely headless "worker tier."
Don't rely on this until someone has actually confirmed it; treat every node
as needing the full interactive login until proven otherwise.
