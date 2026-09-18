import json
from pathlib import Path
from typing import Any


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text())
