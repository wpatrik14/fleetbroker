import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockHeld(Exception):
    """Another process already holds the run lock for this home dir."""


@contextmanager
def run_lock(home: Path) -> Iterator[None]:
    """Non-blocking exclusive lock so two overlapping `fleetbroker run`
    invocations against the same home dir never race on state.json - one
    loses immediately (raises LockHeld) instead of both reading the same
    stale last_notify_epoch and both relaying."""
    lock_path = home / "fleetbroker.lock"
    lock_file = lock_path.open("w")
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LockHeld(f"another fleetbroker run already holds {lock_path}")
        yield
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
