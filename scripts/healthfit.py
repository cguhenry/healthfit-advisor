#!/usr/bin/env python3
"""
healthfit.py - Unified CLI entry point for HealthFit Advisor.

Keeps the existing per-phase scripts intact while exposing one stable
operator-facing command surface for local CLI use and agent manifests.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent


def _run_script(script_name: str, forwarded_args: Sequence[str]) -> int:
    script_path = SCRIPT_DIR / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"missing target script: {script_path}")
    cmd = [sys.executable, str(script_path), *forwarded_args]
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="healthfit.py",
        description="Unified CLI for HealthFit Advisor workflows.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_intake = sub.add_parser("intake", help="Run the Phase 1 intake flow.")
    p_intake.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to intake_flow.py")

    p_log = sub.add_parser("log", help="Logging workflows.")
    log_sub = p_log.add_subparsers(dest="log_command", required=True)
    p_log_meal = log_sub.add_parser("meal", help="Log a meal analysis payload.")
    p_log_meal.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to calorie_tracker.py log")

    p_report = sub.add_parser("report", help="Generate reports.")
    report_sub = p_report.add_subparsers(dest="report_command", required=True)
    p_report_daily = report_sub.add_parser("daily", help="Generate a daily report.")
    p_report_daily.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to report_generator.py daily")
    p_report_weekly = report_sub.add_parser("weekly", help="Generate a weekly report.")
    p_report_weekly.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to report_generator.py weekly")

    p_plan = sub.add_parser("plan", help="Generate a weekly meal plan.")
    p_plan.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to meal_planner.py plan")

    p_gi = sub.add_parser("gi", help="GI lookup and guidance.")
    gi_sub = p_gi.add_subparsers(dest="gi_command", required=True)
    p_gi_classify = gi_sub.add_parser("classify", help="Classify a food's GI tier.")
    p_gi_classify.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to gi_guide.py classify")
    p_gi_alias = gi_sub.add_parser("lookup", help="Alias of gi classify.")
    p_gi_alias.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to gi_guide.py classify")
    p_gi_swap = gi_sub.add_parser("swap", help="Recommend a lower-GI alternative.")
    p_gi_swap.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to gi_guide.py swap")
    p_gi_strategy = gi_sub.add_parser("strategy", help="Show GI eating strategy.")
    p_gi_strategy.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to gi_guide.py strategy")

    p_menu = sub.add_parser("menu", help="Get menu suggestions from menu_advisor.py.")
    p_menu.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to menu_advisor.py")

    p_alert = sub.add_parser("alert", help="Health alert workflows.")
    alert_sub = p_alert.add_subparsers(dest="alert_command", required=True)
    for name in ("check", "list", "ack"):
        p_alert_sub = alert_sub.add_parser(name, help=f"Forward to health_alerts.py {name}")
        p_alert_sub.add_argument("args", nargs=argparse.REMAINDER, help=f"Arguments forwarded to health_alerts.py {name}")

    p_notify = sub.add_parser("notify", help="Notification workflows.")
    notify_sub = p_notify.add_subparsers(dest="notify_command", required=True)
    for name in ("daily", "weekly", "test", "setup-cron"):
        p_notify_sub = notify_sub.add_parser(name, help=f"Forward to notification_scheduler.py {name}")
        p_notify_sub.add_argument("args", nargs=argparse.REMAINDER, help=f"Arguments forwarded to notification_scheduler.py {name}")

    return parser


def dispatch(argv: Sequence[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 2
    if argv[0] in {"-h", "--help"}:
        build_parser().print_help()
        return 0

    command = argv[0]
    rest = argv[1:]

    if command == "intake":
        return _run_script("intake_flow.py", rest)
    if command == "log":
        if not rest:
            raise ValueError("log requires a subcommand")
        if rest[0] == "meal":
            return _run_script("calorie_tracker.py", ["log", *rest[1:]])
        raise ValueError(f"unsupported log subcommand: {rest[0]}")
    if command == "report":
        if not rest:
            raise ValueError("report requires a subcommand")
        if rest[0] in {"daily", "weekly"}:
            return _run_script("report_generator.py", [rest[0], *rest[1:]])
        raise ValueError(f"unsupported report subcommand: {rest[0]}")
    if command == "plan":
        return _run_script("meal_planner.py", ["plan", *rest])
    if command == "gi":
        if not rest:
            raise ValueError("gi requires a subcommand")
        gi_command = "classify" if rest[0] in {"classify", "lookup"} else rest[0]
        if gi_command not in {"classify", "swap", "strategy", "list"}:
            raise ValueError(f"unsupported gi subcommand: {rest[0]}")
        return _run_script("gi_guide.py", [gi_command, *rest[1:]])
    if command == "menu":
        return _run_script("menu_advisor.py", rest)
    if command == "alert":
        if not rest:
            raise ValueError("alert requires a subcommand")
        if rest[0] not in {"check", "list", "ack"}:
            raise ValueError(f"unsupported alert subcommand: {rest[0]}")
        return _run_script("health_alerts.py", [rest[0], *rest[1:]])
    if command == "notify":
        if not rest:
            raise ValueError("notify requires a subcommand")
        if rest[0] not in {"daily", "weekly", "test", "setup-cron"}:
            raise ValueError(f"unsupported notify subcommand: {rest[0]}")
        return _run_script("notification_scheduler.py", [rest[0], *rest[1:]])

    raise ValueError(f"unsupported command path: {command}")


def main() -> None:
    raise SystemExit(dispatch())


if __name__ == "__main__":
    main()
