# Liveness heartbeat (Uptime Kuma push monitor)

## What problem this solves

Every other safety mechanism in this project assumes the node's cron/systemd
timer is actually firing. If it isn't - a crashed container, a broken
crontab entry after a re-provision, a host that silently stopped booting -
the only way to notice today is to go check a specific node's `log.txt` by
hand. That doesn't scale past a couple of nodes, and it means the *first*
sign of a dead node is usually "why hasn't this site claimed anything from
the backlog in three weeks."

An optional `heartbeat` block turns this into a normal monitored service: on
every completed `fleetbroker run` tick, the node pushes a liveness ping to an
external push-style monitor. Point it at an existing
[Uptime Kuma](https://github.com/louislam/uptime-kuma) instance (or anything
else that speaks the same "GET this URL on a schedule or alert" push
contract) and a silent node shows up on the same dashboard as every other
monitored service, instead of requiring a per-node log check.

## Setting up the monitor side

In Uptime Kuma: **Add New Monitor** → Monitor Type **Push** → set the
**Heartbeat Interval** to somewhat more than this node's cron period (e.g. 20
minutes for a 15-minute cron, to tolerate one missed/late tick without
false-alarming), and a **Retries** count of at least 1 so a single slow tick
doesn't page anyone. Save, then copy the **Push URL** it gives you
(`https://<kuma-host>/api/push/<token>`).

## Config

Add a top-level `heartbeat` key to the node's config JSON, alongside `home`,
`probe`, `relay`, etc.:

```json
{
  "name": "gh-backlog",
  "home": "/root/.fleetbroker-backlog",
  "probe": "fleetbroker.probes.gh_backlog",
  "heartbeat": {
    "url": "https://kuma.example.com/api/push/xxxxxxxxxxxxxxxxxxxxxxxx",
    "timeout_seconds": 5
  },
  "...": "..."
}
```

`timeout_seconds` is optional (default `5`). Omit the whole `heartbeat` key
(or leave out `url`) to leave heartbeat off entirely - this is an opt-in
feature, and a node with no `heartbeat` block behaves exactly as before.

Run `fleetbroker doctor <config>` after adding it - `doctor` fires one real
push and reports whether it reached the URL, so a copy-paste mistake in the
token shows up immediately instead of silently degrading to "always down"
in Kuma.

## Semantics

- The push fires once per `fleetbroker run` invocation, at the very end,
  after the probe tick has already run to completion **or** been skipped
  because another `run` for the same config was still in flight
  (`lock.LockHeld`) - both cases mean the cron fired and this process
  executed normally, which is the liveness question this feature answers.
- It does **not** fire if something raises past that point - a bug in the
  runner itself, not a probe-level data error (those are already caught
  inside `_run_locked()` and logged as `ERROR gathering data: ...` without
  crashing the tick). A genuinely broken node still shows as down.
- It reports `status=up` unconditionally on every fire. This is a dead-man's-
  switch pattern, not a health check of the probe's own decision: Kuma
  already infers "down" from a missing ping once the configured interval
  elapses, so there's no separate "push down" case to model. A probe-level
  data error still shows up in that node's own `log.txt` / `fleetbroker
  status` - the heartbeat only answers "is the process still ticking at
  all," not "is everything the probe checked healthy."
- A push failure (unreachable host, DNS failure, timeout, non-2xx from
  Kuma) is caught and logged to `log.txt` as `heartbeat push failed: ...`
  and never raised - a flaky or misconfigured monitor endpoint must never
  take down the probe tick it's supposed to be observing.

## What this does not do

- Does not add a runtime dependency - the push is a single stdlib
  `urllib.request` GET, matching this project's zero-dependency stance.
- Does not push per-probe outcome detail (e.g. "decision was green" vs "no
  green light") into the monitor - that distinction already lives in each
  node's own `log.txt` and in `fleetbroker status`. The heartbeat is
  liveness-only, by design; folding decision detail into it would blur two
  different questions ("is the node alive" vs "did it decide to do
  anything") into one signal.
- Does not require Uptime Kuma specifically - any endpoint that accepts a
  plain `GET <url>?status=up&msg=...` on a schedule works (Kuma's push
  monitor type is the reference target because it's free, self-hostable,
  and this project's own author runs one).
