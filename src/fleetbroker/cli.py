import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import runner
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
