"""Optional liveness heartbeat to an external dead-man's-switch monitor
(e.g. Uptime Kuma's "Push" monitor type) - see docs/heartbeat.md.

Deliberately isolated from the probe/policy/relay pipeline: a heartbeat push
is a courtesy signal for external monitoring, not part of the fleet's own
coordination logic. A broken or unreachable monitor endpoint must never
affect a probe tick, so every failure is caught and logged, never raised.
"""
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import journal


def push(home: Path, config: dict[str, Any] | None, msg: str = "tick ok") -> bool | None:
    """Fire a GET at a push-style monitor URL, if configured.

    `config` is a node config's optional top-level "heartbeat" dict:
    `{"url": "https://kuma.example.com/api/push/<token>", "timeout_seconds": 5}`.

    Returns None if heartbeat isn't configured (missing dict or "url") - a
    silent, opt-in no-op. Returns True/False for an attempted push so callers
    that care about the outcome (e.g. `fleetbroker doctor`) can report it;
    `runner.run()` ignores the return value - a failed push is already logged
    here and must not affect the tick itself.
    """
    if not config:
        return None
    url = config.get("url")
    if not url:
        return None

    timeout = config.get("timeout_seconds", 5)
    query = urllib.parse.urlencode({"status": "up", "msg": msg[:200]})
    separator = "&" if "?" in url else "?"
    full_url = f"{url}{separator}{query}"

    try:
        with urllib.request.urlopen(full_url, timeout=timeout) as resp:
            resp.read()
        return True
    except Exception as e:
        journal.log(home, f"heartbeat push failed: {e}")
        return False
