#!/usr/bin/env python3
"""
cron_notifications.py — Phase 6: Cron-based notification dispatcher.

Triggers daily and weekly reports, plus Sunday morning shopping list push,
and delivers them via notification_scheduler.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager
from report_generator import generate_daily_report, generate_weekly_report
from notification_scheduler import deliver_report

# ─────────────────────────────────────────────────────────────
# Shopping push schedule constants
# ─────────────────────────────────────────────────────────────

SHOPPING_PUSH_WEEKDAY = 6    # Sunday (0=Monday)
SHOPPING_PUSH_HOUR = 10      # 10 AM


def should_push_shopping_list(now: datetime) -> bool:
    """Check whether it's Sunday at the configured push hour."""
    return now.weekday() == SHOPPING_PUSH_WEEKDAY and now.hour == SHOPPING_PUSH_HOUR


def send_notification(user_id: str, message: str, channel: str, category: str) -> None:
    """Thin wrapper around notification_scheduler.deliver_report()."""
    deliver_report(
        {"user_id": user_id, "report_text": message, "category": category},
        [channel],
    )


# ─────────────────────────────────────────────────────────────
# Notification Logic
# ─────────────────────────────────────────────────────────────

def run_daily_notification(user_id: str, db: DBManager) -> None:
    """Generate and send daily report."""
    today = date.today().isoformat()
    
    # 1. Generate Report
    try:
        report_text = generate_daily_report(db, user_id, today)
        if not report_text or "無數據" in report_text:
            print(f"ℹ️ {today}: User {user_id} has no data to report. Skipping.")
            return
    except Exception as e:
        print(f"❌ Error generating daily report for {user_id}: {e}")
        return

    # 2. Send Notification
    # In a real scenario, we would fetch the user's preferred channel from the DB
    # For now, we send to both if configured
    send_notification(
        user_id=user_id,
        message=report_text,
        channel="line",
        category="daily_report"
    )
    send_notification(
        user_id=user_id,
        message=report_text,
        channel="discord",
        category="daily_report"
    )
    print(f"✅ Daily report sent for {user_id} ({today}).")

def run_weekly_notification(user_id: str, db: DBManager) -> None:
    """Generate and send weekly report."""
    # Weekly report is usually sent on Sunday for the past 7 days
    # Week start = last Monday
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    
    try:
        report_text = generate_weekly_report(db, user_id, week_start)
        if not report_text or "無數據" in report_text:
            print(f"ℹ️ {week_start}: User {user_id} has no data for the week. Skipping.")
            return
    except Exception as e:
        print(f"❌ Error generating weekly report for {user_id}: {e}")
        return

    send_notification(
        user_id=user_id,
        message=report_text,
        channel="line",
        category="weekly_report"
    )
    send_notification(
        user_id=user_id,
        message=report_text,
        channel="discord",
        category="weekly_report"
    )
    print(f"✅ Weekly report sent for {user_id} ({week_start}).")

def run_shopping_push(user_id: str, db: DBManager, week_start_date: Optional[date] = None) -> None:
    """Generate next week's meal plan + shopping list and push to channels."""
    from shopping_push import run_weekly_shopping_push

    now = date.today()
    if week_start_date is None:
        # Next Monday
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        week_start_date = now + timedelta(days=days_until_monday)

    channels_str = os.environ.get("HEALTHFIT_CHANNELS", "discord,line")
    channels = [c.strip() for c in channels_str.split(",") if c.strip()]

    try:
        result = run_weekly_shopping_push(
            db, user_id, week_start_date, channels=channels,
        )
        print(
            f"✅ Shopping push sent for {user_id} (week {week_start_date}): "
            f"{result.get('item_count', 0)} items to {result.get('channel_count', 0)} channels"
        )
    except Exception as e:
        print(f"❌ Shopping push failed for {user_id}: {e}")

# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="HealthFit Cron Notification Dispatcher")
    parser.add_argument("--user-id", required=True, help="User ID to notify")
    parser.add_argument("--type", choices=["daily", "weekly", "shopping"], required=True, help="Report type")
    parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))
    parser.add_argument("--week-start", help="Week start date (ISO, for shopping push)")

    args = parser.parse_args()
    db = DBManager(Path(args.db_path))
    
    if args.type == "daily":
        run_daily_notification(args.user_id, db)
    elif args.type == "weekly":
        run_weekly_notification(args.user_id, db)
    elif args.type == "shopping":
        ws = date.fromisoformat(args.week_start) if args.week_start else None
        run_shopping_push(args.user_id, db, week_start_date=ws)

if __name__ == "__main__":
    main()