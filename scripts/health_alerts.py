#!/usr/bin/env python3
"""
health_alerts.py — Phase 6: Health alert detection and escalation system.

Detects warning conditions from logged data and generates alerts:
- Low calorie streak (3+ consecutive days)
- Rapid weight loss (>1.5kg/week)
- Protein deficiency (<0.8g/kg for 3+ days)
- Missing tracking (5+ days with no food logs)
- Plateaus (no weight change for 3+ weeks on weight loss plan)
- Binge days (>50% over calorie target with sudden weight rebound)

Usage (CLI):
    python3 scripts/health_alerts.py check
    python3 scripts/health_alerts.py check --date 2026-05-23
    python3 scripts/health_alerts.py ack --id <alert_id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager

DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()

# ─────────────────────────────────────────────────────────────
# Alert types and severities
# ─────────────────────────────────────────────────────────────

ALERT_TYPES = {
    "low_calorie_streak": {
        "description": "連續熱量過低",
        "severity": "warning",
        "detail": "連續 {days} 天熱量攝取低於安全下限（{floor} kcal/天）",
    },
    "rapid_weight_loss": {
        "description": "體重下降過快",
        "severity": "critical",
        "detail": "一週內體重下降 {delta}kg，超過安全上限 1.5kg/週",
    },
    "protein_deficiency": {
        "description": "蛋白質長期不足",
        "severity": "warning",
        "detail": "連續 {days} 天蛋白質攝取低於 0.8g/kg（{floor}g/天）",
    },
    "missing_logs": {
        "description": "長期未記錄飲食",
        "severity": "warning",
        "detail": "已連續 {days} 天未記錄飲食資料",
    },
    "plateau": {
        "description": "體重停滯",
        "severity": "info",
        "detail": "過去 {weeks} 週體重無明顯變化（變化 < 0.3kg），可能遇到停滯期",
    },
    "binge_day": {
        "description": "暴食警示",
        "severity": "warning",
        "detail": "{date}: 熱量攝取 {calories} kcal，超過目標 {target} kcal 的 {pct}%",
    },
    "excessive_exercise": {
        "description": "運動過量",
        "severity": "info",
        "detail": "當日運動消耗 {cal} kcal，超過 {threshold} kcal 安全上限",
    },
}

# Safety thresholds
SAFE_CALORIE_FLOOR = {"M": 1500, "F": 1200, "X": 1350}
MIN_PROTEIN_G_PER_KG = 0.8  # g/kg body weight
MAX_WEEKLY_WEIGHT_LOSS_KG = 1.5
MAX_EXERCISE_DAILY_KCAL = 800
BINGE_THRESHOLD_PCT = 0.50  # 50% over target
PLATEAU_MIN_CHANGE_KG = 0.3
PLATEAU_MIN_WEEKS = 3
MISSING_LOG_DAYS = 5
LOW_CALORIE_STREAK_DAYS = 3
PROTEIN_DEFICIENCY_DAYS = 3


@dataclass
class HealthAlert:
    user_id: str
    alert_type: str
    severity: str
    message: str
    alert_date: str
    acknowledged: bool = False
    alert_id: str = ""


# ─────────────────────────────────────────────────────────────
# Detection logic
# ─────────────────────────────────────────────────────────────

def _get_user_gender_and_weight(
    db: DBManager, user_id: str
) -> tuple[str, float]:
    """Get user's gender and current weight."""
    # Get gender from users table
    user = db.fetchone("SELECT gender, height_cm FROM users WHERE user_id = ?", (user_id,))

    gender = "X"
    if user and user["gender"]:
        gender = user["gender"].upper()

    # Get latest weight
    weight_row = db.fetchone(
        """SELECT weight_kg FROM weight_logs
           WHERE user_id = ? ORDER BY log_date DESC LIMIT 1""",
        (user_id,),
    )
    if weight_row and weight_row["weight_kg"]:
        weight = float(weight_row["weight_kg"])
    else:
        # Fallback to plan start weight
        plan = db.fetchone(
            """SELECT start_weight_kg FROM weight_plans
               WHERE user_id = ? AND is_active = 1 LIMIT 1""",
            (user_id,),
        )
        weight = float(plan["start_weight_kg"]) if plan else 0.0

    return gender, weight


