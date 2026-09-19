# A real deployment, end to end

The rest of the docs describe the mechanism in the abstract. This page grounds
it in one concrete node: the actual config shape, crontab line, and what
`fleetbroker status` prints for a healthy quota-broker node in production use.
Names, hostnames, and peer identifiers below are placeholders - the shape and
field values are real.

## The config

`/root/.fleetbroker-quota/config.json` on the quota-broker node:

```json
{
  "name": "quota-broker",
  "home": "/root/.fleetbroker-quota",
  "probe": "fleetbroker.probes.anthropic_usage",
  "cooldown_seconds": 7200,
  "relay": {
    "target_tmux_session": "claude",
    "forbidden_tmux_sessions": ["other-cli-a", "other-cli-b"],
    "forbidden_peer_names": ["some-other-fleet-node"],
    "prompt_locale": "en",
    "timeout_seconds": 180
  },
  "probe_config": {
    "credentials_path": "/root/.claude/.credentials.json"
  }
}
```

A few things worth calling out that aren't obvious from `writing-a-probe.md`
alone:

- `forbidden_tmux_sessions` exists because this host runs other long-lived
  CLI tools in their own tmux sessions - the relay must never accidentally
  wake one of *those* instead of the intended Claude Code session.
- `forbidden_peer_names` is the same guard at the `ListAgents` layer: even if
  a peer with that Remote Control name is reachable, the relay refuses to
  target it. See [`addressing.md`](addressing.md) for why both a tmux-level
  and a peer-name-level guard exist rather than just one.
- `cooldown_seconds: 7200` means a GREEN LIGHT that already fired won't fire
  again for two hours even if the probe keeps finding room, so the receiving
  session isn't re-notified every single hourly tick.

## The crontab line

```
0 * * * * /opt/fleetbroker/.venv/bin/fleetbroker run /root/.fleetbroker-quota/config.json >> /root/.fleetbroker-quota/log.txt 2>&1
```

Straight from [`examples/crontab.example`](../examples/crontab.example) - runs
the probe once an hour, on the hour, appending to its own log. See
[`auth.md`](auth.md)'s cron-PATH section before assuming a `doctor` pass
means the cron invocation will also find `claude`.

## What `fleetbroker status` prints for a healthy node

```
$ fleetbroker status /root/.fleetbroker-quota/config.json
NODE  (quota-broker)
  claude auth:   user@example.com (org: user@example.com's Organization, plan: pro)
  tmux 'claude':   ONLINE (pane: ['claude'])

PROBE  (fleetbroker.probes.anthropic_usage)
  decision:      room available: session 4.0%, week 68.0% (pace=-15.4), no urgent reset
  would relay:   yes

RECENT LOG
  2026-09-19T04:10:02.374732+00:00 GREEN LIGHT: room available: session 0.0%, week 68.0% (pace=-15.4), no urgent reset (window=45min) - notifying
  2026-09-19T04:10:20.747349+00:00 notify_home rc=0 stdout='Message sent to the target peer, flagged as untrusted-source. It decides the next step.' stderr=''
```

This is read-only - it re-evaluates the probe's decision function against
current state but never spends quota or fires a relay, so it's safe to run
any time you want to sanity-check a node without waiting for the next cron
tick.

## Not included here: a recorded terminal demo

A short asciinema/GIF capture of the ALLOW path (probe fires, decision =
ALLOW, relay wakes the target session) and the DENY path (same setup, low
headroom, nothing happens) would make this more legible than prose - tracked
separately since it needs a live two-node take rather than being something to
improvise from one node's log.
