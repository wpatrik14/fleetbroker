# Getting started on a fresh Proxmox host

This walks through the very first node, starting from a bare Proxmox VE host
with no containers yet - just root SSH access to the host itself.

## 1. Get the source onto the Proxmox host

`create-ct.sh` runs *on the Proxmox host* (it calls `pct create`) and pushes
this repo's tree into the container it creates, so the repo needs to exist on
the host first:

```bash
ssh root@your-proxmox-host
git clone https://github.com/wpatrik14/fleetbroker.git
```

## 2. Create the container

```bash
cd fleetbroker
chmod +x provision/*.sh
./provision/create-ct.sh 120 192.168.1.199/24 MyFirstFleetNode
```

- `120` is the LXC VMID - pick one not already in use (`pct list` shows what's
  taken).
- `192.168.1.199/24` is the container's static IP/CIDR; `GATEWAY` defaults to
  the `.1` of that subnet, override by exporting `GATEWAY` first if needed.
- `MyFirstFleetNode` is this node's Remote Control identity - it's what shows
  up in `ListAgents` from other fleet nodes, not a hostname or tmux session
  name (those are separate, see [`addressing.md`](addressing.md)).

This downloads a Debian 13 template if needed, creates and starts an
unprivileged LXC, and pushes the whole fleetbroker source tree into it at
`/opt/fleetbroker-src`. It does **not** install anything inside the
container yet - that's `install-node.sh`, run next.

## 3. Enter the container and run the installer

```bash
pct enter 120
/opt/fleetbroker-src/provision/install-node.sh MyFirstFleetNode
```

This installs the Claude Code CLI (native installer, no Node.js needed),
pre-seeds the workspace-trust and Remote-Control first-run prompts (see
[`incidents.md`](incidents.md) #2 and #6 for why those exist), and then
stops with:

```
=== Manual step required: interactive login ===
Run in another shell on this same machine, or right here:
    claude auth login

Press Enter once 'claude auth login' has completed successfully...
```

This is the one genuinely unavoidable manual step - see
[`auth.md`](auth.md) for why a node discoverable via `ListAgents` cannot be
provisioned headlessly.

## 4. Log in, in a second window

The script above is now blocked waiting for Enter, so run the login in a
**second** connection to the same container. `tmux` is already installed at
this point, so the easiest way is a second window in the same session
instead of a second SSH hop:

```bash
# from the Proxmox host, in a new terminal:
pct exec 120 -- tmux new-window -t <session> 'claude auth login; bash'
```

(or just open a second `pct enter 120` shell and run `claude auth login`
directly - anything that gives you a second prompt inside the container
works.)

`claude auth login` in a container with no browser prints a URL instead of
opening one:

```
Opening browser to sign in…
If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?...
Paste code here if prompted >
```

Open that URL on any machine with a browser, approve it, and you'll land on
a page showing a code. Paste that code back at the `Paste code here if
prompted >` line and press Enter.

**Two gotchas seen in practice:**
- If the URL wraps across multiple terminal lines, copy it carefully - a
  stray or missing character in the middle (easy to introduce when
  re-typing a wrapped line by hand) fails with `Redirect URI ... is not
  supported by client`, which looks like a server-side problem but isn't.
  If you're capturing the URL via `tmux capture-pane`, add `-J` to join
  wrapped lines automatically instead of doing it by hand.
- If `claude auth login` fails or is cancelled, the tmux window running it
  closes immediately (the command exited) - that's why the command above
  ends in `; bash`, so you get a live shell back to retry instead of a dead
  window.

Once `claude auth login` reports success, go back to the **first** window
and press Enter. The script verifies with `claude auth status` and, from
here on, finishes with **zero further input**: it installs
`claude-tmux.service` (the persistent session), the tmux watchdog, the
`fleetbroker` package, writes a working default quota-broker config, wires
up cron, and self-checks with `fleetbroker doctor`.

## 5. Verify

From any other machine already running Claude Code with Remote Control
enabled:

```
ListAgents
```

`MyFirstFleetNode` should now be listed. That's the whole setup - the
default config needs no editing to start working (see
[`architecture.md`](architecture.md) for what's now running and why).

From inside the node itself, `fleetbroker status /root/.fleetbroker-quota/config.json`
gives a read-only snapshot - current auth, tmux session health, the probe's
current decision, and the last few log lines - without spending anything.

See [`example-deployment.md`](example-deployment.md) for what a healthy
node's config, crontab line, and `status` output actually look like in
production use.

## What's next

- A second node, at a different site, gives the fairness/backlog features
  something to coordinate across - see [`backlog-fairness.md`](backlog-fairness.md).
- Give this node its own persona/Skills/MCP roster instead of the defaults -
  see [`provision/profiles/README.md`](../provision/profiles/README.md).
- Customize the quota policy or add a second probe (e.g. the `gh_repo_watch`
  example) - see [`writing-a-probe.md`](writing-a-probe.md) and
  [`examples/crontab.example`](../examples/crontab.example).
