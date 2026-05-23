#!/usr/bin/env python3
"""
notification_scheduler.py — Phase 6: Cron-based daily summary scheduler.

Generates and delivers daily/weekly health reports on a schedule.
Designed to run via cron or APScheduler.

Usage (standalone):
    python3 scripts/notification_scheduler.py daily
    python3 scripts/notification_scheduler.py weekly
    python3 scripts/notification_scheduler.py setup-cron

Environment variables:
    HEALTHFIT_DB_PATH   — SQLite DB path (default: ~/.healthfit/healthfit.db)
    HEALTHFIT_PROFILE   — Profile JSON path (default: ~/.healthfit/profile.json)
    HEALTHFIT_DRY_RUN   — If set, print report instead of sending
    HEALTHFIT_CHANNELS  — Comma-separated channels: discord,line (default: discord)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Add scripts dir to path for imports
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.db_manager import DBManager
from scripts.report_generator import generate_daily_report, generate_weekly_report
from scripts.scoring_engine import run_daily_scoring
from scripts.calorie_tracker import get_calorie_progress, get_history_comparison


DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()
DEFAULT_PROFILE_PATH = Path("~/.healthfit/profile.json").expanduser()
CRON_LINE = (
    "# HealthFit AI — daily report at 22:30\n"
    "30 22 * * * "
    "python3 /home/node/.openclaw/workspace/skills/healthfit-advisor/scripts/notification_scheduler.py daily\n"
    "# HealthFit AI — weekly report on Sunday at 21:00\n"
    "0 21 * * 0 "
    "python3 /home/node/.openclaw/workspace/skills/healthfit-advisor/scripts/notification_scheduler.py weekly\n"
)


def load_profile(profile_path: Path) -> dict:
    """Load the local single-user profile."""
    if not profile_path.exists():
        raise RuntimeError(
            f"Profile not found at {profile_path}. "
            "Please run the Phase 1 intake flow first."
        )
    with open(profile_path) as f:
        return json.load(f)


def get_db(db_path: Path) -> DBManager:
    """Connect to the SQLite database."""
    return DBManager(db=str(db_path))


def get_user_id(profile: dict) -> str:
    """Extract user_id from profile."""
    return profile.get("user_id") or profile.get("user", {}).get("user_id", "")


# ─────────────────────────────────────────────────────────────
# Report generation helpers
# ─────────────────────────────────────────────────────────────

def build_daily_payload(user_id: str, db: DBManager, target_date: date | None = None) -> dict:
    """
    Run daily scoring and generate the daily report text.
    Returns a dict with keys: report_text, score, grade, date.
    """
    target_date = target_date or date.today()

    # Run scoring pipeline to ensure fresh data
    try:
        run_daily_scoring(db, user_id, target_date)
    except Exception as e:
        print(f"[notification_scheduler] scoring warning: {e}", file=sys.stderr)

    # Generate the human-readable report
    report = generate_daily_report(db, user_id, target_date)
    return {
        "report_text": report,
        "date": str(target_date),
        "user_id": user_id,
    }


def build_weekly_payload(
    user_id: str, db: DBManager, week_start: date | None = None
) -> dict:
    """
    Generate the weekly report text.
    week_start defaults to the Monday of the current week.
    """
    if week_start is None:
        # Find Monday of this week
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

    report = generate_weekly_report(db, user_id, week_start)
    return {
        "report_text": report,
        "week_start": str(week_start),
        "user_id": user_id,
    }


# ─────────────────────────────────────────────────────────────
# Delivery (stub — wire to OpenClaw message system)
# ─────────────────────────────────────────────────────────────

def deliver_report(payload: dict, channels: list[str]) -> None:
    """
    Deliver a report payload to the specified channels.
    Currently supports: discord, line, print (stdout).
    Wire this to OpenClaw's message system for production use.
    """
    text = payload["report_text"]
    dry_run = os.environ.get("HEALTHFIT_DRY_RUN", "").lower() in ("1", "true", "yes")

    if "print" in channels or dry_run:
        print("=" * 60, flush=True)
        print(text, flush=True)
        print("=" * 60, flush=True)

    if "discord" in channels and not dry_run:
        _deliver_discord(text)

    if "line" in channels and not dry_run:
        _deliver_line(text)


def _deliver_discord(text: str, webhook_url: str | None = None) -> None:
    """Send report to Discord via webhook.

    Falls back to printing when HEALTHFIT_DRY_RUN is set or
    no DISCORD_WEBHOOK_URL is configured.
    """
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(
            "[discord] No DISCORD_WEBHOOK_URL set. "
            f"Would send report ({len(text)} chars)",
            flush=True,
        )
        return

    try:
        import requests
        payload = {"content": text[:2000]}  # Discord 2000-char limit per message
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"[discord] Sent report ({len(text)} chars)", flush=True)
    except Exception as e:
        print(f"[discord] Failed to send: {e}", file=sys.stderr, flush=True)


def _deliver_line(text: str, channel_token: str | None = None) -> None:
    """Send report to LINE via LINE Messaging API.

    Falls back to printing when HEALTHFIT_DRY_RUN is set or
    no LINE_CHANNEL_ACCESS_TOKEN is configured.
    """
    channel_token = channel_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    target = os.environ.get("LINE_REPORT_TARGET")
    if not channel_token or not target:
        print(
            "[line] LINE_CHANNEL_ACCESS_TOKEN or LINE_REPORT_TARGET not set. "
            f"Would send report ({len(text)} chars)",
            flush=True,
        )
        return

    try:
        import requests
        headers = {
            "Authorization": f"Bearer {channel_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "to": target,
            "messages": [{"type": "text", "text": text[:5000]}],
        }
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers=headers, json=payload, timeout=10,
        )
        resp.raise_for_status()
        print(f"[line] Sent report ({len(text)} chars)", flush=True)
    except Exception as e:
        print(f"[line] Failed to send: {e}", file=sys.stderr, flush=True)


# ─────────────────────────────────────────────────────────────
# CLI entry points
# ─────────────────────────────────────────────────────────────

def cmd_daily(args: argparse.Namespace) -> None:
    db_path = Path(os.environ.get("HEALTHFIT_DB_PATH", DEFAULT_DB_PATH))
    profile_path = Path(os.environ.get("HEALTHFIT_PROFILE", DEFAULT_PROFILE_PATH))

    if not db_path.exists():
        print("No database found. Run the Phase 1 intake flow first.", file=sys.stderr)
        sys.exit(1)

    profile = load_profile(profile_path)
    user_id = get_user_id(profile)
    db = get_db(db_path)

    target = date.today()
    payload = build_daily_payload(user_id, db, target)

    channels = args.channels or os.environ.get("HEALTHFIT_CHANNELS", "print").split(",")
    deliver_report(payload, channels)

    print(f"\n[OK] Daily report generated for {payload['date']}", flush=True)


def cmd_weekly(args: argparse.Namespace) -> None:
    db_path = Path(os.environ.get("HEALTHFIT_DB_PATH", DEFAULT_DB_PATH))
    profile_path = Path(os.environ.get("HEALTHFIT_PROFILE", DEFAULT_PROFILE_PATH))

    if not db_path.exists():
        print("No database found. Run the Phase 1 intake flow first.", file=sys.stderr)
        sys.exit(1)

    profile = load_profile(profile_path)
    user_id = get_user_id(profile)
    db = get_db(db_path)

    payload = build_weekly_payload(user_id, db, week_start=None)

    channels = args.channels or os.environ.get("HEALTHFIT_CHANNELS", "print").split(",")
    deliver_report(payload, channels)

    print(f"\n[OK] Weekly report generated for week starting {payload['week_start']}", flush=True)


def cmd_setup_cron(args: argparse.Namespace) -> None:
    """Print the cron entry to stdout. User should pipe to crontab."""
    print(CRON_LINE)
    print(
        "\nTo install:\n"
        f"  python3 {__file__} setup-cron >> ~/.crontab && crontab ~/.crontab\n"
        "\nTo remove:\n"
        "  crontab -l | grep -v healthfit | crontab -\n"
    )


def cmd_test(args: argparse.Namespace) -> None:
    """Quick smoke test: run daily scoring and print the report."""
    db_path = Path(os.environ.get("HEALTHFIT_DB_PATH", DEFAULT_DB_PATH))
    profile_path = Path(os.environ.get("HEALTHFIT_PROFILE", DEFAULT_PROFILE_PATH))

    profile = load_profile(profile_path)
    user_id = get_user_id(profile)
    db = get_db(db_path)

    target = date.today()
    payload = build_daily_payload(user_id, db, target)
    print(payload["report_text"])
    print(f"\n[TEST OK] Report generated for {payload['date']}")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(prog="notification_scheduler.py")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("daily", help="Generate and deliver today's daily report") \
        .add_argument("-c", "--channels", nargs="+", help="Channels: discord line print")
    sub.add_parser("weekly", help="Generate and deliver this week's report") \
        .add_argument("-c", "--channels", nargs="+", help="Channels: discord line print")
    sub.add_parser("setup-cron", help="Print cron entry to stdout")
    sub.add_parser("test", help="Smoke test: generate and print today's report")

    args = parser.parse_args()

    if args.command == "daily":
        cmd_daily(args)
    elif args.command == "weekly":
        cmd_weekly(args)
    elif args.command == "setup-cron":
        cmd_setup_cron(args)
    elif args.command == "test":
        cmd_test(args)


if __name__ == "__main__":
    main()