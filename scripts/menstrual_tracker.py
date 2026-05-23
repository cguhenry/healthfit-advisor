#!/usr/bin/env python3
"""
menstrual_tracker.py — Phase 6: Menstrual cycle phase tracking with BMR/target adjustments.

Supports users who wish to track their menstrual cycle and adjust
calorie targets based on cycle phase.

Cycle phases (28-day model, adjustable):
1. Follicular phase (Day 1–14): Slightly higher BMR
2. Luteal phase (Day 15–28): ~5–10% higher BMR (progesterone effect)
3. Menstruation (Day 1–7): Potential iron loss, appetite changes

Adjustments based on:
- Davidsen et al. (2007): 5–10% increased energy expenditure in luteal phase
- Benton et al. (2020): Protein needs may increase in luteal phase
- ACSM guidelines for exercise adaptation during cycle

Usage (CLI):
    python3 scripts/menstrual_tracker.py log-period --start 2026-05-15
    python3 scripts/menstrual_tracker.py current-phase
    python3 scripts/menstrual_tracker.py adjust 1500
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager

DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()

# ─────────────────────────────────────────────────────────────
# Cycle phase constants
# ─────────────────────────────────────────────────────────────

# Default 28-day cycle. Adjustable per user.
DEFAULT_CYCLE_LENGTH = 28
DEFAULT_PERIOD_LENGTH = 5

# BMR adjustment factors by phase
# Based on Davidsen et al. (2007) and Benton et al. (2020)
PHASE_BMR_ADJUSTMENTS: dict[str, float] = {
    "menstruation": 1.00,   # Baseline (no adjustment)
    "follicular":   1.02,   # Slight increase post-menstruation
    "ovulation":    1.03,   # Slight increase during ovulation
    "luteal":       1.07,   # 5–10% increase confirmed by literature
    "premenstrual": 1.05,   # Slightly lower than full luteal
}

# Nutrition adjustment recommendations by phase
PHASE_NUTRITION_ADVICE: dict[str, dict[str, object]] = {
    "menstruation": {
        "emoji": "🩸",
        "display": "月經期",
        "advice": (
            "• 鐵質補充：建議攝取紅肉、菠菜、黑芝麻、蛤蜊\n"
            "• 補水：增加水量攝取，減少咖啡因\n"
            "• 維生素C：幫助鐵質吸收（搭配奇異果、芭樂）\n"
            "• Omega-3：鮭魚、亞麻籽，有助緩解經痛\n"
            "• 避免生冷食物，運動以溫和伸展為主"
        ),
    },
    "follicular": {
        "emoji": "🌱",
        "display": "濾泡期",
        "advice": (
            "• 荷爾蒙穩定，是運動表現最佳時期\n"
            "• 碳水可略高（肝醣儲存能力佳）\n"
            "• 適合高強度訓練與增肌\n"
            "• 代謝率開始回升，是熱量控制的黃金期"
        ),
    },
    "ovulation": {
        "emoji": "🥚",
        "display": "排卵期",
        "advice": (
            "• 雌激素高峰，運動表現仍然不錯\n"
            "• 注意關節鬆弛（黃體素上升），避免高衝擊運動\n"
            "• 食慾可能增加，但屬正常生理現象\n"
            "• 保持蛋白質攝取以穩定血糖"
        ),
    },
    "luteal": {
        "emoji": "🌙",
        "display": "黃體期",
        "advice": (
            "• BMR 增加 5–10%，基礎消耗上升\n"
            "• 蛋白質需求提高（建議 +10–15g/天）\n"
            "• 複合碳水化合物（地瓜、燕麥）穩定情緒\n"
            "• 避免過度限制熱量（身體處於高代謝狀態）\n"
            "• 建議增加鎂攝取（堅果、深綠色蔬菜）\n"
            "• 運動以中等強度為主，注意疲勞恢復"
        ),
    },
    "premenstrual": {
        "emoji": "💧",
        "display": "經前",
        "advice": (
            "• PMS 常見：水腫、情緒波動、旺盛食慾\n"
            "• 維生素B6有助緩解情緒不適\n"
            "• 減少鹽分攝取以減輕水腫\n"
            "• 小分量多餐，穩定血糖\n"
            "• 若食慾爆增，選低GI高體積食物\n"
            "• 運動以瑜珈、散步等低強度為佳"
        ),
    },
}


def get_cycle_phase(
    last_period_start: date, today: Optional[date] = None,
    cycle_length: int = DEFAULT_CYCLE_LENGTH,
) -> dict:
    """Determine current cycle phase based on last period start date.

    Args:
        last_period_start: Start date of last menstrual period
        today: Current date (default: today)
        cycle_length: Length of cycle in days (default: 28)

    Returns dict with:
        - phase: str (menstruation/follicular/ovulation/luteal/premenstrual)
        - cycle_day: int (1-indexed day of cycle)
        - days_remaining: int (days until next predicted period)
    """
    today = today or date.today()
    days_since = (today - last_period_start).days
    cycle_day = (days_since % cycle_length) + 1

    # Map cycle day to phase
    # Menstruation: day 1–DEFAULT_PERIOD_LENGTH
    # Follicular: day 6–12
    # Ovulation: day 13–15 (approximate)
    # Luteal: day 16–25
    # Premenstrual: day 26–28
    period_len = min(DEFAULT_PERIOD_LENGTH, cycle_length)

    if cycle_day <= period_len:
        phase = "menstruation"
    elif cycle_day <= 12:
        phase = "follicular"
    elif cycle_day <= 15:
        phase = "ovulation"
    elif cycle_day <= 25:
        phase = "luteal"
    else:
        phase = "premenstrual"

    days_remaining = cycle_length - cycle_day
    next_period = today + timedelta(days=days_remaining)

    return {
        "phase": phase,
        "cycle_day": cycle_day,
        "cycle_length": cycle_length,
        "days_remaining": days_remaining,
        "predicted_next_period": str(next_period),
        "bmr_adjustment": PHASE_BMR_ADJUSTMENTS.get(phase, 1.0),
    }


def adjust_calorie_target(
    base_calories: int, phase_info: dict
) -> dict:
    """Adjust calorie target based on menstrual cycle phase.

    Returns dict with:
        - base_target: int (original)
        - adjusted_target: int (phase-adjusted)
        - bmr_adjustment: float
        - phase_display: str
        - advice: str
    """
    phase = phase_info["phase"]
    adjustment = phase_info["bmr_adjustment"]
    adjusted = round(base_calories * adjustment)

    phase_data = PHASE_NUTRITION_ADVICE.get(phase, {})
    display = phase_data.get("display", phase)
    advice = phase_data.get("advice", "")
    emoji = phase_data.get("emoji", "")

    return {
        "base_target": base_calories,
        "adjusted_target": adjusted,
        "increase": adjusted - base_calories,
        "bmr_adjustment": adjustment,
        "phase": phase,
        "phase_display": f"{emoji} {display}",
        "cycle_day": phase_info["cycle_day"],
        "advice": advice,
    }


# ─────────────────────────────────────────────────────────────
# Database persistence
# ─────────────────────────────────────────────────────────────

def log_period_start(
    db: DBManager, user_id: str, start_date: str, cycle_length: Optional[int] = None,
) -> dict:
    """Log a period start date. Returns the saved record."""
    db.execute(
        """INSERT INTO menstrual_logs (user_id, period_start, cycle_length)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id, period_start)
           DO UPDATE SET cycle_length = excluded.cycle_length""",
        (user_id, start_date, cycle_length),
    )
    return {"user_id": user_id, "period_start": start_date, "cycle_length": cycle_length}


def get_last_period_start(db: DBManager, user_id: str) -> Optional[dict]:
    """Get the most recent logged period start date and cycle length.

    Returns dict with period_start (date) and cycle_length (int),
    or None if no data.
    """
    row = db.fetchone(
        """SELECT period_start, cycle_length FROM menstrual_logs
           WHERE user_id = ? ORDER BY period_start DESC LIMIT 1""",
        (user_id,),
    )
    if not row:
        return None

    return {
        "period_start": date.fromisoformat(str(row["period_start"])[:10]),
        "cycle_length": row["cycle_length"] or DEFAULT_CYCLE_LENGTH,
    }


def get_cycle_info(db: DBManager, user_id: str) -> Optional[dict]:
    """Get current cycle phase info from DB."""
    last_data = get_last_period_start(db, user_id)
    if last_data is None:
        return None
    return get_cycle_phase(last_data["period_start"], cycle_length=last_data["cycle_length"])


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def _get_db_and_user():
    db_path = Path(os.environ.get("HEALTHFIT_DB_PATH", DEFAULT_DB_PATH))
    if not db_path.exists():
        print("No database found.", file=sys.stderr)
        sys.exit(1)
    db = DBManager(db_path=db_path)

    profile_path = Path(os.environ.get("HEALTHFIT_PROFILE",
                                       Path("~/.healthfit/profile.json").expanduser()))
    if not profile_path.exists():
        print("No profile found.", file=sys.stderr)
        sys.exit(1)
    with open(profile_path) as f:
        profile = json.load(f)
    user_id = profile.get("user_id") or profile.get("user", {}).get("user_id", "")
    return db, user_id


def cmd_log_period(args: argparse.Namespace) -> None:
    db, user_id = _get_db_and_user()
    result = log_period_start(db, user_id, args.start, args.cycle_length)
    print(f"✅ 已記錄週期開始：{result['period_start']}")
    if args.cycle_length:
        print(f"   週期長度：{args.cycle_length} 天")
    cycle = get_cycle_info(db, user_id)
    if cycle:
        print(f"   目前：第{cycle['cycle_day']}天，{cycle['phase']}")


def cmd_current_phase(args: argparse.Namespace) -> None:
    db, user_id = _get_db_and_user()
    info = get_cycle_info(db, user_id)
    if not info:
        print("📭 尚未記錄月經週期。請先使用 menstrual_tracker.py log-period 記錄。")
        return

    phase_data = PHASE_NUTRITION_ADVICE.get(info["phase"], {})
    emoji = phase_data.get("emoji", "")
    display = phase_data.get("display", info["phase"])
    advice = phase_data.get("advice", "")

    print(f"{emoji} 目前週期：{display}")
    print(f"   週期第 {info['cycle_day']} 天（週期長度 {info['cycle_length']} 天）")
    print(f"   距下次月經：{info['days_remaining']} 天")
    print(f"   預估下次：{info['predicted_next_period']}")
    print(f"   BMR 調整：{info['bmr_adjustment']:.0%}")
    if advice:
        print(f"\n📋 營養建議：")
        print(advice)


def cmd_adjust(args: argparse.Namespace) -> None:
    db, user_id = _get_db_and_user()
    info = get_cycle_info(db, user_id)
    if not info:
        print("⚠️ 尚未記錄月經週期，無法調整。先使用 log-period 記錄。")
        return

    result = adjust_calorie_target(args.calories, info)
    print(f"📊 熱量調整（{result['phase_display']}）")
    print(f"   原始目標：{result['base_target']} kcal")
    print(f"   調整倍率：{result['bmr_adjustment']:.0%}")
    print(f"   調整後目標：{result['adjusted_target']} kcal")
    if result["advice"]:
        print(f"\n📋 {result['phase_display']}建議：")
        print(result["advice"])

    if args.json:
        import json as _json
        print(_json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="menstrual_tracker.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_log = sub.add_parser("log-period", help="Log a period start date")
    p_log.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    p_log.add_argument("--cycle-length", type=int, help="Cycle length in days")

    p_phase = sub.add_parser("current-phase", help="Show current cycle phase")

    p_adj = sub.add_parser("adjust", help="Adjust calorie target for cycle phase")
    p_adj.add_argument("--calories", type=int, required=True, help="Base daily calorie target")
    p_adj.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args()

    if args.command == "log-period":
        cmd_log_period(args)
    elif args.command == "current-phase":
        cmd_current_phase(args)
    elif args.command == "adjust":
        cmd_adjust(args)


if __name__ == "__main__":
    main()