import json
import os
from pathlib import Path
from typing import Any


def load_state(home: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    state_file = home / "state.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return dict(defaults)


def save_state(home: Path, state: dict[str, Any]) -> None:
    state_file = home / "state.json"
    tmp_file = state_file.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(state))
    os.replace(tmp_file, state_file)
