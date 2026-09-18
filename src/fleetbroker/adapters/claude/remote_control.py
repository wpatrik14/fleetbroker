"""The Claude Code CLI adapter for relaying a message to the one persistent,
full-context peer session - the only piece of fleetbroker that actually
shells out to `claude`. Isolated here (not in core scheduling/policy code)
because its correctness depends entirely on Claude Code CLI behavior that
isn't a documented, stable contract - see docs/compatibility.md."""

import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

from ... import journal

# Load-bearing: this exact flag combination avoids spawning a full MCP-server
# roster on every one-shot invocation. An earlier design without
# --strict-mcp-config hard-crashed the host container (spawned ~6 node
# processes per fire, 3 fires in 24 minutes required a forced reboot).
# --allowed-tools makes the one-shot structurally incapable of doing anything
# but relay, even if a probe's body text (e.g. gh_backlog embeds untrusted
# GitHub Issue titles) tries to talk it into something else - this is a real
# hardening measure, not just prompt wording, since prompt instructions alone
# are not a security boundary. Probes cannot override any of this - they
# only ever supply a message body.
RELAY_ARGV_PREFIX = [
    "claude", "-p",
    "--strict-mcp-config",
    "--mcp-config", '{"mcpServers":{}}',
    "--allowed-tools", "ListAgents", "SendMessage",
    "--",
]

DEFAULT_TIMEOUT_SECONDS = 180


def _forbidden_clause(cfg: dict[str, Any], locale: str) -> str:
    tmux_names = cfg.get("forbidden_tmux_sessions", [])
    peer_names = cfg.get("forbidden_peer_names", [])
    if not tmux_names and not peer_names:
        return ""

    if locale == "hu":
        parts = []
        if tmux_names:
            parts.append("NE a " + " vagy ".join(f"'{n}'" for n in tmux_names) + " tmux session-t")
        if peer_names:
            parts.append(
                "NE kozvetlenul a " + " vagy ".join(f"'{n}'" for n in peer_names)
                + " nevut - csak a home sessiont"
            )
        return " (" + ", es ".join(parts) + ")"

    parts = []
    if tmux_names:
        parts.append("NOT the " + " or ".join(f"'{n}'" for n in tmux_names) + " tmux session")
    if peer_names:
        parts.append(
            "NOT the " + " or ".join(f"'{n}'" for n in peer_names)
            + " peer(s) directly - only the home session"
        )
    return " (" + ", and ".join(parts) + ")"


def build_prompt(cfg: dict[str, Any], body: str) -> str:
    locale = cfg.get("prompt_locale", "en")
    template_path = resources.files("fleetbroker.prompts").joinpath(f"relay_{locale}.txt")
    template = template_path.read_text()
    return template.format(
        body=body,
        target=cfg["target_tmux_session"],
        forbidden_clause=_forbidden_clause(cfg, locale),
    )


def relay(home: Path, cfg: dict[str, Any], body: str) -> bool:
    """Shell out to a one-shot, MCP-free Claude invocation to relay `body` to
    the one allow-listed peer. Never raises - a hung/missing `claude` binary
    is logged and swallowed here so the caller can always persist state
    (a prior bug let a TimeoutExpired here kill the whole run before state
    was saved, which meant the cooldown never engaged and a new hung process
    got spawned every single tick)."""
    prompt = build_prompt(cfg, body)
    argv = RELAY_ARGV_PREFIX + [prompt]
    timeout = cfg.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        journal.log(home, f"notify_home failed to run: {e}")
        return False
    journal.log(
        home,
        f"notify_home rc={result.returncode} stdout={result.stdout[:500]!r} stderr={result.stderr[:500]!r}",
    )
    return True
