#!/usr/bin/env python3
"""
scoring_engine.py — Phase 5: Daily & weekly scoring engine.

Implements the scoring rubric from the HealthFit development plan:
- Daily score: 100-point base, deductions per WHO/ACSM/Taiwan DRI guidelines
- Weekly score: 50% daily average + 20% weight trend + 15% diversity + 15% completeness
- Persists scores into daily_summaries, weekly_summaries, and score_events.

All functions are stateless: pass in a DBManager, user_id, and data.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Ensure sibling scripts are importable ───────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager

# ---------------------------------------------------------------------------
# Constants — scoring rubric
# ---------------------------------------------------------------------------

# Calorie overage deductions
CALORIE_OVER_SEVERE_PCT = 0.20    # > target +20%
CALORIE_OVER_MODERATE_PCT = 0.10  # target +10~20%
CALORIE_OVER_MILD_PCT = 0.05      # target +5~10%

CALORIE_UNDER_SEVERE_PCT = 0.25   # < target -25%
CALORIE_UNDER_MODERATE_PCT = 0.15 # target -15~25%

# Protein deductions
PROTEIN_LOW_PCT = 0.80            # < target 80%
PROTEIN_MAX_G_PER_KG = 2.5        # g per kg body weight

# Other thresholds
FIBER_MIN_G = 25.0
SODIUM_MAX_MG = 2300.0
REFINED_SUGAR_MAX_PCT = 0.10      # 10% of total calories

# Meal count
EXPECTED_MEALS_PER_DAY = 3        # breakfast, lunch, dinner

# Bonus
DAILY_BONUS = 5

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DailyNutrition:
    """Aggregated nutrition data for a single day (from food_logs)."""
    total_calories: float = 0.0
    total_protein_g: float = 0.0
    total_carb_g: float = 0.0
    total_fat_g: float = 0.0
    total_fiber_g: float = 0.0
    total_sodium_mg: float = 0.0
    refined_sugar_g: float = 0.0      # estimate, may be 0 if not tracked
    meal_count: int = 0               # distinct meal_types logged
    item_count: int = 0               # total food items


@dataclass
class ScoreEvent:
    """A single scoring event (deduction or bonus)."""
    event_type: str
    points: int                       # negative = deduction, positive = bonus
    description: str


@dataclass
class DailyScore:
    """Result of daily scoring calculation."""
    user_id: str
    score_date: str
    base_score: int = 100
    deductions: List[ScoreEvent] = field(default_factory=list)
    bonus: Optional[ScoreEvent] = None
    final_score: int = 100
    grade: str = "⭐ 優秀"
    breakdown: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WeeklyScore:
    """Result of weekly scoring calculation."""
    user_id: str
    week_start: str
    daily_scores: List[int] = field(default_factory=list)
    avg_daily_score: float = 0.0
    weight_trend_score: int = 0
    diversity_score: int = 0
    completeness_score: int = 0
    final_score: int = 0
    grade: str = "⭐ 優秀"
    weekly_calories_avg: float = 0.0
    goal_adherence_pct: float = 0.0
    weight_change_kg: Optional[float] = 0.0
    weight_trend_available: bool = True
    weight_trend_note: str = ""
    component_weights: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Grade classification
# ---------------------------------------------------------------------------

def _classify_grade(score: int) -> str:
    if score >= 90:
        return "⭐ 優秀"
    elif score >= 75:
        return "良好"
    elif score >= 60:
        return "及格"
    elif score >= 40:
        return "待加強"
    else:
        return "⚠️ 警示"


# ---------------------------------------------------------------------------
# Daily scoring
# ---------------------------------------------------------------------------

def score_daily(
    nutrition: DailyNutrition,
    calorie_target: int,
    protein_target_g: int,
    body_weight_kg: float = 0.0,
    expected_meals: int = EXPECTED_MEALS_PER_DAY,
) -> DailyScore:
    """
    Calculate a daily score from nutrition totals and targets.

    Args:
        nutrition: Aggregated daily intake data.
        calorie_target: Plan's daily calorie target.
        protein_target_g: Plan's protein target in grams.
        body_weight_kg: For protein ceiling check (max 2.5g/kg).
        expected_meals: Expected number of meals (default 3).

    Returns:
        DailyScore with all deductions, final score, and grade.
    """
    score = 100
    events: List[ScoreEvent] = []
    breakdown: Dict[str, Any] = {
        "calories": {
            "actual": round(nutrition.total_calories, 1),
            "target": calorie_target,
        },
        "protein": {
            "actual": round(nutrition.total_protein_g, 1),
            "target": protein_target_g,
        },
        "deductions": [],
    }

    # ── 1. Calorie checks ──────────────────────────────────────────
    if calorie_target > 0:
        cal_ratio = nutrition.total_calories / calorie_target if calorie_target else 0
        breakdown["calories"]["ratio"] = round(cal_ratio, 3)

        if cal_ratio > 1 + CALORIE_OVER_SEVERE_PCT:
            pts = -15
            ev = ScoreEvent("calorie_over_severe", pts, "熱量嚴重超標（超過目標 20%）")
            events.append(ev)
            score += pts
        elif cal_ratio > 1 + CALORIE_OVER_MODERATE_PCT:
            pts = -8
            ev = ScoreEvent("calorie_over_moderate", pts, "熱量中度超標（超過目標 10–20%）")
            events.append(ev)
            score += pts
        elif cal_ratio > 1 + CALORIE_OVER_MILD_PCT:
            pts = -3
            ev = ScoreEvent("calorie_over_mild", pts, "熱量輕度超標（超過目標 5–10%）")
            events.append(ev)
            score += pts

        if cal_ratio < 1 - CALORIE_UNDER_SEVERE_PCT:
            pts = -12
            ev = ScoreEvent("calorie_under_severe", pts, "熱量嚴重不足（低於目標 25%）")
            events.append(ev)
            score += pts
        elif cal_ratio < 1 - CALORIE_UNDER_MODERATE_PCT:
            pts = -5
            ev = ScoreEvent("calorie_under_moderate", pts, "熱量中度不足（低於目標 15–25%）")
            events.append(ev)
            score += pts

    # ── 2. Protein checks ──────────────────────────────────────────
    if protein_target_g > 0:
        prot_ratio = nutrition.total_protein_g / protein_target_g
        breakdown["protein"]["ratio"] = round(prot_ratio, 3)

        if prot_ratio < PROTEIN_LOW_PCT:
            # -10 per 10% gap, max -20
            gap = PROTEIN_LOW_PCT - prot_ratio
            pts = min(-int(gap * 100), -20)  # -10 per 10pp gap → roughly
            # More precise: -10 per full 10% below 80%
            tens_below = int((PROTEIN_LOW_PCT - prot_ratio) * 10)
            pts = max(-20, tens_below * -10)
            if pts < 0:
                ev = ScoreEvent(
                    "protein_low", pts,
                    f"蛋白質不足（僅達成目標 {round(prot_ratio * 100)}%）"
                )
                events.append(ev)
                score += pts

        # Protein ceiling check
        if body_weight_kg > 0 and nutrition.total_protein_g > body_weight_kg * PROTEIN_MAX_G_PER_KG:
            pts = -5
            ev = ScoreEvent("protein_excess", pts, "蛋白質攝取過高（> 2.5g/kg 體重）")
            events.append(ev)
            score += pts

    # ── 3. Fiber check ─────────────────────────────────────────────
    if nutrition.total_fiber_g < FIBER_MIN_G and nutrition.total_calories > 0:
        pts = -5
        ev = ScoreEvent("fiber_low", pts, f"膳食纖維不足（僅 {round(nutrition.total_fiber_g, 1)}g，建議 ≥ 25g）")
        events.append(ev)
        score += pts

    # ── 4. Sodium check ────────────────────────────────────────────
    if nutrition.total_sodium_mg > SODIUM_MAX_MG:
        pts = -5
        ev = ScoreEvent("sodium_high", pts, "鈉攝取過高（超過 2300mg）")
        events.append(ev)
        score += pts

    # ── 5. Refined sugar check ─────────────────────────────────────
    if calorie_target > 0 and nutrition.refined_sugar_g > 0:
        sugar_cal = nutrition.refined_sugar_g * 4  # 4 kcal/g sugar
        sugar_pct = sugar_cal / calorie_target
        if sugar_pct > REFINED_SUGAR_MAX_PCT:
            pts = -5
            ev = ScoreEvent("refined_sugar_high", pts, "精緻糖攝取過高（> 總熱量 10%）")
            events.append(ev)
            score += pts

    # ── 6. Missing meals check ─────────────────────────────────────
    missing = expected_meals - nutrition.meal_count
    if missing > 0:
        # Cap at -15 (3 meals × -5)
        pts = max(-15, missing * -5)
        ev = ScoreEvent("missing_meals", pts, f"有 {missing} 餐未完整記錄")
        events.append(ev)
        score += pts

    # ── 7. Bonus: complete tracking & on target ────────────────────
    no_deductions = all(e.points >= 0 for e in events)
    on_target = calorie_target > 0 and abs(nutrition.total_calories - calorie_target) / calorie_target <= 0.10
    if no_deductions and on_target and nutrition.meal_count >= expected_meals:
        pts = DAILY_BONUS
        bonus = ScoreEvent("complete_on_target", pts, "記錄完整且達標！")
        score += pts
    else:
        bonus = None

    # Clamp
    score = max(0, min(100, score))

    breakdown["deductions"] = [
        {"type": e.event_type, "points": e.points, "description": e.description}
        for e in events
    ]
    if bonus:
        breakdown["bonus"] = {"points": bonus.points, "description": bonus.description}

    return DailyScore(
        user_id="",
        score_date="",
        base_score=100,
        deductions=events,
        bonus=bonus,
        final_score=score,
        grade=_classify_grade(score),
        breakdown=breakdown,
    )


# ---------------------------------------------------------------------------
# Weekly scoring
# ---------------------------------------------------------------------------

def score_weekly(
    daily_scores: List[int],
    daily_calorie_averages: List[float],
    calorie_target: int,
    goal_adherence_pct: float = 0.0,
    weight_change_kg: Optional[float] = 0.0,
    expected_weekly_change_kg: float = 0.0,
    food_category_coverage: float = 0.0,   # 0–1
    logged_days: int = 7,
    total_days: int = 7,
    weight_trend_available: bool = True,
) -> WeeklyScore:
    """
    Calculate a weekly score from 7 days of data.

    Args:
        daily_scores: 7 daily scores.
        daily_calorie_averages: Per-day calorie totals.
        calorie_target: Plan target.
        goal_adherence_pct: % of days within calorie target ±10%.
        weight_change_kg: Actual weight change this week.
        expected_weekly_change_kg: Expected change per plan (negative for loss).
        food_category_coverage: 0–1 coverage of 6 food categories.
        logged_days: Days with food records.
        total_days: Total days in period (default 7).

    Returns:
        WeeklyScore with weighted final score and grade.
    """
    n = len(daily_scores) if daily_scores else 1

    component_weights = {
        "daily_average": 0.50,
        "weight_trend": 0.20,
        "food_diversity": 0.15,
        "record_completeness": 0.15,
    }
    weight_trend_note = ""
    if weight_change_kg is None:
        weight_trend_available = False

    if not weight_trend_available:
        component_weights = {
            "daily_average": 0.60,
            "weight_trend": 0.0,
            "food_diversity": 0.20,
            "record_completeness": 0.20,
        }
        weight_trend_note = "本週無體重記錄，已將原 20% 體重趨勢權重重新分配到其他三項。"

    # ── 1. Daily average ───────────────────────────────────────────
    avg_daily = sum(daily_scores) / n
    daily_component = avg_daily * component_weights["daily_average"]

    # ── 2. Weight trend ────────────────────────────────────────────
    actual_change = weight_change_kg if weight_change_kg is not None else 0.0
    if not weight_trend_available:
        trend_score = -1
    elif abs(expected_weekly_change_kg) > 0.01:
        deviation = abs(actual_change - expected_weekly_change_kg)
        max_dev = max(abs(expected_weekly_change_kg) * 2, 0.5)
        trend_score = max(0, int(100 * (1 - min(deviation / max_dev, 1.0))))
    else:
        deviation = abs(actual_change)
        trend_score = max(0, int(100 * (1 - min(deviation / 0.5, 1.0))))
    weight_trend_component = trend_score * component_weights["weight_trend"]

    # ── 3. Food diversity ──────────────────────────────────────────
    diversity_score = int(food_category_coverage * 100)
    diversity_component = diversity_score * component_weights["food_diversity"]

    # ── 4. Record completeness ─────────────────────────────────────
    completeness_score = int((logged_days / total_days) * 100) if total_days > 0 else 0
    completeness_component = completeness_score * component_weights["record_completeness"]

    # ── Final ──────────────────────────────────────────────────────
    final = int(round(daily_component + weight_trend_component + diversity_component + completeness_component))
    final = max(0, min(100, final))

    cal_avg = sum(daily_calorie_averages) / len(daily_calorie_averages) if daily_calorie_averages else 0

    return WeeklyScore(
        user_id="",
        week_start="",
        daily_scores=list(daily_scores),
        avg_daily_score=round(avg_daily, 1),
        weight_trend_score=trend_score,
        diversity_score=diversity_score,
        completeness_score=completeness_score,
        final_score=final,
        grade=_classify_grade(final),
        weekly_calories_avg=round(cal_avg, 1),
        goal_adherence_pct=round(goal_adherence_pct, 1),
        weight_change_kg=round(actual_change, 2) if weight_change_kg is not None else None,
        weight_trend_available=weight_trend_available,
        weight_trend_note=weight_trend_note,
        component_weights=component_weights,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def persist_daily_score(
    db: DBManager,
    user_id: str,
    daily_score: DailyScore,
    summary_date: str,
) -> List[str]:
    """
    Write score_events rows and update daily_summaries.

    Returns list of inserted score_event IDs.
    """
    db.initialize()
    event_ids: List[str] = []

    # Insert score_events (ensure table exists)
    _ensure_score_events_table(db)

    # Deductions
    for ev in daily_score.deductions:
        eid = str(uuid.uuid4())
        db.execute(
            """INSERT INTO score_events (event_id, user_id, event_date, event_type, points, description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (eid, user_id, summary_date, ev.event_type, ev.points, ev.description),
        )
        event_ids.append(eid)

    # Bonus
    if daily_score.bonus:
        eid = str(uuid.uuid4())
        db.execute(
            """INSERT INTO score_events (event_id, user_id, event_date, event_type, points, description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (eid, user_id, summary_date, daily_score.bonus.event_type,
             daily_score.bonus.points, daily_score.bonus.description),
        )
        event_ids.append(eid)

    # Update daily_summaries
    breakdown_json = json.dumps(daily_score.breakdown, ensure_ascii=False)
    existing = db.fetch_one(
        "SELECT summary_id FROM daily_summaries WHERE user_id = ? AND summary_date = ?",
        (user_id, summary_date),
    )
    if existing:
        db.execute(
            "UPDATE daily_summaries SET daily_score = ?, score_breakdown = ? WHERE summary_id = ?",
            (daily_score.final_score, breakdown_json, existing["summary_id"]),
        )
    else:
        db.execute(
            """INSERT INTO daily_summaries (
                 summary_id, user_id, summary_date, daily_score, score_breakdown
               ) VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, summary_date, daily_score.final_score, breakdown_json),
        )

    return event_ids


