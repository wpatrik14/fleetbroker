import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import heartbeat
from . import journal
from . import lock
from . import state as state_mod
from .adapters.claude import remote_control as relay


def run(config: dict[str, Any], dry_run: bool = False) -> None:
    home = Path(config["home"]).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    probe = importlib.import_module(config["probe"])

    try:
        with lock.run_lock(home):
            _run_locked(probe, config, home, dry_run)
    except lock.LockHeld as e:
        journal.log(home, f"SKIP: {e}")

    # Fires on every completed tick, including a lock-contention SKIP - both
    # mean the cron fired and this process ran end-to-end. It deliberately
    # does NOT fire if something above raises a real exception (a bug, not a
    # probe-level data error - those are already caught inside
    # _run_locked() and don't propagate here), so a genuinely broken node
    # still shows as down. See docs/heartbeat.md.
    heartbeat.push(home, config.get("heartbeat"))


def _run_locked(probe: Any, config: dict[str, Any], home: Path, dry_run: bool) -> None:
    st = state_mod.load_state(home, probe.default_state())
    now = datetime.now(timezone.utc)

    try:
        data = probe.gather(config.get("probe_config", {}))
    except Exception as e:
        journal.log(home, f"ERROR gathering data: {e}")
        return

    derived = probe.prepare_state(st, data, now)
    decision = probe.decide(data, derived, now)

    cooldown_seconds = config.get("cooldown_seconds", 7200)
    last_notify = st.get("last_notify_epoch", 0)
    cooldown_active = (now.timestamp() - last_notify) < cooldown_seconds

    if decision.notify and not cooldown_active:
        journal.log(
            home,
            f"GREEN LIGHT: {decision.reason} (window={decision.window_minutes}min) - notifying",
        )
        body = probe.build_body(data, derived, decision)
        if dry_run:
            prompt = relay.build_prompt(config["relay"], body)
            journal.log(home, f"[dry-run] would relay argv+prompt: {prompt!r}")
        else:
            relay.relay(home, config["relay"], body)
        st["last_notify_epoch"] = now.timestamp()
    elif decision.notify:
        delta = now.timestamp() - last_notify
        journal.log(
            home,
            f"green light but cooldown active (last notify {delta:.0f}s ago): {decision.reason}",
        )
    else:
        journal.log(home, f"no green light: {decision.reason}")

    state_mod.save_state(home, st)
