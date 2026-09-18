"""Same quota policy as ha_quota, but reads usage directly from Anthropic's
own (undocumented) OAuth usage endpoint using the already-authenticated
`claude` CLI's own credentials.

No Home Assistant, no separate HACS integration, no separate OAuth client
registration, no extra login step: every fleetbroker node already needs a
working `claude auth login` for Remote Control (see docs/auth.md), and that
same token already carries the `user:profile` scope this endpoint needs.

This removes a real dependency for anyone standing up a new node - "log
into claude" is something they do anyway; "also run Home Assistant plus a
specific HACS integration just to read your own quota" was never load-
bearing, it was just how the original deployment happened to already have
this data lying around. See docs/direct-api.md for how this was found,
and the tradeoffs of depending on an undocumented endpoint.

decide()/prepare_state()/build_body()/default_state() are intentionally
re-exported from ha_quota unchanged - the policy doesn't depend on where
the numbers came from, only gather() differs.
"""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ha_quota import build_body, decide, default_state, prepare_state  # noqa: F401

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
API_BETA_HEADER = "oauth-2025-04-20"
DEFAULT_CREDENTIALS_PATH = "~/.claude/.credentials.json"


def gather(probe_config: dict[str, Any]) -> dict[str, Any]:
    creds_path = Path(probe_config.get("credentials_path", DEFAULT_CREDENTIALS_PATH)).expanduser()
    creds = json.loads(creds_path.read_text())
    access_token = creds["claudeAiOauth"]["accessToken"]

    req = urllib.request.Request(
        USAGE_API_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": API_BETA_HEADER,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.loads(resp.read())

    return _parse_usage(raw)


def _parse_usage(raw: dict[str, Any]) -> dict[str, Any]:
    five_hour = raw.get("five_hour") or {}
    seven_day = raw.get("seven_day") or {}

    session_usage = five_hour.get("utilization")
    week_usage = seven_day.get("utilization")

    session_reset = None
    if five_hour.get("resets_at"):
        session_reset = datetime.fromisoformat(five_hour["resets_at"])

    week_reset = None
    week_pace = None
    if seven_day.get("resets_at"):
        week_reset = datetime.fromisoformat(seven_day["resets_at"])
        if week_usage is not None:
            now = datetime.now(timezone.utc)
            week_seconds = 7 * 24 * 60 * 60
            elapsed = week_seconds - (week_reset - now).total_seconds()
            percent_elapsed = (elapsed / week_seconds) * 100
            # Same pace formula as the HACS integration this was ported from
            # (trickv/hass-claude-usage) - kept identical so a node switching
            # from the ha_quota probe to this one sees no policy behavior
            # change, only a different data source.
            week_pace = round(week_usage - percent_elapsed, 1)

    return {
        "session_usage": session_usage,
        "week_usage": week_usage,
        "session_reset": session_reset,
        "week_reset": week_reset,
        "week_pace": week_pace,
    }
