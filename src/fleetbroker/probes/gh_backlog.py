"""Shared, multi-site backlog probe: notifies when an unclaimed GitHub issue
is available for this site to pick up, gated by a fairness check so one site
can't keep claiming work while a peer site's queue sits idle.

GitHub Issues themselves are the only shared state - no cross-node sync, no
extra data store. Labels carry all the policy inputs:
  priority:P1 / P2 / P3   - matches the existing AUTONOMOUS_BACKLOG.md convention
  size:S / M / L          - effort tag, same convention
  site:shared             - open to any site to claim
  site:<name>             - reserved for one site only, invisible to others
  claimed-by:<name>       - added by the *receiving* Claude session at claim
                            time (never by this probe - gather() only reads),
                            via `gh issue edit --add-assignee @me --add-label
                            claimed-by:<name>`. This is the lock; because it
                            lives on GitHub, every site sees the same truth.
"""

import json
import subprocess
from datetime import datetime, timedelta
from typing import Any

from ..probe import Decision

FAIRNESS_WINDOW_DAYS_DEFAULT = 7
_PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3}


def default_state() -> dict[str, Any]:
    return {}


def _gh_json(repo: str) -> list[dict]:
    result = subprocess.run(
        ["gh", "issue", "list", "-R", repo, "--state", "all",
         "--json", "number,title,url,state,labels,closedAt", "--limit", "200"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh issue list failed: {result.stderr}")
    return json.loads(result.stdout)


def gather(probe_config: dict[str, Any]) -> dict[str, Any]:
    repo = probe_config["repo"]
    my_site = probe_config["site"]
    return {
        "repo": repo,
        "my_site": my_site,
        "known_sites": probe_config.get("known_sites", [my_site]),
        "window_days": probe_config.get("fairness_window_days", FAIRNESS_WINDOW_DAYS_DEFAULT),
        "issues": _gh_json(repo),
    }


def _label_value(issue: dict, prefix: str) -> str | None:
    for label in issue.get("labels", []):
        name = label["name"] if isinstance(label, dict) else label
        if name.startswith(prefix):
            return name[len(prefix):]
    return None


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _recent_claim_counts(issues: list[dict], known_sites: list[str], cutoff: datetime) -> dict[str, int]:
    counts = {s: 0 for s in known_sites}
    for issue in issues:
        claimed_by = _label_value(issue, "claimed-by:")
        if claimed_by not in counts:
            continue
        if issue["state"] == "CLOSED":
            closed_at = issue.get("closedAt")
            if not closed_at or _parse_dt(closed_at) < cutoff:
                continue  # claimed long enough ago it no longer counts as "recent"
        counts[claimed_by] += 1
    return counts


def prepare_state(state: dict[str, Any], data: dict[str, Any], now: datetime) -> dict[str, Any]:
    my_site = data["my_site"]
    issues = data["issues"]

    candidates = []
    for issue in issues:
        if issue["state"] != "OPEN":
            continue
        if _label_value(issue, "claimed-by:") is not None:
            continue
        site_label = _label_value(issue, "site:")
        if site_label is not None and site_label not in ("shared", my_site):
            continue  # reserved for a different site
        candidates.append({
            "number": issue["number"],
            "title": issue["title"],
            "url": issue["url"],
            "priority": _label_value(issue, "priority:"),
            "size": _label_value(issue, "size:"),
        })
    candidates.sort(key=lambda c: (_PRIORITY_RANK.get(c["priority"], 9), c["number"]))

    cutoff = now - timedelta(days=data["window_days"])
    site_counts = _recent_claim_counts(issues, data["known_sites"], cutoff)

    return {
        "repo": data["repo"],
        "my_site": my_site,
        "window_days": data["window_days"],
        "candidates": candidates,
        "site_counts": site_counts,
    }


def decide(data: dict[str, Any], derived: dict[str, Any], now: datetime) -> Decision:
    candidates = derived["candidates"]
    if not candidates:
        return Decision(False, 0, "no eligible unclaimed backlog issue for this site")

    my_site = derived["my_site"]
    my_count = derived["site_counts"].get(my_site, 0)
    others = {s: c for s, c in derived["site_counts"].items() if s != my_site}
    if others:
        behind_site = min(others, key=others.get)
        min_other = others[behind_site]
        if my_count > min_other:
            return Decision(
                False, 0,
                f"fair-share hold-back: this site claimed {my_count} issue(s) in the last "
                f"{derived['window_days']}d, '{behind_site}' only {min_other} - waiting for peer",
            )

    top = candidates[0]
    return Decision(
        True, 0,
        f"{len(candidates)} eligible backlog issue(s), top: #{top['number']} "
        f"[{top['priority'] or '?'}/{top['size'] or '?'}] '{top['title']}'",
    )


def build_body(data: dict[str, Any], derived: dict[str, Any], decision: Decision) -> str:
    top = derived["candidates"][0]
    repo = derived["repo"]
    my_site = derived["my_site"]
    return (
        f"[Backlog-broker] There's a claimable item in the shared backlog ({repo}):\n"
        f"- #{top['number']} [{top['priority'] or '?'}/{top['size'] or '?'}] "
        f"{top['title']} - {top['url']}\n\n"
        f"Before starting: assign the issue to yourself and add the "
        f"'claimed-by:{my_site}' label (`gh issue edit {top['number']} -R {repo} "
        f"--add-assignee @me --add-label claimed-by:{my_site}`), so the other site sees "
        f"it's taken. If someone else already claimed it in the meantime, pick a different "
        f"candidate from the list, or report that no work is currently free."
    )