def _already_alerted(
    db: DBManager, user_id: str, alert_type: str, since: str
) -> bool:
    """Check if an alert of this type was already raised recently."""
    row = db.fetchone(
        """SELECT COUNT(*) AS cnt FROM health_alerts
           WHERE user_id = ? AND alert_type = ? AND created_at >= ?""",
        (user_id, alert_type, since),
    )
    return (row and row["cnt"] > 0) if row else False


def _persist_alert(db: DBManager, alert: HealthAlert) -> str:
    """Persist alert to DB. Returns alert_id."""
    db.execute(
        """INSERT INTO health_alerts (user_id, alert_type, severity, message, acknowledged)
           VALUES (?, ?, ?, ?, ?)""",
        (alert.user_id, alert.alert_type, alert.severity, alert.message,
         1 if alert.acknowledged else 0),
    )
    # Get back the ID
    row = db.fetchone(
        "SELECT alert_id FROM health_alerts WHERE rowid = last_insert_rowid()"
    )
    return row["alert_id"] if row else ""


def check_low_calorie_streak(
    db: DBManager, user_id: str, target_date: str
) -> Optional[HealthAlert]:
    """Check for 3+ consecutive days below safe calorie floor."""
    gender, _ = _get_user_gender_and_weight(db, user_id)
    floor = SAFE_CALORIE_FLOOR.get(gender, 1350)

    # Get last N days of summary data
    cutoff = (date.fromisoformat(target_date) - timedelta(days=LOW_CALORIE_STREAK_DAYS)).isoformat()
    rows = db.fetchall(
        """SELECT summary_date, total_calories FROM daily_summaries
           WHERE user_id = ? AND summary_date >= ? AND summary_date < ?
           ORDER BY summary_date DESC LIMIT ?""",
        (user_id, cutoff, target_date, LOW_CALORIE_STREAK_DAYS),
    )

    if len(rows) < LOW_CALORIE_STREAK_DAYS:
        return None

    streak = 0
    for r in rows:
        cal = float(r["total_calories"]) if r["total_calories"] else 0
        if 0 < cal < floor:
            streak += 1
        else:
            break

    if streak >= LOW_CALORIE_STREAK_DAYS:
        msg = ALERT_TYPES["low_calorie_streak"]["detail"].format(
            days=streak, floor=floor
        )
        return HealthAlert(
            user_id=user_id,
            alert_type="low_calorie_streak",
            severity="warning",
            message=msg,
            alert_date=target_date,
        )

    return None


def check_rapid_weight_loss(
    db: DBManager, user_id: str, target_date: str
) -> Optional[HealthAlert]:
    """Check for >1.5kg weight loss in one week."""
    today = date.fromisoformat(target_date)
    week_ago = (today - timedelta(days=7)).isoformat()

    current = db.fetchone(
        """SELECT weight_kg, log_date FROM weight_logs
           WHERE user_id = ? AND log_date <= ?
           ORDER BY log_date DESC LIMIT 1""",
        (user_id, target_date),
    )
    previous = db.fetchone(
        """SELECT weight_kg FROM weight_logs
           WHERE user_id = ? AND log_date <= ?
           ORDER BY log_date DESC LIMIT 1""",
        (user_id, week_ago),
    )

    if not current or not previous:
        return None

    delta = float(previous["weight_kg"]) - float(current["weight_kg"])
    if delta > MAX_WEEKLY_WEIGHT_LOSS_KG:
        msg = ALERT_TYPES["rapid_weight_loss"]["detail"].format(delta=round(delta, 1))
        return HealthAlert(
            user_id=user_id,
            alert_type="rapid_weight_loss",
            severity="critical",
            message=msg,
            alert_date=target_date,
        )

    return None


