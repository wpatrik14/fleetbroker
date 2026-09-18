"""The Claude Code CLI adapter for reading Anthropic account usage: reads
the already-authenticated `claude` CLI's own credentials file and calls
Anthropic's own (undocumented) OAuth usage endpoint. Isolated here because
both the credentials file's shape and the endpoint itself are unofficial -
see docs/compatibility.md and fleetbroker.probes.anthropic_usage's own
docstring for the full tradeoffs.
"""

import json
import urllib.request
from pathlib import Path
from typing import Any

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
API_BETA_HEADER = "oauth-2025-04-20"
DEFAULT_CREDENTIALS_PATH = "~/.claude/.credentials.json"


def fetch_usage(probe_config: dict[str, Any]) -> dict[str, Any]:
    """All I/O for the usage probe lives here - reading the credentials
    file and the live HTTP call - so fleetbroker.probes.anthropic_usage
    itself only has to know how to parse the response shape."""
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
        return json.loads(resp.read())
