from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass
class Decision:
    notify: bool
    window_minutes: int
    reason: str


class Probe(Protocol):
    """Contract a fleetbroker probe module must implement as module-level functions.

    The runner owns gather()'s exception handling, the cooldown check, and the
    relay call itself - a probe only supplies data and policy, never touches
    the relay mechanism directly.
    """

    def default_state(self) -> dict[str, Any]: ...

    def gather(self, probe_config: dict[str, Any]) -> Any:
        """Do all I/O (HTTP, subprocess, file reads). May raise - the runner
        wraps this call and logs+returns on any exception, so nothing needs
        to be caught here."""
        ...

    def prepare_state(self, state: dict[str, Any], data: Any, now: datetime) -> Any:
        """Mutate `state` in place if needed (e.g. daily-cap baseline) and
        return whatever derived value decide() needs alongside `data`."""
        ...

    def decide(self, data: Any, derived: Any, now: datetime) -> Decision: ...

    def build_body(self, data: Any, derived: Any, decision: Decision) -> str:
        """Only called when decision.notify is True - the message text handed
        to relay.relay() as the payload."""
        ...
