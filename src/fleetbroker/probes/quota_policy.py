"""Shared quota policy: decide whether there's spare Anthropic account usage
to safely hand to another fleet participant right now.

Every constant and precedence rule below is ported verbatim from the
production quota-broker this project generalizes - see docs/incidents.md for
the operational history behind each one. Do not "simplify" the precedence
chain without re-reading that history first.

This module holds only the policy (`decide`/`prepare_state`/`build_body`/
`default_state`) - it has no I/O of its own. `fleetbroker.probes.anthropic_usage`
supplies the data via its own `gather()` and re-exports these functions
unchanged, so a probe swap never changes policy behavior.
"""

from datetime import datetime
from typing import Any

from ..probe import Decision

WEEK_STOP_PCT = 85
SESSION_RISK_PCT = 70
PACE_AHEAD = -20
PACE_BEHIND = 10
SESSION_RISK_PCT_LENIENT = 80
SESSION_RISK_PCT_STRICT = 55
SESSION_URGENT_MINUTES = 45
SESSION_URGENT_UNUSED_PCT = 10
WEEK_URGENT_MINUTES = 120
WEEK_URGENT_UNUSED_PCT = 15
DEFAULT_WINDOW_MINUTES = 45
MAX_URGENT_WINDOW_MINUTES = 60
DAILY_CAP_PCT = 14


def default_state() -> dict[str, Any]:
    return {"last_notify_epoch": 0, "day_start_date": None, "day_start_week_usage": 0.0}


def prepare_state(state: dict[str, Any], data: dict[str, Any], now: datetime) -> float:
    """Update the daily-cap baseline in `state` in place, return today's
    daily_used_pct so far."""
    week_usage = data["week_usage"]
    today = now.date().isoformat()

    if week_usage < state.get("day_start_week_usage", 0):
        # Genuine weekly reset detected (week_usage dropped below the stored
        # baseline). Always snap to exactly 0, never the observed post-reset
        # reading - any usage between the true reset moment and our next
        # successful check (crash gap, missed cron tick, ...) must still
        # count fully against today's cap, or the day gets free grandfathered
        # points it didn't earn.
        state["day_start_date"] = today
        state["day_start_week_usage"] = 0.0
    elif state.get("day_start_date") != today:
        # Plain new-calendar-day rollover with no reset detected: carry the
        # current cumulative total forward as the new baseline (each day
        # adds its own DAILY_CAP_PCT on top of the week so far).
        state["day_start_date"] = today
        state["day_start_week_usage"] = week_usage

    return week_usage - state["day_start_week_usage"]


def decide(data: dict[str, Any], derived: float, now: datetime) -> Decision:
    daily_used_pct = derived
    session_usage = data["session_usage"]
    week_usage = data["week_usage"]
    session_reset = data["session_reset"]
    week_reset = data["week_reset"]
    week_pace = data["week_pace"]

    mins_to_session_reset = (
        (session_reset - now).total_seconds() / 60 if session_reset is not None else float("inf")
    )
    mins_to_week_reset = (
        (week_reset - now).total_seconds() / 60 if week_reset is not None else float("inf")
    )

    # 1. Hard weekly ceiling - never go above this regardless of anything else.
    if week_usage >= WEEK_STOP_PCT:
        return Decision(False, 0, f"week usage {week_usage}% >= {WEEK_STOP_PCT}% stop threshold")

    # 2. Pace-projection pullback: if the current burn rate would blow past
    # the hard ceiling before the week actually resets, stop handing out more
    # room even though neither the ceiling nor the daily cap has fired yet.
    days_to_week_reset = mins_to_week_reset / 1440 if mins_to_week_reset != float("inf") else None
    if week_pace is not None and days_to_week_reset is not None:
        projected_week_usage = week_usage + week_pace * days_to_week_reset
        if projected_week_usage >= WEEK_STOP_PCT and mins_to_week_reset >= WEEK_URGENT_MINUTES:
            return Decision(
                False, 0,
                f"pace {week_pace}%/day would reach {projected_week_usage:.0f}% before the "
                f"{days_to_week_reset:.1f}d-away reset (>= {WEEK_STOP_PCT}% ceiling) - pulling back",
            )

    # 3. Daily cap - deliberately checked before urgency logic, no exceptions,
    # even for an imminent reset. Keeps the rule simple.
    if daily_used_pct >= DAILY_CAP_PCT:
        return Decision(
            False, 0,
            f"daily cap reached: {daily_used_pct:.1f} pts of week usage burned today "
            f"(cap {DAILY_CAP_PCT}%)",
        )

    # 4. "Use it or lose it": a reset is close enough that unused room would
    # otherwise be wasted. Soonest reset wins if both fire.
    urgent = []
    if mins_to_session_reset < SESSION_URGENT_MINUTES and (100 - session_usage) >= SESSION_URGENT_UNUSED_PCT:
        urgent.append(("session", mins_to_session_reset))
    if mins_to_week_reset < WEEK_URGENT_MINUTES and (100 - week_usage) >= WEEK_URGENT_UNUSED_PCT:
        urgent.append(("week", mins_to_week_reset))
    if urgent:
        kind, soonest = min(urgent, key=lambda x: x[1])
        window = max(5, min(MAX_URGENT_WINDOW_MINUTES, round(soonest) - 5))
        return Decision(
            True, window,
            f"{kind} reset in {soonest:.0f}min with unused room - use it before it resets",
        )

    # 5. Pace-adjusted session-risk threshold.
    risk_pct = SESSION_RISK_PCT
    if week_pace is not None:
        if week_pace <= PACE_AHEAD:
            risk_pct = SESSION_RISK_PCT_LENIENT
        elif week_pace >= PACE_BEHIND:
            risk_pct = SESSION_RISK_PCT_STRICT
    if session_usage >= risk_pct:
        return Decision(
            False, 0,
            f"session usage {session_usage}% >= {risk_pct}% risk threshold (pace={week_pace}), "
            f"reset {mins_to_session_reset:.0f}min away - too risky",
        )

    # 6. Default green light.
    return Decision(
        True, DEFAULT_WINDOW_MINUTES,
        f"room available: session {session_usage}%, week {week_usage}% (pace={week_pace}), "
        f"no urgent reset",
    )


def build_body(data: dict[str, Any], derived: float, decision: Decision) -> str:
    daily_used_pct = derived
    daily_headroom = DAILY_CAP_PCT - daily_used_pct
    return (
        f"[Quota-broker] Green light - spare quota available right now "
        f"(session usage {data['session_usage']}%, week usage {data['week_usage']}%, "
        f"roughly a {decision.window_minutes}min window; today's daily cap: "
        f"{daily_used_pct:.1f}/{DAILY_CAP_PCT}% used, about {daily_headroom:.1f} points left "
        f"today). If daily headroom is already thin (a few points or less), only start a "
        f"small-effort backlog item, not a large multi-step one that a depleted cap could "
        f"cut off mid-way."
    )
