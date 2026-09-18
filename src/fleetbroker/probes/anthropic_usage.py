"""Flagship probe: reads Anthropic account usage directly from Anthropic's
own (undocumented) OAuth usage endpoint, using the already-authenticated
`claude` CLI's own credentials, and relays a green light when there's spare
quota to safely hand to another fleet participant.

Every fleetbroker node already needs a working `claude auth login` for
Remote Control (see docs/auth.md), and that same token already carries the
`user:profile` scope this endpoint needs - no separate OAuth client, no
separate login, no extra dependency to stand up.

`decide()`/`prepare_state()`/`build_body()`/`default_state()` are
intentionally re-exported from `fleetbroker.probes.quota_policy` unchanged -
the policy doesn't depend on where the numbers came from, only `gather()`
does.

## How this endpoint was found

Checking `~/.claude/.credentials.json` shows the `claude` CLI's own token
already carries `user:profile` among its scopes (alongside `user:inference`,
`user:mcp_servers`, etc.), and a live call with that exact token against
`GET https://api.anthropic.com/api/oauth/usage` returns `200 OK` with real
usage data. This is what claude.ai's own web UI uses internally - it is not
a published/versioned API, so it can change or disappear without notice.

## Tradeoffs, stated plainly

- **Undocumented, unofficial endpoint.** No stability guarantee. If it
  breaks, this probe needs a matching fleetbroker update.
- **Token lifecycle is borrowed, not owned.** This probe reads whatever
  access token is currently sitting in the credentials file; it does not
  refresh it. In practice this is fine on a fleetbroker node, because the
  persistent `claude rc` session in the same tmux `claude` session is always
  active and refreshes its own token through normal use - by the time this
  probe's token would be stale, the live session has almost always already
  refreshed it. If a tick does hit an expired token, `gather()`'s failure is
  caught by the runner's standard guarded-gather handling (one clean log
  line, no crash, tried again next tick) exactly like any other probe
  failure - it is not a special case.
- **Reading `~/.claude/.credentials.json` is a sensitive-file operation.**
  Treat `credentials_path` in probe_config as sensitive-adjacent
  configuration even though it's just a path, not a secret itself - the file
  it points to holds the same live token that authenticates this node's
  entire Remote Control identity.
"""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .quota_policy import build_body, decide, default_state, prepare_state  # noqa: F401

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
            week_pace = round(week_usage - percent_elapsed, 1)

    return {
        "session_usage": session_usage,
        "week_usage": week_usage,
        "session_reset": session_reset,
        "week_reset": week_reset,
        "week_pace": week_pace,
    }
