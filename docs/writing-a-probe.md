# Writing a probe

A probe is a plain Python module (referenced by dotted path in a node's
config, e.g. `"probe": "fleetbroker.probes.ha_quota"`) exposing five
module-level functions. See `fleetbroker.probe.Probe` for the formal
`Protocol`, and `fleetbroker.probes.gh_repo_watch` for the simplest possible
real example (no policy engine at all - just a last-seen watermark).

```python
def default_state() -> dict:
    """The state dict used on a node's very first run."""

def gather(probe_config: dict) -> Any:
    """Do ALL your I/O here - HTTP calls, subprocess calls, file reads.
    Raise freely on any failure; the runner wraps this call and turns any
    exception into one clean log line, so you don't need your own
    try/except for this."""

def prepare_state(state: dict, data: Any, now: datetime) -> Any:
    """Mutate `state` in place if you need to track something across runs
    (e.g. a daily baseline, a last-seen timestamp), and return whatever
    `decide()` needs alongside `data`. Called before decide() - if your
    policy depends on a value derived from stateful bookkeeping, compute it
    here, not inside decide()."""

def decide(data: Any, derived: Any, now: datetime) -> Decision:
    """Pure policy function - given the gathered data and whatever
    prepare_state() derived, return a Decision(notify, window_minutes,
    reason). Keep this pure (no I/O, no state mutation) so it stays trivially
    unit-testable, the way fleetbroker.probes.ha_quota.decide() is."""

def build_body(data: Any, derived: Any, decision: Decision) -> str:
    """Only called when decision.notify is True. Return the message text to
    hand to the relay - this is the ONLY thing your probe controls about the
    relay; the allow-list/deny-list framing around it is added by
    fleetbroker.relay and cannot be overridden."""
```

## What the runner guarantees you, so your probe doesn't have to

- Every run's decision is logged, whether or not it results in a relay.
- A relay is only attempted if `decision.notify` is true AND the configured
  cooldown has elapsed since the last successful relay attempt - the
  cooldown does not suppress the decision log line, only the relay call.
- State is always persisted at the end of a successful `gather()`, regardless
  of whether a relay was attempted, attempted-and-cooled-down, or skipped.
- A relay call itself never raises back into your probe or the runner - a
  hung/missing `claude` binary is logged and treated as "the relay didn't
  happen this tick," not a crash.

## Testing your probe

Keep `decide()` pure and it's nearly free to test exhaustively - see
`tests/test_decide.py` for the pattern (one test per precedence branch, plus
edge cases). `tests/test_state_baseline.py` shows the same approach for
`prepare_state()`.
