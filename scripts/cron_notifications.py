#!/usr/bin/env python3
"""
cron_notifications.py — Phase 6: Cron-based notification dispatcher.

Triggers daily and weekly reports and delivers them via notification_scheduler.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager
from report_generator import generate_daily_report, generate_weekly_report
from notification_scheduler import deliver_report

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

# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="HealthFit Cron Notification Dispatcher")
    parser.add_argument("--user-id", required=True, help="User ID to notify")
    parser.add_argument("--type", choices=["daily", "weekly"], required=True, help="Report type")
    parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    args = parser.parse_args()
    db = DBManager(Path(args.db_path))
    
    if args.type == "daily":
        run_daily_notification(args.user_id, db)
    elif args.type == "weekly":
        run_weekly_notification(args.user_id, db)

if __name__ == "__main__":
    main()