def check_protein_deficiency(
    db: DBManager, user_id: str, target_date: str
) -> Optional[HealthAlert]:
    """Check for 3+ consecutive days of protein intake < 0.8g/kg."""
    _, weight = _get_user_gender_and_weight(db, user_id)
    if weight <= 0:
        return None

    min_protein = weight * MIN_PROTEIN_G_PER_KG

    cutoff = (date.fromisoformat(target_date) - timedelta(days=PROTEIN_DEFICIENCY_DAYS + 1)).isoformat()
    rows = db.fetchall(
        """SELECT summary_date, total_protein_g FROM daily_summaries
           WHERE user_id = ? AND summary_date >= ?
           ORDER BY summary_date DESC LIMIT ?""",
        (user_id, cutoff, PROTEIN_DEFICIENCY_DAYS + 1),
    )

    if len(rows) < PROTEIN_DEFICIENCY_DAYS:
        return None

    deficient = 0
    for r in rows[:PROTEIN_DEFICIENCY_DAYS]:
        prot = float(r["total_protein_g"]) if r["total_protein_g"] else 0
        if 0 < prot < min_protein:
            deficient += 1
        else:
            break

    if deficient >= PROTEIN_DEFICIENCY_DAYS:
        msg = ALERT_TYPES["protein_deficiency"]["detail"].format(
            days=deficient, floor=round(min_protein, 1)
        )
        return HealthAlert(
            user_id=user_id,
            alert_type="protein_deficiency",
            severity="warning",
            message=msg,
            alert_date=target_date,
        )

    return None


def check_missing_logs(
    db: DBManager, user_id: str, target_date: str
) -> Optional[HealthAlert]:
    """Check for 5+ consecutive days with no food logs."""
    today = date.fromisoformat(target_date)

    # Find the very last date with any food logs
    row = db.fetchone(
        """SELECT MAX(DATE(log_datetime)) AS last_date FROM food_logs
           WHERE user_id = ?""",
        (user_id,),
    )
    if row and row["last_date"]:
        last_date = row["last_date"]
    else:
        row = db.fetchone(
            """SELECT MAX(summary_date) AS last_date FROM daily_summaries
               WHERE user_id = ?""",
            (user_id,),
        )
        last_date = row["last_date"] if row and row["last_date"] else None

    if last_date is None:
        # No logs at all — only alert if user has had a plan for 5+ days
        plan = db.fetchone(
            "SELECT created_at FROM weight_plans WHERE user_id = ? LIMIT 1",
            (user_id,),
        )
        if plan and plan["created_at"]:
            plan_date = date.fromisoformat(str(plan["created_at"])[:10])
            days_since_plan = (today - plan_date).days
            if days_since_plan >= MISSING_LOG_DAYS:
                msg = ALERT_TYPES["missing_logs"]["detail"].format(
                    days=days_since_plan
                )
                return HealthAlert(
                    user_id=user_id,
                    alert_type="missing_logs",
                    severity="warning",
                    message=msg,
                    alert_date=target_date,
                )
        return None

    last_date_obj = date.fromisoformat(str(last_date)[:10]) if isinstance(last_date, str) else date.fromisoformat(str(last_date)[:10])
    gap = (today - last_date_obj).days
    if gap >= MISSING_LOG_DAYS:
        msg = ALERT_TYPES["missing_logs"]["detail"].format(days=gap)
        return HealthAlert(
            user_id=user_id,
            alert_type="missing_logs",
            severity="warning",
            message=msg,
            alert_date=target_date,
        )

    return None


