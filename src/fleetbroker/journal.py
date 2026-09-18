from datetime import datetime, timezone
from pathlib import Path


def log(home: Path, msg: str) -> None:
    # Callers (e.g. `fleetbroker doctor`, which checks but does not create
    # `home`) may invoke this before the home dir exists yet - a logging
    # call must not be the thing that crashes a diagnostic path.
    home.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    with (home / "log.txt").open("a") as f:
        f.write(line)
