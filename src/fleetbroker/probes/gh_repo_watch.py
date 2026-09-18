"""Reference probe with no policy engine at all - proves the runner/probe
split works for a bare watermark comparison, not just the quota policy."""

import json
import subprocess
from datetime import datetime
from typing import Any

from ..probe import Decision


def default_state() -> dict[str, Any]:
    return {"last_notify_epoch": 0, "last_check": "2000-01-01T00:00:00+00:00"}


def _gh_json(repo: str, *args: str) -> list[dict]:
    result = subprocess.run(
        ["gh", *args, "-R", repo, "--state", "all",
         "--json", "number,title,state,updatedAt,url", "--limit", "50"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {args} failed: {result.stderr}")
    return json.loads(result.stdout)


def gather(probe_config: dict[str, Any]) -> dict[str, Any]:
    repo = probe_config["repo"]
    return {
        "issues": _gh_json(repo, "issue", "list"),
        "prs": _gh_json(repo, "pr", "list"),
    }


def prepare_state(state: dict[str, Any], data: dict[str, Any], now: datetime) -> dict[str, list[dict]]:
    last_check = datetime.fromisoformat(state["last_check"])
    updated = {
        "issues": [i for i in data["issues"] if datetime.fromisoformat(i["updatedAt"]) > last_check],
        "prs": [p for p in data["prs"] if datetime.fromisoformat(p["updatedAt"]) > last_check],
    }
    state["last_check"] = now.isoformat()
    return updated


def decide(data: dict[str, Any], derived: dict[str, list[dict]], now: datetime) -> Decision:
    n = len(derived["issues"]) + len(derived["prs"])
    if n == 0:
        return Decision(False, 0, "no new issue/PR activity since last check")
    return Decision(True, 0, f"{n} new/updated issue(s)/PR(s) since last check")


def build_body(data: dict[str, Any], derived: dict[str, list[dict]], decision: Decision) -> str:
    lines = ["[Repo-watch] New/updated items:"]
    for i in derived["issues"]:
        lines.append(f"- Issue #{i['number']} [{i['state']}]: {i['title']} - {i['url']}")
    for p in derived["prs"]:
        lines.append(f"- PR #{p['number']} [{p['state']}]: {p['title']} - {p['url']}")
    return "\n".join(lines)