def check_plateau(
    db: DBManager, user_id: str, target_date: str
) -> Optional[HealthAlert]:
    """Check for weight plateau (no change for 3+ weeks on a cut plan)."""
    # Only check for loss plans
    plan = db.fetchone(
        "SELECT goal_type FROM weight_plans WHERE user_id = ? AND is_active = 1 LIMIT 1",
        (user_id,),
    )
    if not plan or plan["goal_type"] != "loss":
        return None

    today = date.fromisoformat(target_date)
    weeks_ago = (today - timedelta(weeks=PLATEAU_MIN_WEEKS)).isoformat()

    weights = db.fetchall(
        """SELECT log_date, weight_kg FROM weight_logs
           WHERE user_id = ? AND log_date >= ?
           ORDER BY log_date ASC""",
        (user_id, weeks_ago),
    )

    if len(weights) < 2:
        return None

    first_w = float(weights[0]["weight_kg"])
    last_w = float(weights[-1]["weight_kg"])
    change = abs(last_w - first_w)

    if change < PLATEAU_MIN_CHANGE_KG and len(weights) >= 2:
        weeks = PLATEAU_MIN_WEEKS
        msg = ALERT_TYPES["plateau"]["detail"].format(weeks=weeks)
        return HealthAlert(
            user_id=user_id,
            alert_type="plateau",
            severity="info",
            message=msg,
            alert_date=target_date,
        )

    return None


def check_binge_day(
    db: DBManager, user_id: str, target_date: str
) -> Optional[HealthAlert]:
    """Check for single-day binge (50%+ over calorie target)."""
    summary = db.fetchone(
        """SELECT total_calories, calorie_target FROM daily_summaries
           WHERE user_id = ? AND summary_date = ?""",
        (user_id, target_date),
    )

    if not summary or not summary["total_calories"] or not summary["calorie_target"]:
        return None

    calories = float(summary["total_calories"])
    target = int(summary["calorie_target"])

    if target <= 0:
        return None

    pct = (calories - target) / target
    if pct > BINGE_THRESHOLD_PCT:
        msg = ALERT_TYPES["binge_day"]["detail"].format(
            date=target_date, calories=int(calories),
            target=target,
            pct=round(pct * 100)
        )
        return HealthAlert(
            user_id=user_id,
            alert_type="binge_day",
            severity="warning",
            message=msg,
            alert_date=target_date,
        )

    return None


def check_excessive_exercise(
    db: DBManager, user_id: str, target_date: str
) -> Optional[HealthAlert]:
    """Check for excessive exercise calories in one day."""
    row = db.fetchone(
        """SELECT COALESCE(SUM(calories_burned), 0) AS total
           FROM exercise_logs
           WHERE user_id = ? AND log_date = ?""",
        (user_id, target_date),
    )

    if not row:
        return None

    total = float(row["total"])
    if total > MAX_EXERCISE_DAILY_KCAL:
        msg = ALERT_TYPES["excessive_exercise"]["detail"].format(
            cal=int(total), threshold=MAX_EXERCISE_DAILY_KCAL
        )
        return HealthAlert(
            user_id=user_id,
            alert_type="excessive_exercise",
            severity="info",
            message=msg,
            alert_date=target_date,
        )

    return None


# ─────────────────────────────────────────────────────────────
# Main check entry point
# ─────────────────────────────────────────────────────────────

def run_all_checks(
    db: DBManager, user_id: str, target_date: str | None = None
) -> list[HealthAlert]:
    """Run all health checks and return new alerts (deduplicated)."""
    target_date = target_date or str(date.today())

    # Dedup window: don't re-alert for same type within 3 days
    dedup_cutoff = (date.fromisoformat(target_date) - timedelta(days=3)).isoformat()

    checks = [
        ("low_calorie_streak", check_low_calorie_streak),
        ("rapid_weight_loss", check_rapid_weight_loss),
        ("protein_deficiency", check_protein_deficiency),
        ("missing_logs", check_missing_logs),
        ("plateau", check_plateau),
        ("binge_day", check_binge_day),
        ("excessive_exercise", check_excessive_exercise),
    ]

    alerts = []
    for alert_type, check_fn in checks:
        if _already_alerted(db, user_id, alert_type, dedup_cutoff):
            continue
        alert = check_fn(db, user_id, target_date)
        if alert is not None:
            alert.alert_id = _persist_alert(db, alert)
            alerts.append(alert)

    return alerts


# ─────────────────────────────────────────────────────────────
# Queries
# ─────────────────────────────────────────────────────────────

