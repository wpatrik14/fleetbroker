"""Tracks which Claude Code CLI versions this project has actually been
verified against, so `fleetbroker doctor` can distinguish "known good" from
"untested" instead of staying silent about a real risk: this project
depends on several Claude Code CLI internals that aren't a documented,
stable contract (ListAgents/SendMessage behavior, `claude rc` flags, the
`~/.claude.json` structure, the credentials file layout - see
docs/incidents.md). An unverified version is not necessarily broken, so
this never produces a hard failure, only a warning.
"""

import re

KNOWN_GOOD_MIN = (2, 1, 0)
KNOWN_GOOD_MAX_EXCLUSIVE = (3, 0, 0)

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_version(version_string: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(version_string)
    if not match:
        return None
    return tuple(int(g) for g in match.groups())


def _fmt(version: tuple[int, int, int]) -> str:
    return ".".join(str(p) for p in version)


def check_version(version_string: str) -> tuple[str, str]:
    """Returns (status, detail), status always "OK" or "WARN" - an
    unverified version is a reason for caution, not a doctor failure."""
    parsed = parse_version(version_string)
    if parsed is None:
        return "WARN", f"could not parse a version from {version_string!r}"
    if KNOWN_GOOD_MIN <= parsed < KNOWN_GOOD_MAX_EXCLUSIVE:
        return "OK", f"{_fmt(parsed)} is within the verified range (>= {_fmt(KNOWN_GOOD_MIN)}, < {_fmt(KNOWN_GOOD_MAX_EXCLUSIVE)})"
    if parsed < KNOWN_GOOD_MIN:
        return "WARN", f"{_fmt(parsed)} is older than the verified minimum {_fmt(KNOWN_GOOD_MIN)} - untested, may be missing required behavior"
    return "WARN", f"{_fmt(parsed)} is a newer major version than verified (last verified below {_fmt(KNOWN_GOOD_MAX_EXCLUSIVE)}) - untested, not necessarily broken"
