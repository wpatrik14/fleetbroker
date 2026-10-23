"""Reference probe with no policy engine at all - proves the runner/probe
split works for a bare watermark comparison, not just the quota policy.

Config (``probe_config``): exactly one of

* ``"repo": "owner/name"`` - watch a single repository (original behaviour,
  unchanged output), or
* ``"repos": ["owner/name", ...]`` - watch several repositories from one
  node; every reported item is prefixed with its repository.

Watermarks: ``state["last_check"]`` is the original single watermark. In
multi-repo mode the probe additionally keeps ``state["repo_checks"]``, a
``{repo: iso timestamp}`` map, and advances a repository's entry only when
that repository was fetched successfully. A repository that fails keeps its
old watermark, so its activity is reported on the first tick after it
recovers, while repositories that succeeded are never re-reported.
``last_check`` is kept equal to the oldest per-repo watermark, so it stays a
valid fallback for a repository that has no entry yet (e.g. a newly added
one, or a ``state.json`` written before multi-repo support existed).
"""

import json
import re
import subprocess
from datetime import datetime
from typing import Any

from ..probe import Decision

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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


def resolve_repos(probe_config: dict[str, Any]) -> tuple[list[str], bool]:
    """Validate the config and return ``(repos, multi)``.

    ``multi`` is False for the legacy ``repo`` form, which is deliberately not
    format-checked (any value ``gh -R`` accepts keeps working).
    """
    has_repo = "repo" in probe_config
    has_repos = "repos" in probe_config
    if has_repo and has_repos:
        raise ValueError("probe_config: set either 'repo' or 'repos', not both")
    if not has_repo and not has_repos:
        raise ValueError("probe_config: one of 'repo' (string) or 'repos' (list) is required")

    if has_repo:
        repo = probe_config["repo"]
        if not isinstance(repo, str) or not repo.strip():
            raise ValueError("probe_config: 'repo' must be a non-empty string")
        return [repo], False

    repos = probe_config["repos"]
    if not isinstance(repos, list) or not repos:
        raise ValueError("probe_config: 'repos' must be a non-empty list of 'owner/name' strings")
    seen: dict[str, str] = {}
    for r in repos:
        if not isinstance(r, str) or not _REPO_RE.match(r):
            raise ValueError(f"probe_config: invalid repository name in 'repos': {r!r} (expected 'owner/name')")
        key = r.lower()  # GitHub owner/repo names are case-insensitive
        if key in seen:
            raise ValueError(f"probe_config: duplicate repository in 'repos': {r!r}")
        seen[key] = r
    return list(repos), True


def gather(probe_config: dict[str, Any]) -> dict[str, Any]:
    repos, multi = resolve_repos(probe_config)
    issues: list[dict] = []
    prs: list[dict] = []
    fetched: list[str] = []
    errors: dict[str, str] = {}
    for repo in repos:
        try:
            repo_issues = _gh_json(repo, "issue", "list")
            repo_prs = _gh_json(repo, "pr", "list")
        except Exception as e:
            if not multi:
                raise  # legacy: the runner logs it and keeps the old state
            errors[repo] = str(e).strip() or type(e).__name__
            continue
        issues += [{**i, "repo": repo} for i in repo_issues]
        prs += [{**p, "repo": repo} for p in repo_prs]
        fetched.append(repo)
    if not fetched:
        raise RuntimeError("all repositories failed: " + "; ".join(f"{r}: {m}" for r, m in errors.items()))
    return {"multi": multi, "repos": fetched, "errors": errors, "issues": issues, "prs": prs}


def prepare_state(state: dict[str, Any], data: dict[str, Any], now: datetime) -> dict[str, list[dict]]:
    fallback = datetime.fromisoformat(state["last_check"])
    checks: dict[str, str] = state.get("repo_checks", {}) if data.get("multi") else {}

    def mark(item: dict) -> datetime:
        return datetime.fromisoformat(checks[item["repo"]]) if item.get("repo") in checks else fallback

    updated = {
        "issues": [i for i in data["issues"] if datetime.fromisoformat(i["updatedAt"]) > mark(i)],
        "prs": [p for p in data["prs"] if datetime.fromisoformat(p["updatedAt"]) > mark(p)],
    }

    if not data.get("multi"):
        state["last_check"] = now.isoformat()
        return updated

    configured = list(data["repos"]) + list(data.get("errors", {}))
    new_checks = {r: checks.get(r, state["last_check"]) for r in configured}
    for r in data["repos"]:
        new_checks[r] = now.isoformat()
    state["repo_checks"] = new_checks
    state["last_check"] = min(new_checks.values(), key=datetime.fromisoformat)
    return updated


def decide(data: dict[str, Any], derived: dict[str, list[dict]], now: datetime) -> Decision:
    failed = f" ({len(data['errors'])} repo(s) failed to fetch)" if data.get("errors") else ""
    n = len(derived["issues"]) + len(derived["prs"])
    if n == 0:
        return Decision(False, 0, "no new issue/PR activity since last check" + failed)
    return Decision(True, 0, f"{n} new/updated issue(s)/PR(s) since last check" + failed)


def build_body(data: dict[str, Any], derived: dict[str, list[dict]], decision: Decision) -> str:
    def tag(item: dict) -> str:
        return f"[{item['repo']}] " if data.get("multi") and item.get("repo") else ""

    lines = ["[Repo-watch] New/updated items:"]
    for i in derived["issues"]:
        lines.append(f"- {tag(i)}Issue #{i['number']} [{i['state']}]: {i['title']} - {i['url']}")
    for p in derived["prs"]:
        lines.append(f"- {tag(p)}PR #{p['number']} [{p['state']}]: {p['title']} - {p['url']}")
    for repo, message in data.get("errors", {}).items():
        lines.append(f"- [{repo}] could not be fetched (will retry next run): {message}")
    return "\n".join(lines)
