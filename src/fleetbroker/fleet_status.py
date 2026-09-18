import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import state as state_mod
from .adapters.claude import status as claude_status


@dataclass
class NodeSummary:
    name: str
    decision_reason: str | None
    would_relay: bool | None
    last_relay: str
    cooldown_active: bool
    tmux_online: bool | None
    error: str | None = None


def summarize_node(name: str, config: dict[str, Any]) -> NodeSummary:
    """One-shot, read-only summary of a single node's config - never writes
    state.json, same guarantee as `fleetbroker status`. tmux_online is only
    meaningful for a node whose tmux session is reachable from *this* host;
    a node on a different site always reports None here (see fleet-status's
    own printed note about cross-checking ListAgents for real liveness)."""
    home = Path(config["home"]).expanduser()

    try:
        probe = importlib.import_module(config["probe"])
    except Exception as e:
        return NodeSummary(name, None, None, "unknown", False, None, error=f"failed to load probe: {e}")

    st = state_mod.load_state(home, probe.default_state())
    now = datetime.now(timezone.utc)
    last_notify = st.get("last_notify_epoch", 0)
    cooldown_seconds = config.get("cooldown_seconds", 7200)
    cooldown_active = bool(last_notify) and (now.timestamp() - last_notify) < cooldown_seconds
    last_relay = (
        datetime.fromtimestamp(last_notify, tz=timezone.utc).isoformat() if last_notify else "never"
    )

    try:
        data = probe.gather(config.get("probe_config", {}))
        derived = probe.prepare_state(dict(st), data, now)
        decision = probe.decide(data, derived, now)
    except Exception as e:
        return NodeSummary(name, None, None, last_relay, cooldown_active, None, error=f"gather failed: {e}")

    tmux_online = None
    target = config.get("relay", {}).get("target_tmux_session")
    if target:
        health = claude_status.tmux_session_health(target)
        tmux_online = health.has_live_claude_pane

    return NodeSummary(name, decision.reason, decision.notify, last_relay, cooldown_active, tmux_online)
