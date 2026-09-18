import argparse
import importlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import fleet_status
from . import lock
from . import runner
from . import state as state_mod
from .adapters.claude import status as claude_status
from .adapters.claude.compat import check_version
from .config import load_config


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    runner.run(config, dry_run=args.dry_run)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        status = "OK" if passed else "FAIL"
        print(f"[{status}] {label}" + (f" - {detail}" if detail else ""))
        if not passed:
            ok = False

    claude_bin = claude_status.claude_binary()
    check("claude on PATH", claude_bin is not None, claude_bin or "not found")

    if claude_bin:
        auth = claude_status.get_auth_status()
        check("claude auth status", auth.ok, auth.raw)

        # Never a hard failure - an unverified CLI version is a reason for
        # caution, not proof of breakage. See fleetbroker.adapters.claude.compat
        # and docs/compatibility.md.
        version_status, version_detail = check_version(claude_status.get_version_string())
        print(f"[{version_status}] claude version - {version_detail}")

    target = config.get("relay", {}).get("target_tmux_session")
    if target:
        health = claude_status.tmux_session_health(target)
        check(f"tmux session '{target}' exists", health.exists)
        if health.exists:
            check(f"tmux session '{target}' has a live claude pane", health.has_live_claude_pane, str(health.panes))

    home = Path(config["home"]).expanduser()
    check(f"home dir '{home}' writable", os.access(home, os.W_OK) if home.exists() else True)

    check("config has 'probe' key", "probe" in config)
    check("config has 'relay' key", "relay" in config)

    check(
        f"crontab has an entry for this config",
        _crontab_has_entry(str(args.config)),
    )

    # Never a hard failure - a briefly-held lock just means a run is
    # genuinely in progress right now, not a bug. See issue #8.
    if home.exists():
        try:
            with lock.run_lock(home):
                pass
            print("[OK] run lock available (no other fleetbroker run in progress)")
        except lock.LockHeld:
            print("[INFO] run lock currently held - another fleetbroker run is in progress for this config")

    print()
    print("Overall: " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    home = Path(config["home"]).expanduser()

    print(f"NODE  ({config.get('name', str(args.config))})")

    claude_bin = claude_status.claude_binary()
    if claude_bin is None:
        print("  claude auth:   claude not found on PATH")
    else:
        auth = claude_status.get_auth_status()
        if auth.info:
            print(
                f"  claude auth:   {auth.info.get('email', '?')} "
                f"(org: {auth.info.get('orgName', '?')}, plan: {auth.info.get('subscriptionType', '?')})"
            )
        else:
            print(f"  claude auth:   {auth.raw}")

    target = config.get("relay", {}).get("target_tmux_session")
    if target:
        health = claude_status.tmux_session_health(target)
        if not health.exists:
            print(f"  tmux '{target}':   OFFLINE")
        else:
            state_label = "ONLINE" if health.has_live_claude_pane else "STALE"
            print(f"  tmux '{target}':   {state_label} (pane: {health.panes})")

    print()
    print(f"PROBE  ({config['probe']})")
    probe = importlib.import_module(config["probe"])
    st = state_mod.load_state(home, probe.default_state())
    now = datetime.now(timezone.utc)
    try:
        data = probe.gather(config.get("probe_config", {}))
        # Pass a shallow copy - status must never persist a side effect,
        # even for probes whose prepare_state() mutates the state dict
        # in place (e.g. the quota policy's daily-cap baseline).
        derived = probe.prepare_state(dict(st), data, now)
        decision = probe.decide(data, derived, now)
        print(f"  decision:      {decision.reason}")
        print(f"  would relay:   {'yes' if decision.notify else 'no'}")
    except Exception as e:
        print(f"  gather failed: {e}")

    log_path = home / "log.txt"
    if log_path.exists():
        lines = log_path.read_text().splitlines()[-5:]
        if lines:
            print()
            print("RECENT LOG")
            for line in lines:
                print(f"  {line}")

    return 0


def cmd_fleet_status(args: argparse.Namespace) -> int:
    fleet_config = load_config(args.fleet_config)
    nodes = fleet_config.get("nodes", [])
    if not nodes:
        print("No nodes configured in this fleet file.")
        return 1

    print(f"FLEET STATUS  ({len(nodes)} node(s))")
    print()
    for entry in nodes:
        name = entry.get("name", entry["config"])
        try:
            config = load_config(Path(entry["config"]))
        except Exception as e:
            print(f"{name}")
            print(f"  error:         failed to load config - {e}")
            print()
            continue

        summary = fleet_status.summarize_node(name, config)
        print(f"{name}")
        if summary.error:
            print(f"  error:         {summary.error}")
        else:
            print(f"  decision:      {summary.decision_reason}")
            print(f"  would relay:   {'yes' if summary.would_relay else 'no'}")
        print(f"  last relay:    {summary.last_relay}")
        print(f"  cooldown:      {'active' if summary.cooldown_active else 'clear'}")
        if summary.tmux_online is not None:
            print(f"  tmux pane:     {'online' if summary.tmux_online else 'stale/offline'}")
        print()

    print(
        "Note: tmux pane checks only work for nodes local to this host. For "
        "nodes on other sites, cross-check node names against a live "
        "ListAgents call from a Claude Code session for real liveness."
    )
    return 0


def _crontab_has_entry(config_path: str) -> bool:
    # Match on the resolved absolute path only - a bare-filename fallback is
    # too weak once more than one node uses the conventional "config.json"
    # name in different home dirs (which every example in this project does).
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    return str(Path(config_path).expanduser().resolve()) in result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fleetbroker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run a single probe check")
    p_run.add_argument("config", type=Path)
    p_run.add_argument("--dry-run", action="store_true", help="log what would be relayed, don't call claude")
    p_run.set_defaults(func=cmd_run)

    p_doctor = sub.add_parser("doctor", help="verify a node's setup without spending quota")
    p_doctor.add_argument("config", type=Path)
    p_doctor.set_defaults(func=cmd_doctor)

    p_status = sub.add_parser("status", help="show this node's current state without spending quota")
    p_status.add_argument("config", type=Path)
    p_status.set_defaults(func=cmd_status)

    p_fleet_status = sub.add_parser(
        "fleet-status", help="one-shot status overview across this host's configured probe homes"
    )
    p_fleet_status.add_argument("fleet_config", type=Path)
    p_fleet_status.set_defaults(func=cmd_fleet_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
