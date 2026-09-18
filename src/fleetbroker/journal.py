from datetime import datetime, timezone
from pathlib import Path


def log(home: Path, msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    with (home / "log.txt").open("a") as f:
        f.write(line)