def persist_weekly_score(
    db: DBManager,
    user_id: str,
    weekly_score: WeeklyScore,
) -> str:
    """
    Upsert weekly_summaries row.

    Returns the summary_id.
    """
    db.initialize()
    _ensure_score_events_table(db)

    report_json = json.dumps({
        "daily_scores": weekly_score.daily_scores,
        "avg_daily_score": weekly_score.avg_daily_score,
        "weight_trend_score": weekly_score.weight_trend_score,
        "weight_trend_available": weekly_score.weight_trend_available,
        "weight_trend_note": weekly_score.weight_trend_note,
        "diversity_score": weekly_score.diversity_score,
        "completeness_score": weekly_score.completeness_score,
        "component_weights": weekly_score.component_weights,
        "grade": weekly_score.grade,
    }, ensure_ascii=False)

    existing = db.fetch_one(
        "SELECT summary_id FROM weekly_summaries WHERE user_id = ? AND week_start_date = ?",
        (user_id, weekly_score.week_start),
    )
    if existing:
        db.execute(
            """UPDATE weekly_summaries SET
                 avg_daily_calories = ?, goal_adherence_pct = ?, weekly_score = ?,
                 weight_change_kg = ?, report_text = ?
               WHERE summary_id = ?""",
            (
                weekly_score.weekly_calories_avg,
                weekly_score.goal_adherence_pct,
                weekly_score.final_score,
                weekly_score.weight_change_kg,
                report_json,
                existing["summary_id"],
            ),
        )
        return existing["summary_id"]
    else:
        sid = str(uuid.uuid4())
        db.execute(
            """INSERT INTO weekly_summaries (
                 summary_id, user_id, week_start_date, avg_daily_calories,
                 goal_adherence_pct, weekly_score, weight_change_kg, report_text
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid, user_id, weekly_score.week_start,
                weekly_score.weekly_calories_avg,
                weekly_score.goal_adherence_pct,
                weekly_score.final_score,
                weekly_score.weight_change_kg,
                report_json,
            ),
        )
        return sid


def _ensure_score_events_table(db: DBManager) -> None:
    """Create score_events table if it doesn't exist (migration-safe)."""
    db.execute(
        """CREATE TABLE IF NOT EXISTS score_events (
            event_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            user_id TEXT REFERENCES users(user_id),
            event_date DATE,
            event_type VARCHAR(30),
            points INTEGER,
            description TEXT
        )"""
    )


# ---------------------------------------------------------------------------
# Aggregation helpers (query food_logs for DailyNutrition)
# ---------------------------------------------------------------------------

def get_daily_nutrition(
    db: DBManager,
    user_id: str,
    log_date: str,
) -> DailyNutrition:
    """
    Aggregate food_logs into a DailyNutrition for scoring.

    Args:
        db: Initialized DBManager.
        user_id: Target user.
        log_date: YYYY-MM-DD.

    Returns:
        DailyNutrition with totals and meal/item counts.
    """
    db.initialize()
    row = db.fetch_one(
        """SELECT
             COALESCE(SUM(calories), 0)      AS total_calories,
             COALESCE(SUM(protein_g), 0)     AS total_protein_g,
             COALESCE(SUM(carb_g), 0)        AS total_carb_g,
             COALESCE(SUM(fat_g), 0)         AS total_fat_g,
             COALESCE(SUM(fiber_g), 0)       AS total_fiber_g,
             COALESCE(SUM(sodium_mg), 0)     AS total_sodium_mg,
             COUNT(DISTINCT meal_type)       AS meal_count,
             COUNT(*)                         AS item_count
           FROM food_logs
           WHERE user_id = ? AND date(log_datetime) = ?
             AND food_name != '___MEAL_TOTAL___'""",
        (user_id, log_date),
    )
    if not row:
        return DailyNutrition()

    r = dict(row)
    return DailyNutrition(
        total_calories=float(r.get("total_calories") or 0),
        total_protein_g=float(r.get("total_protein_g") or 0),
        total_carb_g=float(r.get("total_carb_g") or 0),
        total_fat_g=float(r.get("total_fat_g") or 0),
        total_fiber_g=float(r.get("total_fiber_g") or 0),
        total_sodium_mg=float(r.get("total_sodium_mg") or 0),
        meal_count=int(r.get("meal_count") or 0),
        item_count=int(r.get("item_count") or 0),
    )


# ---------------------------------------------------------------------------
# Full daily scoring pipeline
# ---------------------------------------------------------------------------

def run_daily_scoring(
    db: DBManager,
    user_id: str,
    log_date: Optional[str] = None,
    calorie_target: Optional[int] = None,
    protein_target_g: Optional[int] = None,
    body_weight_kg: float = 0.0,
    adjusted_target: Optional[int] = None,
) -> DailyScore:
    """
    Full pipeline: aggregate nutrition → score → persist.

    If adjusted_target is not provided, checks daily_calorie_ledger for
    exercise-adjusted targets (Phase 6). If no ledger entry exists, uses
    the base plan target.
    """
    db.initialize()
    sd = log_date or date.today().isoformat()

    # Get nutrition
    nutrition = get_daily_nutrition(db, user_id, sd)

    # Resolve targets from active plan if not provided
    if calorie_target is None or protein_target_g is None:
        plan = db.get_active_plan(user_id)
        if plan:
            if calorie_target is None:
                calorie_target = int(plan["daily_calorie_target"] or 0)
            if protein_target_g is None:
                protein_target_g = int(plan["protein_target_g"] or 0)
            if body_weight_kg <= 0:
                body_weight_kg = float(plan["start_weight_kg"] or 0)
        else:
            calorie_target = calorie_target or 0
            protein_target_g = protein_target_g or 0

    # Phase 6: Check for exercise-adjusted target
    if adjusted_target is None:
        ledger = db.fetch_one(
            "SELECT adjusted_target FROM daily_calorie_ledger "
            "WHERE user_id = ? AND ledger_date = ?",
            (user_id, sd),
        )
        if ledger and ledger["adjusted_target"] and calorie_target:
            adjusted_target = ledger["adjusted_target"]
            # Record adjustment info for logging
            _log_scoring_message(
                f"[Phase 6] Using exercise-adjusted target: {calorie_target} → {adjusted_target}"
            )

    if adjusted_target and adjusted_target > 0:
        effective_target = adjusted_target
    else:
        effective_target = calorie_target or 0

    # Score against the effective (possibly adjusted) target
    result = score_daily(nutrition, effective_target, protein_target_g, body_weight_kg)
    result.user_id = user_id
    result.score_date = sd

    # Phase 6: Exercise bonus (+5 if exercise was logged)
    exercise_row = db.fetch_one(
        "SELECT COUNT(*) AS cnt FROM exercise_logs "
        "WHERE user_id = ? AND log_date = ?",
        (user_id, sd),
    )
    if exercise_row and exercise_row["cnt"] > 0:
        exercise_bonus = ScoreEvent("exercise_logged_bonus", 5, "🏃 有記錄運動，+5 分獎勵")
        result.bonus = exercise_bonus
        result.final_score = min(100, result.final_score + 5)
        if result.final_score >= 90:
            result.grade = "⭐ 優秀"
        elif result.final_score >= 75:
            result.grade = "良好"
        # bonus adjustments already scored, persist still uses final_score

    # Persist
    persist_daily_score(db, user_id, result, sd)

    return result


def _log_scoring_message(msg: str) -> None:
    """Internal structured logging helper."""
    import sys as _sys
    print(f"[scoring_engine] {msg}", file=_sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="HealthFit scoring engine")
    sub = parser.add_subparsers(dest="command")

    # ── score ──────────────────────────────────────────────────────
    score_parser = sub.add_parser("score", help="Score a single day")
    score_parser.add_argument("--user-id", required=True)
    score_parser.add_argument("--date", default=date.today().isoformat())
    score_parser.add_argument("--calorie-target", type=int, default=None)
    score_parser.add_argument("--protein-target", type=int, default=None)
    score_parser.add_argument("--body-weight-kg", type=float, default=0.0)
    score_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    # ── weekly ─────────────────────────────────────────────────────
    weekly_parser = sub.add_parser("weekly", help="Score a week")
    weekly_parser.add_argument("--user-id", required=True)
    weekly_parser.add_argument("--week-start", required=True, help="YYYY-MM-DD (Monday)")
    weekly_parser.add_argument("--calorie-target", type=int, default=0)
    weekly_parser.add_argument("--expected-weekly-change", type=float, default=0.0)
    weekly_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    args = parser.parse_args()
    db = DBManager(Path(args.db_path))

    if args.command == "score":
        result = run_daily_scoring(
            db, args.user_id, args.date,
            calorie_target=args.calorie_target,
            protein_target_g=args.protein_target,
            body_weight_kg=args.body_weight_kg,
        )
        print(f"{'='*50}")
        print(f"📊 每日評分 — {result.score_date}")
        print(f"{'='*50}")
        print(f"  基礎分：{result.base_score}")
        for ev in result.deductions:
            print(f"  {ev.description}：{ev.points:+d}")
        if result.bonus:
            print(f"  {result.bonus.description}：{result.bonus.points:+d}")
        print(f"  ──────────────────")
        print(f"  最終分數：{result.final_score} 分　{result.grade}")
        print(f"  詳細明細：{json.dumps(result.breakdown, ensure_ascii=False, indent=2)}")

    elif args.command == "weekly":
        # Collect 7 daily scores from DB
        ws_date = date.fromisoformat(args.week_start)
        daily_scores: List[int] = []
        daily_cals: List[float] = []
        adherence_days = 0

        for i in range(7):
            d = ws_date.fromordinal(ws_date.toordinal() + i).isoformat()
            row = db.fetch_one(
                "SELECT daily_score, total_calories FROM daily_summaries WHERE user_id = ? AND summary_date = ?",
                (args.user_id, d),
            )
            if row:
                s = int(row["daily_score"] or 0)
                daily_scores.append(s)
                c = float(row["total_calories"] or 0)
                daily_cals.append(c)
                if args.calorie_target > 0 and abs(c - args.calorie_target) / args.calorie_target <= 0.10:
                    adherence_days += 1
            else:
                daily_scores.append(0)
                daily_cals.append(0)

        logged_days = sum(1 for s in daily_scores if s > 0)
        adherence_pct = (adherence_days / 7) * 100 if args.calorie_target > 0 else 0

        ws = score_weekly(
            daily_scores, daily_cals, args.calorie_target,
            goal_adherence_pct=adherence_pct,
            weight_change_kg=0,
            expected_weekly_change_kg=args.expected_weekly_change,
            logged_days=logged_days,
            weight_trend_available=False,
        )

        print(f"{'='*50}")
        print(f"📈 每週評分 — {args.week_start} 起")
        print(f"{'='*50}")
        print(f"  每日分數：{ws.daily_scores}")
        print(f"  每日平均：{ws.avg_daily_score}")
        print(f"  體重趨勢分：{ws.weight_trend_score}")
        if ws.weight_trend_note:
            print(f"  備註：{ws.weight_trend_note}")
        print(f"  飲食多樣性分：{ws.diversity_score}")
        print(f"  記錄完整度分：{ws.completeness_score}")
        print(f"  ──────────────────")
        print(f"  最終分數：{ws.final_score} 分　{ws.grade}")
        print(f"  達標率：{ws.goal_adherence_pct}%")


if __name__ == "__main__":
    main()
