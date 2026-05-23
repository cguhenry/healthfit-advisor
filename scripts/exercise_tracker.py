#!/usr/bin/env python3
"""
exercise_tracker.py — Phase 6: Exercise logging, MET-based calorie estimation,
and dynamic daily calorie quota adjustment.

Design:
- MET-based calorie estimation using Compendium of Physical Activities values.
- Log workouts to `exercise_logs` table.
- Dynamically adjust daily calorie target via `daily_calorie_ledger`.
- Wire into scoring_engine so burned calories add to adjusted target.

Usage (CLI):
    python3 scripts/exercise_tracker.py log --type cardio --activity "慢跑" --duration 30 --intensity moderate
    python3 scripts/exercise_tracker.py log --type strength --activity "深蹲" --duration 45 --intensity vigorous
    python3 scripts/exercise_tracker.py status --date 2026-05-23
    python3 scripts/exercise_tracker.py adjust --date 2026-05-23
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ── Ensure sibling scripts are importable ───────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager

DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()

# ─────────────────────────────────────────────────────────────
# MET Values (Compendium of Physical Activities)
# ─────────────────────────────────────────────────────────────

# MET by exercise category and intensity
# Key: (activity_name_lower, intensity) → MET
_MET_TABLE: dict[tuple[str, str], float] = {
    # ── Cardio ──
    ("慢跑", "light"): 6.0,      # jogging, slow
    ("慢跑", "moderate"): 8.0,   # jogging, general
    ("慢跑", "vigorous"): 11.0,  # running, 8 km/h
    ("跑步", "light"): 7.0,
    ("跑步", "moderate"): 9.8,
    ("跑步", "vigorous"): 12.5,
    ("快走", "light"): 3.5,
    ("快走", "moderate"): 5.0,
    ("快走", "vigorous"): 7.0,
    ("走路", "light"): 2.5,
    ("走路", "moderate"): 3.5,
    ("走路", "vigorous"): 5.0,
    ("騎腳踏車", "light"): 4.0,
    ("騎腳踏車", "moderate"): 6.8,
    ("騎腳踏車", "vigorous"): 10.0,
    ("飛輪", "light"): 5.5,
    ("飛輪", "moderate"): 8.5,
    ("飛輪", "vigorous"): 12.0,
    ("游泳", "light"): 5.0,
    ("游泳", "moderate"): 7.0,
    ("游泳", "vigorous"): 10.0,
    ("跳繩", "light"): 8.0,
    ("跳繩", "moderate"): 10.0,
    ("跳繩", "vigorous"): 12.3,
    ("橢圓機", "light"): 4.5,
    ("橢圓機", "moderate"): 6.0,
    ("橢圓機", "vigorous"): 8.0,
    ("划船機", "light"): 4.8,
    ("划船機", "moderate"): 7.0,
    ("划船機", "vigorous"): 8.5,
    ("樓梯機", "light"): 5.5,
    ("樓梯機", "moderate"): 8.0,
    ("樓梯機", "vigorous"): 10.0,
    # ── HIIT ──
    ("tabata", "moderate"): 8.0,
    ("tabata", "vigorous"): 12.0,
    ("hiit", "light"): 6.5,
    ("hiit", "moderate"): 8.5,
    ("hiit", "vigorous"): 12.0,
    ("波比跳", "light"): 6.0,
    ("波比跳", "moderate"): 8.0,
    ("波比跳", "vigorous"): 12.0,
    ("間歇跑", "light"): 7.0,
    ("間歇跑", "moderate"): 10.0,
    ("間歇跑", "vigorous"): 13.5,
    # ── Strength ──
    ("重訓", "light"): 3.0,      # light weight training
    ("重訓", "moderate"): 5.0,   # general weight training
    ("重訓", "vigorous"): 6.0,   # vigorous weight training
    ("深蹲", "light"): 4.0,
    ("深蹲", "moderate"): 5.5,
    ("深蹲", "vigorous"): 8.0,
    ("硬舉", "light"): 4.5,
    ("硬舉", "moderate"): 6.0,
    ("硬舉", "vigorous"): 8.5,
    ("臥推", "light"): 3.5,
    ("臥推", "moderate"): 5.0,
    ("臥推", "vigorous"): 6.5,
    ("壺鈴", "light"): 4.0,
    ("壺鈴", "moderate"): 6.0,
    ("壺鈴", "vigorous"): 8.0,
    ("伏地挺身", "moderate"): 5.0,
    ("伏地挺身", "vigorous"): 8.0,
    ("引體向上", "moderate"): 5.0,
    ("引體向上", "vigorous"): 8.0,
    # ── Yoga / Flexibility ──
    ("瑜珈", "light"): 2.5,      # hatha yoga
    ("瑜珈", "moderate"): 4.0,   # power yoga
    ("瑜珈", "vigorous"): 6.0,
    ("皮拉提斯", "light"): 2.8,
    ("皮拉提斯", "moderate"): 4.0,
    ("皮拉提斯", "vigorous"): 5.5,
    ("伸展", "light"): 2.3,
    ("伸展", "moderate"): 3.0,
    # ── Dance / Sports ──
    ("跳舞", "light"): 3.5,
    ("跳舞", "moderate"): 5.5,
    ("跳舞", "vigorous"): 7.5,
    ("籃球", "light"): 5.0,
    ("籃球", "moderate"): 6.5,
    ("籃球", "vigorous"): 8.0,
    ("羽球", "light"): 4.0,
    ("羽球", "moderate"): 5.5,
    ("羽球", "vigorous"): 7.0,
    ("網球", "light"): 4.5,
    ("網球", "moderate"): 6.0,
    ("網球", "vigorous"): 8.0,
    ("桌球", "light"): 3.5,
    ("桌球", "moderate"): 4.0,
    ("桌球", "vigorous"): 5.5,
    # ── Other ──
    ("跳繩", "moderate"): 10.0,
    ("登山", "light"): 4.5,
    ("登山", "moderate"): 6.0,
    ("登山", "vigorous"): 8.0,
    ("體操", "light"): 3.0,
    ("體操", "moderate"): 5.0,
    ("太極拳", "light"): 3.0,
    ("太極拳", "moderate"): 4.0,
    ("氣功", "light"): 2.5,
    ("清潔", "light"): 3.0,
    ("園藝", "light"): 3.5,
}

# Intensity multiplier adjustments
INTENSITY_ALIASES = {
    "輕度": "light", "輕": "light", "低": "light",
    "中度": "moderate", "中": "moderate", "中等": "moderate",
    "高強度": "vigorous", "強": "vigorous", "高": "vigorous", "劇烈": "vigorous",
}

EXERCISE_TYPE_ALIASES = {
    "cardio": ["有氧", "跑步", "慢跑", "快走", "走路", "騎腳踏車", "飛輪", "游泳", "跳繩",
               "橢圓機", "划船機", "樓梯機", "跳舞", "籃球", "羽球", "網球", "桌球", "登山"],
    "strength": ["重訓", "深蹲", "硬舉", "臥推", "壺鈴", "伏地挺身", "引體向上"],
    "hiit": ["tabata", "hiit", "波比跳", "間歇跑", "高強度間歇"],
    "yoga": ["瑜珈", "皮拉提斯", "伸展", "太極拳", "氣功"],
}

# ─────────────────────────────────────────────────────────────
# Calorie Estimation
# ─────────────────────────────────────────────────────────────

def normalize_activity(activity: str) -> str:
    """Normalize activity name to lookup key."""
    return activity.strip()


def normalize_intensity(intensity: str) -> str:
    """Normalize intensity to one of 'light', 'moderate', 'vigorous'."""
    return INTENSITY_ALIASES.get(intensity.strip(), intensity.strip().lower())


def get_met(activity: str, intensity: str) -> Optional[float]:
    """Look up MET value. Returns None if not found."""
    key = (normalize_activity(activity), normalize_intensity(intensity))
    met = _MET_TABLE.get(key)
    if met is None:
        # Try without intensity (use moderate as default)
        for (_act, _int), _met in _MET_TABLE.items():
            if _act == key[0]:
                return _met
    return met


def estimate_calories_burned(
    weight_kg: float, met: float, duration_min: int
) -> float:
    """
    Calories = MET × weight(kg) × (duration_min / 60)

    Returns estimated kcal burned.
    """
    return round(met * weight_kg * (duration_min / 60), 1)


def classify_exercise_type(activity: str) -> str:
    """Classify an activity into exercise_type category."""
    act = activity.strip().lower()
    for etype, keywords in EXERCISE_TYPE_ALIASES.items():
        for kw in keywords:
            if kw in act:
                return etype
    return "other"


@dataclass
class ExerciseLog:
    user_id: str
    log_date: str  # YYYY-MM-DD
    exercise_type: str
    activity_name: str
    duration_min: int
    intensity: str
    calories_burned: float
    note: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Database Persistence
# ─────────────────────────────────────────────────────────────

def log_exercise(
    db: DBManager,
    user_id: str,
    log_date: str,
    exercise_type: str,
    activity_name: str,
    duration_min: int,
    intensity: str,
    weight_kg: float,
    note: Optional[str] = None,
) -> ExerciseLog:
    """
    Log an exercise session.

    Raises ValueError if MET not found (unknown activity/intensity combo).
    """
    intensity_norm = normalize_intensity(intensity)
    met = get_met(activity_name, intensity_norm)

    if met is None:
        raise ValueError(
            f"找不到「{activity_name}」({intensity}) 的 MET 值。"
            f"請確認活動名稱和強度是否正確，或使用自訂 MET 值。"
        )

    calories = estimate_calories_burned(weight_kg, met, duration_min)
    etype = exercise_type or classify_exercise_type(activity_name)

    db.execute(
        """INSERT INTO exercise_logs (user_id, log_date, exercise_type, activity_name,
           duration_min, intensity, calories_burned, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, log_date, activity_name)
           DO UPDATE SET duration_min = duration_min + excluded.duration_min,
                         calories_burned = calories_burned + excluded.calories_burned""",
        (user_id, log_date, etype, activity_name, duration_min,
         intensity_norm, calories, note)
    )

    return ExerciseLog(
        user_id=user_id,
        log_date=log_date,
        exercise_type=etype,
        activity_name=activity_name,
        duration_min=duration_min,
        intensity=intensity_norm,
        calories_burned=calories,
        note=note,
    )


def get_daily_exercise(
    db: DBManager, user_id: str, target_date: str
) -> list[dict]:
    """Get all exercise logs for a given date."""
    rows = db.fetchall(
        """SELECT exercise_type, activity_name, duration_min, intensity,
                  calories_burned, note
           FROM exercise_logs
           WHERE user_id = ? AND log_date = ?
           ORDER BY exercise_type, activity_name""",
        (user_id, target_date),
    )
    return [dict(r) for r in rows]


def get_daily_exercise_total(db: DBManager, user_id: str, target_date: str) -> float:
    """Get total calories burned from exercise on a given date."""
    row = db.fetchone(
        """SELECT COALESCE(SUM(calories_burned), 0) AS total
           FROM exercise_logs WHERE user_id = ? AND log_date = ?""",
        (user_id, target_date),
    )
    return float(row["total"]) if row else 0.0


# ─────────────────────────────────────────────────────────────
# Dynamic Calorie Quota Adjustment
# ─────────────────────────────────────────────────────────────

def adjust_daily_calorie_target(
    db: DBManager,
    user_id: str,
    target_date: str,
    base_target: int,
    exercise_cal: Optional[float] = None,
) -> dict:
    """
    Adjust daily calorie target based on exercise burned calories.

    Strategy:
    - If goal is weight loss: eat back 50% of exercise calories
      (prevents over-compensation)
    - If goal is muscle gain: eat back 100% of exercise calories
      (supports recovery and growth)
    - If goal is maintain: eat back 75% of exercise calories

    Returns ledger dict with base_target, exercise_cal, adjusted_target.
    """
    if exercise_cal is None:
        exercise_cal = get_daily_exercise_total(db, user_id, target_date)

    # Determine goal type from active plan
    row = db.fetchone(
        """SELECT goal_type FROM weight_plans
           WHERE user_id = ? AND is_active = 1
           ORDER BY created_at DESC LIMIT 1""",
        (user_id,),
    )
    goal_type = row["goal_type"] if row else "maintain"

    # Eat-back ratio by goal type
    eat_back_ratios = {"loss": 0.50, "gain": 1.00, "maintain": 0.75}
    ratio = eat_back_ratios.get(goal_type, 0.75)

    added_cal = round(exercise_cal * ratio)
    adjusted = base_target + added_cal

    db.execute(
        """INSERT INTO daily_calorie_ledger (user_id, ledger_date, base_target,
           exercise_cal, adjusted_target)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, ledger_date)
           DO UPDATE SET exercise_cal = excluded.exercise_cal,
                         adjusted_target = excluded.adjusted_target""",
        (user_id, target_date, base_target, int(exercise_cal), adjusted),
    )

    return {
        "user_id": user_id,
        "date": target_date,
        "base_target": base_target,
        "exercise_cal": int(exercise_cal),
        "added_cal": added_cal,
        "eat_back_ratio": ratio,
        "goal_type": goal_type,
        "adjusted_target": adjusted,
    }


def get_adjusted_target(
    db: DBManager, user_id: str, target_date: str
) -> Optional[int]:
    """Get the adjusted calorie target for a given date."""
    row = db.fetchone(
        """SELECT adjusted_target FROM daily_calorie_ledger
           WHERE user_id = ? AND ledger_date = ?""",
        (user_id, target_date),
    )
    return row["adjusted_target"] if row else None


# ─────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────

def format_exercise_summary(exercises: list[dict], total_cal: float) -> str:
    """Format a human-readable exercise summary."""
    if not exercises:
        return "📭 今日尚無運動記錄"

    lines = ["🏃 今日運動記錄", "─" * 30]
    for ex in exercises:
        etype_emoji = {"cardio": "🏃", "strength": "🏋️", "hiit": "🔥",
                       "yoga": "🧘", "other": "💪"}
        emoji = etype_emoji.get(ex.get("exercise_type", "other"), "💪")
        lines.append(
            f"{emoji} {ex['activity_name']}（{ex['intensity']}，{ex['duration_min']}分鐘）"
            f" — {ex['calories_burned']:.0f} kcal"
        )
    lines.extend(["─" * 30, f"🔥 總消耗：{total_cal:.0f} kcal"])
    return "\n".join(lines)


def format_ledger_summary(ledger: dict) -> str:
    """Format a human-readable calorie ledger summary."""
    lines = [
        "📊 動態熱量配額",
        "─" * 20,
        f"原始目標：{ledger['base_target']} kcal",
        f"運動消耗：{ledger['exercise_cal']} kcal",
        f"補充配額：+{ledger['added_cal']} kcal（{ledger['goal_type']}模式 ×{ledger['eat_back_ratio']:.0%}）",
        f"調整後目標：{ledger['adjusted_target']} kcal",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# CLI Entry Points
# ─────────────────────────────────────────────────────────────

def _get_db_and_user():
    db_path = Path(os.environ.get("HEALTHFIT_DB_PATH", DEFAULT_DB_PATH))
    if not db_path.exists():
        print("No database found. Run the Phase 1 intake flow first.", file=sys.stderr)
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


def cmd_log(args: argparse.Namespace) -> None:
    db, user_id = _get_db_and_user()

    # Get weight for MET calculation
    row = db.fetchone(
        """SELECT goal_weight_kg, start_weight_kg FROM weight_plans
           WHERE user_id = ? AND is_active = 1 LIMIT 1""",
        (user_id,),
    )
    weight_kg = 70.0  # fallback
    if row:
        weight_kg = float(row["goal_weight_kg"] or row["start_weight_kg"] or 70.0)

    target_date = args.date or str(date.today())
    etype = args.type or classify_exercise_type(args.activity)

    entry = log_exercise(
        db=db, user_id=user_id, log_date=target_date,
        exercise_type=etype, activity_name=args.activity,
        duration_min=args.duration, intensity=args.intensity,
        weight_kg=weight_kg, note=args.note,
    )

    print(f"✅ 已記錄：{entry.activity_name}（{entry.intensity}，{entry.duration_min}分鐘）")
    print(f"🔥 預估消耗：{entry.calories_burned:.0f} kcal")

    if args.auto_adjust:
        # Get base target
        plan = db.fetchone(
            """SELECT daily_calorie_target FROM weight_plans
               WHERE user_id = ? AND is_active = 1 LIMIT 1""",
            (user_id,),
        )
        if plan:
            ledger = adjust_daily_calorie_target(
                db, user_id, target_date, plan["daily_calorie_target"]
            )
            print(format_ledger_summary(ledger))


def cmd_status(args: argparse.Namespace) -> None:
    db, user_id = _get_db_and_user()
    target_date = args.date or str(date.today())
    exercises = get_daily_exercise(db, user_id, target_date)
    total = get_daily_exercise_total(db, user_id, target_date)
    print(format_exercise_summary(exercises, total))


def cmd_adjust(args: argparse.Namespace) -> None:
    db, user_id = _get_db_and_user()
    target_date = args.date or str(date.today())

    plan = db.fetchone(
        """SELECT daily_calorie_target FROM weight_plans
           WHERE user_id = ? AND is_active = 1 LIMIT 1""",
        (user_id,),
    )
    if not plan:
        print("No active weight plan found.", file=sys.stderr)
        sys.exit(1)

    ledger = adjust_daily_calorie_target(db, user_id, target_date, plan["daily_calorie_target"])
    print(format_ledger_summary(ledger))


def cmd_met_lookup(args: argparse.Namespace) -> None:
    """Look up MET value for an activity."""
    intensity = normalize_intensity(args.intensity)
    met = get_met(args.activity, intensity)
    if met is None:
        print(f"找不到「{args.activity}」({intensity}) 的 MET 值。")
        print(f"可用活動：{', '.join(sorted(set(k[0] for k in _MET_TABLE)))}")
        sys.exit(1)
    print(f"「{args.activity}」({intensity}) MET = {met}")
    if args.weight:
        cal = estimate_calories_burned(args.weight, met, args.duration or 30)
        print(f"預估消耗（{args.weight}kg，{args.duration or 30}分鐘）：{cal} kcal")


def main() -> None:
    parser = argparse.ArgumentParser(prog="exercise_tracker.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_log = sub.add_parser("log", help="Log an exercise session")
    p_log.add_argument("--type", "-t", choices=["cardio", "strength", "hiit", "yoga", "other"],
                       help="Exercise type (auto-detected if omitted)")
    p_log.add_argument("--activity", "-a", required=True, help="Activity name (e.g. 慢跑, 重訓)")
    p_log.add_argument("--duration", "-d", type=int, required=True, help="Duration in minutes")
    p_log.add_argument("--intensity", "-i", required=True,
                       help="Intensity: light/輕度, moderate/中度, vigorous/高強度")
    p_log.add_argument("--date", help="Date (YYYY-MM-DD, default today)")
    p_log.add_argument("--note", help="Optional note")
    p_log.add_argument("--auto-adjust", action="store_true",
                       help="Auto-adjust daily calorie target after logging")

    p_status = sub.add_parser("status", help="Show today's exercise summary")
    p_status.add_argument("--date", help="Date (YYYY-MM-DD, default today)")

    p_adj = sub.add_parser("adjust", help="Recalculate calorie adjustment")
    p_adj.add_argument("--date", help="Date (YYYY-MM-DD, default today)")

    p_met = sub.add_parser("met", help="Look up MET value")
    p_met.add_argument("--activity", "-a", required=True)
    p_met.add_argument("--intensity", "-i", required=True)
    p_met.add_argument("--weight", type=float, help="Weight in kg for calorie estimate")
    p_met.add_argument("--duration", type=int, default=30)

    args = parser.parse_args()

    if args.command == "log":
        cmd_log(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "adjust":
        cmd_adjust(args)
    elif args.command == "met":
        cmd_met_lookup(args)


if __name__ == "__main__":
    main()