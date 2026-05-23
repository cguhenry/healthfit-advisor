#!/usr/bin/env python3
"""
weekly_scoring_advanced.py — Phase 6: Advanced weekly scoring.

Extends the base scoring_engine with:
- Exercise integration (workout frequency, type diversity, calorie impact)
- GI (glycemic index) integration (GI quality score)
- Menstrual cycle integration (BMR adjustment period awareness + symptom penalty)
- Combined weighted scoring

Design:
- All functions are stateless (pass in DBManager).
- Does NOT modify scoring_engine.py; extends it via composition.
- Weekly score = 35% daily avg + 20% exercise + 15% weight trend
  + 15% GI quality + 10% completeness + 5% cycle awareness
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager
from scoring_engine import (
    DailyNutrition,
    DailyScore,
    WeeklyScore,
    _classify_grade,
    get_daily_nutrition,
    score_daily,
    score_weekly as base_score_weekly,
)

# ─────────────────────────────────────────────────────────────
# Advanced Weekly Score dataclass
# ─────────────────────────────────────────────────────────────

@dataclass
class AdvancedWeeklyScore:
    """Extended weekly score with Phase 6 integrations."""
    user_id: str
    week_start: str
    # Base components
    daily_scores: list[int] = field(default_factory=list)
    avg_daily_score: float = 0.0
    # Exercise
    exercise_score: int = 0
    exercise_days: int = 0
    total_exercise_cal: float = 0.0
    exercise_types_used: int = 0
    # GI quality
    gi_score: int = 0
    gi_avg_daily: float = 0.0
    # Weight trend
    weight_trend_score: int = 0
    weight_change_kg: float = 0.0
    # Record completeness
    completeness_score: int = 0
    logged_days: int = 0
    # Cycle awareness (menstrual)
    cycle_score: int = 0
    cycle_phase: str = ""
    cycle_day: int = 0
    # Final
    final_score: int = 0
    grade: str = ""
    # Breakdown for reports
    breakdown: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# Exercise Integration
# ─────────────────────────────────────────────────────────────

def calc_exercise_score(
    db: DBManager,
    user_id: str,
    week_start: str,
    weight_kg: float = 70.0,
) -> tuple[int, int, float, int]:
    """
    Calculate exercise component score (0-100).

    Scored on:
    - Frequency: 3+ days → full marks, 2 days → 70%, 1 → 40%, 0→0
    - Total calorie burn: ≥1000 kcal/week → bonus
    - Type diversity: 2+ types → +10 bonus

    Returns (score, exercise_days, total_cal, types_used).
    """
    ws = date.fromisoformat(week_start)
    days = []
    total_cal = 0.0
    types_set: set[str] = set()

    for i in range(7):
        d = (ws + timedelta(days=i)).isoformat()
        rows = db.fetchall(
            """SELECT exercise_type, SUM(calories_burned) as day_cal
               FROM exercise_logs
               WHERE user_id = ? AND log_date = ?
               GROUP BY log_date""",
            (user_id, d),
        )
        if rows:
            day_cal = sum(float(r["day_cal"] or 0) for r in rows)
            total_cal += day_cal
            days.append(d)
            # Track types
            type_rows = db.fetchall(
                "SELECT DISTINCT exercise_type FROM exercise_logs "
                "WHERE user_id = ? AND log_date = ?",
                (user_id, d),
            )
            for tr in type_rows:
                types_set.add(tr["exercise_type"])

    exercise_days = len(days)
    types_used = len(types_set)

    # Score calculation
    if exercise_days >= 5:
        freq_score = 100
    elif exercise_days >= 3:
        freq_score = 85
    elif exercise_days >= 2:
        freq_score = 60
    elif exercise_days >= 1:
        freq_score = 35
    else:
        freq_score = 0

    # Calorie bonus (up to +15)
    if total_cal >= 2000:
        cal_bonus = 15
    elif total_cal >= 1500:
        cal_bonus = 12
    elif total_cal >= 1000:
        cal_bonus = 8
    elif total_cal >= 500:
        cal_bonus = 5
    else:
        cal_bonus = 0

    # Diversity bonus
    div_bonus = 10 if types_used >= 3 else (5 if types_used >= 2 else 0)

    score = min(100, freq_score + cal_bonus + div_bonus)
    return score, exercise_days, total_cal, types_used


# ─────────────────────────────────────────────────────────────
# GI Quality Integration
# ─────────────────────────────────────────────────────────────

def calc_gi_quality_score(
    db: DBManager,
    user_id: str,
    week_start: str,
) -> tuple[int, float]:
    """
    Calculate GI quality score from gi_intake_logs.

    Scoring: average daily GI intake mapped to score.
    - GI avg < 55 (low GI) → 100
    - GI avg 55-65 → 85
    - GI avg 65-70 → 70
    - GI avg > 70 → 50

    Returns (score_0_100, avg_daily_gi).
    """
    ws = date.fromisoformat(week_start)
    gi_values: list[float] = []

    for i in range(7):
        d = (ws + timedelta(days=i)).isoformat()
        row = db.fetch_one(
            """SELECT AVG(estimated_gi) as avg_gi
               FROM gi_intake_logs
               WHERE user_id = ? AND log_date = ?""",
            (user_id, d),
        )
        if row and row["avg_gi"] is not None:
            gi_values.append(float(row["avg_gi"]))

    if not gi_values:
        return 0, 0.0

    avg_gi = sum(gi_values) / len(gi_values)

    if avg_gi < 55:
        score = 100
    elif avg_gi < 65:
        score = 85
    elif avg_gi <= 70:
        score = 70
    else:
        score = 50

    return score, round(avg_gi, 1)


# ─────────────────────────────────────────────────────────────
# Menstrual Cycle Integration
# ─────────────────────────────────────────────────────────────

def calc_cycle_awareness_score(
    db: DBManager,
    user_id: str,
    week_start: str,
) -> tuple[int, str, int]:
    """
    Calculate menstrual cycle awareness score.

    Checks if the week overlaps with:
    - Luteal phase (PMS/higher BMR): +10 bonus for awareness
    - Menstrual phase (fatigue): no penalty, neutral
    - Follicular phase: optimal training, +5 bonus

    Returns (score_0_100, phase_label, cycle_day).
    """
    ws = date.fromisoformat(week_start)
    week_end = ws + timedelta(days=6)

    # Get most recent period
    period = db.fetch_one(
        """SELECT period_start_date, cycle_length
           FROM menstrual_cycles
           WHERE user_id = ?
           ORDER BY period_start_date DESC LIMIT 1""",
        (user_id,),
    )

    if not period:
        return 0, "", 0

    period_start = date.fromisoformat(period["period_start_date"])
    cycle_length = int(period["cycle_length"] or 28)

    # Determine which cycle day the middle of the week falls on
    week_mid = ws + timedelta(days=3)
    cycle_day = ((week_mid - period_start).days % cycle_length) + 1

    # Phase detection
    # Follicular: days 1-14 (approx)
    # Ovulation: day 14-15
    # Luteal: days 16-28
    if cycle_day <= 5:
        phase = "經期"
        score = 5       # Neutral awareness - no penalty for reduced performance
    elif cycle_day <= 13:
        phase = "濾泡期"
        score = 10      # Bonus: best time for training
    elif cycle_day <= 15:
        phase = "排卵期"
        score = 8       # Good energy
    elif cycle_day <= 28:
        phase = "黃體期"
        score = 6       # PMS, higher BMR awareness - reduced penalty
    else:
        phase = ""
        score = 0

    # Map to 0-100 for weighting
    return min(100, score * 10), phase, cycle_day


# ─────────────────────────────────────────────────────────────
# Combined Advanced Weekly Scoring
# ─────────────────────────────────────────────────────────────

def score_weekly_advanced(
    db: DBManager,
    user_id: str,
    week_start: str,
    calorie_target: Optional[int] = None,
    protein_target_g: Optional[int] = None,
    body_weight_kg: float = 0.0,
    expected_weekly_change_kg: float = 0.0,
) -> AdvancedWeeklyScore:
    """
    Calculate advanced weekly score with Phase 6 integrations.

    Weights:
    - 35% daily avg score
    - 20% exercise
    - 15% weight trend
    - 15% GI quality
    - 10% record completeness
    - 5% cycle awareness
    """
    db.initialize()
    ws = date.fromisoformat(week_start)
    week_end = ws + timedelta(days=6)
    week_end_str = week_end.isoformat()

    # Resolve targets from plan if not provided
    if calorie_target is None or protein_target_g is None:
        plan = db.get_active_plan(user_id)
        if plan:
            calorie_target = calorie_target or int(plan["daily_calorie_target"] or 0)
            protein_target_g = protein_target_g or int(plan["protein_target_g"] or 0)
            if body_weight_kg <= 0:
                body_weight_kg = float(plan["start_weight_kg"] or 0)
        else:
            calorie_target = calorie_target or 0
            protein_target_g = protein_target_g or 0

    # ── 1. Daily scores (35%) ────────────────────────────────────
    daily_scores: list[int] = []
    daily_cals: list[float] = []
    logged_days = 0

    for i in range(7):
        d = (ws + timedelta(days=i)).isoformat()
        nutrition = get_daily_nutrition(db, user_id, d)

        if nutrition.item_count > 0:
            # Check for exercise-adjusted target
            ledger = db.fetch_one(
                "SELECT adjusted_target FROM daily_calorie_ledger "
                "WHERE user_id = ? AND ledger_date = ?",
                (user_id, d),
            )
            effective_target = ledger["adjusted_target"] if ledger else calorie_target

            ds = score_daily(nutrition, effective_target or 0, protein_target_g or 0, body_weight_kg)
            daily_scores.append(ds.final_score)

            if nutrition.total_calories > 0:
                daily_cals.append(nutrition.total_calories)
            logged_days += 1
        else:
            daily_scores.append(0)
            daily_cals.append(0)

    avg_daily = sum(daily_scores) / max(len(daily_scores), 1)
    daily_component = avg_daily * 0.35

    # ── 2. Exercise (20%) ────────────────────────────────────────
    exercise_score, exercise_days, total_exercise_cal, types_used = \
        calc_exercise_score(db, user_id, week_start, body_weight_kg)
    exercise_component = exercise_score * 0.20

    # ── 3. Weight trend (15%) ────────────────────────────────────
    # Get weight at start and end of week
    start_weight = db.fetch_one(
        "SELECT weight_kg FROM weight_logs WHERE user_id = ? AND log_date <= ? "
        "ORDER BY log_date DESC LIMIT 1",
        (user_id, week_start),
    )
    end_weight = db.fetch_one(
        "SELECT weight_kg FROM weight_logs WHERE user_id = ? AND log_date <= ? "
        "ORDER BY log_date DESC LIMIT 1",
        (user_id, week_end_str),
    )

    weight_change_kg = 0.0
    if start_weight and end_weight:
        weight_change_kg = float(end_weight["weight_kg"]) - float(start_weight["weight_kg"])

    # Score based on alignment with expected change
    actual_change = weight_change_kg
    if abs(expected_weekly_change_kg) > 0.01:
        deviation = abs(actual_change - expected_weekly_change_kg)
        max_dev = max(abs(expected_weekly_change_kg) * 2, 0.5)
        weight_trend_score = max(0, int(100 * (1 - min(deviation / max_dev, 1.0))))
    else:
        deviation = abs(actual_change)
        weight_trend_score = max(0, int(100 * (1 - min(deviation / 0.5, 1.0))))
    weight_component = weight_trend_score * 0.15

    # ── 4. GI Quality (15%) ──────────────────────────────────────
    gi_score, gi_avg_daily = calc_gi_quality_score(db, user_id, week_start)
    gi_component = gi_score * 0.15

    # ── 5. Record completeness (10%) ─────────────────────────────
    completeness_score = int((logged_days / 7) * 100)
    completeness_component = completeness_score * 0.10

    # ── 6. Cycle awareness (5%) ──────────────────────────────────
    cycle_score, cycle_phase, cycle_day = calc_cycle_awareness_score(db, user_id, week_start)
    cycle_component = cycle_score * 0.05

    # ── Final ────────────────────────────────────────────────────
    final = int(round(
        daily_component + exercise_component + weight_component +
        gi_component + completeness_component + cycle_component
    ))
    final = max(0, min(100, final))

    avg_cal = sum(daily_cals) / max(len(daily_cals), 1) if daily_cals else 0

    return AdvancedWeeklyScore(
        user_id=user_id,
        week_start=week_start,
        daily_scores=daily_scores,
        avg_daily_score=round(avg_daily, 1),
        exercise_score=exercise_score,
        exercise_days=exercise_days,
        total_exercise_cal=round(total_exercise_cal, 1),
        exercise_types_used=types_used,
        gi_score=gi_score,
        gi_avg_daily=gi_avg_daily,
        weight_trend_score=weight_trend_score,
        weight_change_kg=round(weight_change_kg, 2),
        completeness_score=completeness_score,
        logged_days=logged_days,
        cycle_score=cycle_score,
        cycle_phase=cycle_phase,
        cycle_day=cycle_day,
        final_score=final,
        grade=_classify_grade(final),
        breakdown={
            "weights": {
                "daily_avg": "35%",
                "exercise": "20%",
                "weight_trend": "15%",
                "gi_quality": "15%",
                "completeness": "10%",
                "cycle_awareness": "5%",
            },
            "scores": {
                "daily_component": round(daily_component, 1),
                "exercise_component": round(exercise_component, 1),
                "weight_component": round(weight_component, 1),
                "gi_component": round(gi_component, 1),
                "completeness_component": round(completeness_component, 1),
                "cycle_component": round(cycle_component, 1),
            },
            "exercise_days": exercise_days,
            "exercise_types_used": types_used,
            "total_exercise_cal": round(total_exercise_cal, 1),
            "gi_avg_daily": gi_avg_daily,
            "weight_change_kg": round(weight_change_kg, 2),
            "cycle_phase": cycle_phase,
            "cycle_day": cycle_day,
            "avg_daily_cal": round(avg_cal, 1),
        },
    )


# ─────────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────────

def format_advanced_weekly_score(aws: AdvancedWeeklyScore) -> str:
    """Format AdvancedWeeklyScore for display."""
    lines = [
        f"📈 進階週評分報告 — {aws.week_start} 起",
        "═" * 50,
        "",
        "📊 評分項目　　　　　分數　　權重　　貢獻",
        "─" * 50,
    ]

    # Daily avg
    daily_comp = aws.breakdown["scores"]["daily_component"]
    lines.append(f"📋 每日平均分數　　　{aws.avg_daily_score:.1f}　　35%　　 {daily_comp:.1f}")

    # Exercise
    ex_comp = aws.breakdown["scores"]["exercise_component"]
    lines.append(f"🏃 運動表現　　　　　{aws.exercise_score}　　　20%　　 {ex_comp:.1f}")

    # Weight trend
    wt_comp = aws.breakdown["scores"]["weight_component"]
    lines.append(f"⚖️  體重趨勢　　　　　{aws.weight_trend_score}　　　15%　　 {wt_comp:.1f}")

    # GI Quality
    gi_comp = aws.breakdown["scores"]["gi_component"]
    lines.append(f"🍚 GI 品質　　　　　 {aws.gi_score}　　　15%　　 {gi_comp:.1f}")

    # Completeness
    comp_comp = aws.breakdown["scores"]["completeness_component"]
    lines.append(f"📝 記錄完整度　　　　{aws.completeness_score}　　　10%　　 {comp_comp:.1f}")

    # Cycle awareness (only if applicable)
    if aws.cycle_phase:
        cyc_comp = aws.breakdown["scores"]["cycle_component"]
        phase_emoji = {"經期": "🩸", "濾泡期": "🌸", "排卵期": "✨", "黃體期": "🌙"}
        emoji = phase_emoji.get(aws.cycle_phase, "🔄")
        lines.append(f"{emoji} 週期覺察（{aws.cycle_phase} D{aws.cycle_day}）　 {aws.cycle_score}　　　 5%　　 {cyc_comp:.1f}")

    lines.extend([
        "─" * 50,
        f"🏆 最終分數：{aws.final_score} 分　{aws.grade}",
        "",
        "📋 詳細明細",
        "─" * 50,
    ])

    # Daily scores bar
    bar_chars = []
    for s in aws.daily_scores:
        if s >= 90:
            bar_chars.append("🟢")
        elif s >= 75:
            bar_chars.append("🟡")
        elif s >= 60:
            bar_chars.append("🟠")
        else:
            bar_chars.append("🔴")
    lines.append(f"每日分數：{aws.daily_scores}")
    lines.append(f"每日指標：{''.join(bar_chars)}")

    # Exercise details
    if aws.exercise_days > 0:
        lines.append(f"🏃 運動天數：{aws.exercise_days}/7　燃燒：{aws.total_exercise_cal:.0f} kcal　類型數：{aws.exercise_types_used}")

    # GI detail
    if aws.gi_avg_daily > 0:
        gi_label = "🟢 低 GI" if aws.gi_avg_daily < 55 else ("🟡 中 GI" if aws.gi_avg_daily <= 70 else "🔴 高 GI")
        lines.append(f"🍚 平均 GI：{aws.gi_avg_daily}（{gi_label}）")

    # Weight detail
    lines.append(f"⚖️  體重變化：{aws.weight_change_kg:+.1f} kg")

    # Record completeness
    lines.append(f"📝 記錄天數：{aws.logged_days}/7")

    # Cycle detail
    if aws.cycle_phase:
        phase_suggestions = {
            "經期": "💡 經期間適度休息，補鐵質（深綠色蔬菜、紅肉）",
            "濾泡期": "💡 濾泡期是運動表現最佳時期，可挑戰高強度訓練",
            "排卵期": "💡 排卵期能量充沛，注意保持水分",
            "黃體期": "💡 黃體期 BMR 提升 5-10%，輕微熱量增加屬正常現象",
        }
        if aws.cycle_phase in phase_suggestions:
            lines.append(phase_suggestions[aws.cycle_phase])

    # Recommendations
    lines.extend(["", "💡 下週建議", "─" * 20])
    recs = _generate_advanced_recommendations(aws)
    for rec in recs:
        lines.append(f"  • {rec}")

    return "\n".join(lines)


def _generate_advanced_recommendations(aws: AdvancedWeeklyScore) -> list[str]:
    """Generate targeted recommendations."""
    recs: list[str] = []

    if aws.exercise_days < 2:
        recs.append("🏃 每週至少安排 2 次運動，目標 150 分鐘中強度活動")
    elif aws.exercise_days < 3:
        recs.append("🏃 再增加 1 天運動即可達標，試試不同類型增加趣味性")

    if aws.exercise_types_used < 2 and aws.exercise_days > 0:
        recs.append("🏋️ 建議增加不同類型運動（如有氧+重訓），平衡訓練效果")

    if aws.gi_avg_daily > 65:
        recs.append("🍚 GI 偏高，減少精緻澱粉（白飯、白麵包），改用全穀、糙米")
    elif aws.gi_avg_daily > 55:
        recs.append("🍚 GI 尚可，可再降低白米比例，加入更多豆類和蔬菜")

    if aws.logged_days < 6:
        recs.append(f"📝 僅記錄 {aws.logged_days}/7 天，建議每天記錄以獲得準確評分")

    if aws.cycle_phase == "黃體期" and aws.exercise_score < 50:
        recs.append("🌙 黃體期體力可能下降屬正常，可調整為中低強度運動（如散步、瑜珈）")

    if aws.final_score < 60:
        recs.append("📋 整體分數偏低，建議從記錄完整度開始改善")

    if not recs:
        recs.append("🎉 表現優異！維持目前的好習慣")

    return recs


# ─────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────

def persist_advanced_weekly_score(
    db: DBManager,
    aws: AdvancedWeeklyScore,
) -> str:
    """Persist advanced weekly score to weekly_summaries table."""
    db.initialize()

    import json

    report = json.dumps({
        "scoring_version": "advanced_phase6",
        "daily_scores": aws.daily_scores,
        "avg_daily_score": aws.avg_daily_score,
        "exercise_score": aws.exercise_score,
        "exercise_days": aws.exercise_days,
        "total_exercise_cal": aws.total_exercise_cal,
        "gi_score": aws.gi_score,
        "weight_trend_score": aws.weight_trend_score,
        "completeness_score": aws.completeness_score,
        "cycle_score": aws.cycle_score,
        "cycle_phase": aws.cycle_phase,
        "breakdown": aws.breakdown,
        "grade": aws.grade,
    }, ensure_ascii=False)

    import uuid

    existing = db.fetch_one(
        "SELECT summary_id FROM weekly_summaries WHERE user_id = ? AND week_start_date = ?",
        (aws.user_id, aws.week_start),
    )
    if existing:
        db.execute(
            """UPDATE weekly_summaries SET weekly_score = ?, report_text = ?
               WHERE summary_id = ?""",
            (aws.final_score, report, existing["summary_id"]),
        )
        return existing["summary_id"]

    sid = str(uuid.uuid4())
    db.execute(
        """INSERT INTO weekly_summaries (
             summary_id, user_id, week_start_date, weekly_score, report_text
           ) VALUES (?, ?, ?, ?, ?)""",
        (sid, aws.user_id, aws.week_start, aws.final_score, report),
    )
    return sid


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="HealthFit advanced weekly scoring (Phase 6)")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--week-start", required=True, help="YYYY-MM-DD (Monday)")
    parser.add_argument("--calorie-target", type=int, default=None)
    parser.add_argument("--protein-target", type=int, default=None)
    parser.add_argument("--body-weight-kg", type=float, default=0.0)
    parser.add_argument("--expected-weekly-change", type=float, default=0.0)
    parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    args = parser.parse_args()
    db = DBManager(Path(args.db_path))

    aws = score_weekly_advanced(
        db=db,
        user_id=args.user_id,
        week_start=args.week_start,
        calorie_target=args.calorie_target,
        protein_target_g=args.protein_target,
        body_weight_kg=args.body_weight_kg,
        expected_weekly_change_kg=args.expected_weekly_change,
    )

    print(format_advanced_weekly_score(aws))

    # Persist
    persist_advanced_weekly_score(db, aws)
    print(f"\n✅ 已儲存至資料庫")


if __name__ == "__main__":
    main()