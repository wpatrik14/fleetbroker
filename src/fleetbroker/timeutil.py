"""Small time helpers shared by the probes."""

from datetime import datetime


def parse_iso_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, accepting a trailing ``Z`` or ``z``.

    ``datetime.fromisoformat`` only accepts the ``Z`` UTC designator from
    Python 3.11 on, but APIs and CLIs (``gh``, the Anthropic usage endpoint)
    emit it routinely; normalise it to ``+00:00`` so Python 3.10 behaves like
    newer versions. Everything else is passed through unchanged, so a naive
    input stays naive and an offset-aware one keeps its offset.
    """
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)