def get_active_alerts(
    db: DBManager, user_id: str, include_acked: bool = False
) -> list[dict]:
    """Get unacknowledged (or all) alerts for a user."""
    if include_acked:
        rows = db.fetchall(
            """SELECT alert_id, alert_type, severity, message, acknowledged, created_at
               FROM health_alerts WHERE user_id = ? ORDER BY created_at DESC LIMIT 50""",
            (user_id,),
        )
    else:
        rows = db.fetchall(
            """SELECT alert_id, alert_type, severity, message, acknowledged, created_at
               FROM health_alerts WHERE user_id = ? AND acknowledged = 0
               ORDER BY created_at DESC LIMIT 50""",
            (user_id,),
        )
    return [dict(r) for r in rows]


def acknowledge_alert(db: DBManager, alert_id: str) -> bool:
    """Mark an alert as acknowledged. Returns True if a row was updated."""
    db.execute(
        "UPDATE health_alerts SET acknowledged = 1 WHERE alert_id = ?",
        (alert_id,),
    )
    # Check if row was affected
    row = db.fetchone(
        "SELECT alert_id FROM health_alerts WHERE alert_id = ? AND acknowledged = 1",
        (alert_id,),
    )
    return row is not None


# ─────────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────────

_SEVERITY_EMOJI = {
    "info": "ℹ️",
    "warning": "⚠️",
    "critical": "🚨",
}


def format_alerts(alerts: list[dict]) -> str:
    """Format a list of alerts for display."""
    if not alerts:
        return "✅ 無健康警示"

    lines = []
    for a in alerts:
        emoji = _SEVERITY_EMOJI.get(a["severity"], "📌")
        ack = " ✅已讀" if a.get("acknowledged") else ""
        lines.append(f"{emoji} [{a['alert_type']}]{ack}")
        lines.append(f"   {a['message']}")
        lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def _get_db_and_user():
    db_path = Path(os.environ.get("HEALTHFIT_DB_PATH", DEFAULT_DB_PATH))
    if not db_path.exists():
        print("No database found.", file=sys.stderr)
        sys.exit(1)
    db = DBManager(db=str(db_path))

    profile_path = Path(os.environ.get("HEALTHFIT_PROFILE", Path("~/.healthfit/profile.json").expanduser()))
    if not profile_path.exists():
        print("No profile found.", file=sys.stderr)
        sys.exit(1)
    with open(profile_path) as f:
        profile = json.load(f)
    user_id = profile.get("user_id") or profile.get("user", {}).get("user_id", "")
    return db, user_id


def cmd_check(args: argparse.Namespace) -> None:
    db, user_id = _get_db_and_user()
    target_date = args.date or str(date.today())
    alerts = run_all_checks(db, user_id, target_date)

    if alerts:
        dict_alerts = [
            {"alert_type": a.alert_type, "severity": a.severity,
             "message": a.message, "acknowledged": a.acknowledged}
            for a in alerts
        ]
    else:
        dict_alerts = []

    print(format_alerts(dict_alerts))

    if args.json:
        print(json.dumps(dict_alerts, ensure_ascii=False, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    db, user_id = _get_db_and_user()
    alerts = get_active_alerts(db, user_id, include_acked=args.all)
    print(format_alerts(alerts))


def cmd_ack(args: argparse.Namespace) -> None:
    db, _ = _get_db_and_user()
    ok = acknowledge_alert(db, args.id)
    if ok:
        print(f"✅ 已確認警示 {args.id}")
    else:
        print(f"❌ 找不到警示 {args.id}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="health_alerts.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="Run all health checks")
    p_check.add_argument("--date", help="Target date (default today)")
    p_check.add_argument("--json", action="store_true", help="Output JSON")

    p_list = sub.add_parser("list", help="List active (unacknowledged) alerts")
    p_list.add_argument("--all", action="store_true", help="Include acknowledged")

    p_ack = sub.add_parser("ack", help="Acknowledge an alert")
    p_ack.add_argument("--id", required=True, help="Alert ID")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "ack":
        cmd_ack(args)


if __name__ == "__main__":
    main()