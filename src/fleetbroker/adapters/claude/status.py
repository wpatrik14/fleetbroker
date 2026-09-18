"""The Claude Code CLI adapter for everything `doctor`/`status` need to ask
the CLI and tmux about themselves: is `claude` on PATH, is it logged in,
what version is it, and is the persistent Remote Control tmux session
actually alive (not just what systemd claims - see docs/incidents.md #4).
Isolated here, not inlined in cli.py, because every one of these calls
depends on Claude Code CLI/tmux output shapes that aren't a documented,
stable contract - see docs/compatibility.md.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass


def claude_binary() -> str | None:
    return shutil.which("claude")


@dataclass
class AuthStatus:
    ok: bool
    raw: str
    info: dict | None  # parsed JSON from `claude auth status`, if it was one


def get_auth_status() -> AuthStatus:
    result = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=15)
    raw = result.stdout.strip() or result.stderr.strip()
    try:
        info = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        info = None
    return AuthStatus(ok=result.returncode == 0, raw=raw, info=info)


def get_version_string() -> str:
    result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=15)
    return result.stdout.strip() or result.stderr.strip()


@dataclass
class TmuxSessionHealth:
    exists: bool
    panes: list[str]

    @property
    def has_live_claude_pane(self) -> bool:
        return "claude" in self.panes


def tmux_session_health(target: str) -> TmuxSessionHealth:
    has_session = subprocess.run(["tmux", "has-session", "-t", target], capture_output=True).returncode == 0
    if not has_session:
        return TmuxSessionHealth(exists=False, panes=[])
    panes = subprocess.run(
        ["tmux", "list-panes", "-t", target, "-F", "#{pane_current_command}"],
        capture_output=True, text=True,
    ).stdout.split()
    return TmuxSessionHealth(exists=True, panes=panes)
