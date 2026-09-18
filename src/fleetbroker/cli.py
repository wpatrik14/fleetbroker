import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import runner
from . import state as state_mod
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

    claude_bin = shutil.which("claude")
    check("claude on PATH", claude_bin is not None, claude_bin or "not found")

    if claude_bin:
        result = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=15)
        check("claude auth status", result.returncode == 0, result.stdout.strip() or result.stderr.strip())

    target = config.get("relay", {}).get("target_tmux_session")
    if target:
        has_session = subprocess.run(
            ["tmux", "has-session", "-t", target], capture_output=True
        ).returncode == 0
        check(f"tmux session '{target}' exists", has_session)
        if has_session:
            panes = subprocess.run(
                ["tmux", "list-panes", "-t", target, "-F", "#{pane_current_command}"],
                capture_output=True, text=True,
            ).stdout.split()
            check(f"tmux session '{target}' has a live claude pane", "claude" in panes, str(panes))

    home = Path(config["home"]).expanduser()
    check(f"home dir '{home}' writable", os.access(home, os.W_OK) if home.exists() else True)

    check("config has 'probe' key", "probe" in config)
    check("config has 'relay' key", "relay" in config)

    check(
        f"crontab has an entry for this config",
        _crontab_has_entry(str(args.config)),
    )

    print()
    print("Overall: " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    home = Path(config["home"]).expanduser()

    print(f"NODE  ({config.get('name', str(args.config))})")

    claude_bin = shutil.which("claude")
    if claude_bin is None:
        print("  claude auth:   claude not found on PATH")
    else:
        result = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=15)
        try:
            info = json.loads(result.stdout)
            print(
                f"  claude auth:   {info.get('email', '?')} "
                f"(org: {info.get('orgName', '?')}, plan: {info.get('subscriptionType', '?')})"
            )
        except (json.JSONDecodeError, ValueError):
            print(f"  claude auth:   {result.stdout.strip() or result.stderr.strip()}")

    target = config.get("relay", {}).get("target_tmux_session")
    if target:
        has_session = subprocess.run(["tmux", "has-session", "-t", target], capture_output=True).returncode == 0
        if not has_session:
            print(f"  tmux '{target}':   OFFLINE")
        else:
            panes = subprocess.run(
                ["tmux", "list-panes", "-t", target, "-F", "#{pane_current_command}"],
                capture_output=True, text=True,
            ).stdout.split()
            alive = "claude" in panes
            print(f"  tmux '{target}':   {'ONLINE' if alive else 'STALE'} (pane: {panes})")

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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
