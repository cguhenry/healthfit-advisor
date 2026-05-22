#!/usr/bin/env python3
"""
calorie_tracker.py — Phase 4: Calorie tracking, DB persistence, and history comparison.

Wires Phase 3 food analysis results into the SQLite database:

1. log_meal_analysis()       — Write MealAnalysisResult → food_logs rows
2. upsert_daily_summary()     — Recalculate & persist daily_summaries
3. get_history_comparison()   — Compare today vs yesterday, last week, plan start

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
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FoodLogEntry:
    """A single food item ready for insertion into food_logs."""
    user_id: str
    meal_type: str                     # breakfast | lunch | dinner | snack
    food_name: str
    log_datetime: str                  # ISO-8601
    quantity_g: float = 0.0
    calories: float = 0.0
    protein_g: float = 0.0
    carb_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0
    sodium_mg: float = 0.0
    ai_confidence: float = 0.0
    food_db_source: str = "AI_EST"
    food_db_id: Optional[str] = None
    note: Optional[str] = None


@dataclass
class DailySummary:
    user_id: str
    summary_date: str                  # YYYY-MM-DD
    total_calories: float = 0.0
    total_protein_g: float = 0.0
    total_carb_g: float = 0.0
    total_fat_g: float = 0.0
    calorie_target: int = 0
    calorie_balance: float = 0.0       # positive = over target
    daily_score: Optional[int] = None
    score_breakdown: Optional[Dict[str, Any]] = None


@dataclass
class PeriodComparison:
    """Compare two periods of food logs (e.g., today vs same day last week)."""
    period_label: str
    current: Dict[str, Any]
    previous: Dict[str, Any]
    delta: Dict[str, Any]


# ---------------------------------------------------------------------------
# Meal logging
# ---------------------------------------------------------------------------

def log_meal_analysis(
    db: DBManager,
    user_id: str,
    meal_type: str,
    foods: List[Dict[str, Any]],
    total_nutrition: Optional[Dict[str, Any]] = None,
    log_datetime: Optional[str] = None,
    note: Optional[str] = None,
) -> List[str]:
    """
    Write food analysis result rows into food_logs.

    Args:
        db: Initialized DBManager.
        user_id: Target user.
        meal_type: breakfast | lunch | dinner | snack.
        foods: List of dicts with name, estimated_g, calories, protein_g,
               carb_g, fat_g, fiber_g, sodium_mg, confidence.
        total_nutrition: Optional overall nutrition dict (logged as a summary row
                         with food_name "___MEAL_TOTAL___").
        log_datetime: ISO-8601 timestamp; defaults to now (UTC).
        note: Optional free-text note attached to each row.

    Returns:
        List of inserted log_ids.
    """
    db.initialize()
    ts = log_datetime or datetime.now(timezone.utc).isoformat()
    inserted: List[str] = []

    for food in foods:
        log_id = str(uuid.uuid4())
        calories = float(food.get("calories") or 0)
        protein_g = float(food.get("protein_g") or 0)
        carb_g = float(food.get("carb_g") or 0)
        fat_g = float(food.get("fat_g") or 0)
        fiber_g = float(food.get("fiber_g") or 0)
        sodium_mg = float(food.get("sodium_mg") or 0)
        conf = float(food.get("confidence") or 0)
        estimated_g = float(food.get("estimated_g") or 0)
        food_name = str(food.get("name") or "未知食物")

        db.execute(
            """INSERT INTO food_logs (
                log_id, user_id, meal_type, log_datetime, food_name,
                quantity_g, calories, protein_g, carb_g, fat_g,
                fiber_g, sodium_mg, ai_confidence, food_db_source, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log_id, user_id, meal_type, ts, food_name,
                estimated_g, calories, protein_g, carb_g, fat_g,
                fiber_g, sodium_mg, conf,
                food.get("food_db_source", "AI_EST"),
                note,
            ),
        )
        inserted.append(log_id)

    # Optional: insert a meal-total summary row for aggregation convenience
    if total_nutrition:
        log_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO food_logs (
                log_id, user_id, meal_type, log_datetime, food_name,
                quantity_g, calories, protein_g, carb_g, fat_g,
                fiber_g, sodium_mg, ai_confidence, food_db_source, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log_id, user_id, meal_type, ts, "___MEAL_TOTAL___",
                0,
                float(total_nutrition.get("calories") or 0),
                float(total_nutrition.get("protein_g") or 0),
                float(total_nutrition.get("carb_g") or 0),
                float(total_nutrition.get("fat_g") or 0),
                float(total_nutrition.get("fiber_g") or 0),
                float(total_nutrition.get("sodium_mg") or 0),
                float(total_nutrition.get("confidence") or 0),
                "AI_EST",
                note,
            ),
        )
        inserted.append(log_id)

    return inserted


def _log_food_by_date(
    db: DBManager, user_id: str, log_date: str
) -> List[Dict[str, Any]]:
    """Return raw food_log rows for a given date (excluding ___MEAL_TOTAL___ rows)."""
    return [
        dict(row)
        for row in db.connect().execute(
            """SELECT * FROM food_logs
               WHERE user_id = ? AND date(log_datetime) = ?
                 AND food_name != '___MEAL_TOTAL___'
               ORDER BY log_datetime""",
            (user_id, log_date),
        ).fetchall()
    ]


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------

def upsert_daily_summary(
    db: DBManager,
    user_id: str,
    summary_date: Optional[str] = None,
    calorie_target: int = 0,
) -> DailySummary:
    """
    Recalculate today's (or a given date's) total from food_logs and
    upsert into daily_summaries.

    Returns the computed DailySummary.
    """
    db.initialize()
    sd = summary_date or date.today().isoformat()

    # Aggregate from food_logs (exclude ___MEAL_TOTAL___ to avoid double-counting)
    row = db.fetch_one(
        """SELECT
             COALESCE(SUM(calories), 0)      AS total_calories,
             COALESCE(SUM(protein_g), 0)     AS total_protein_g,
             COALESCE(SUM(carb_g), 0)        AS total_carb_g,
             COALESCE(SUM(fat_g), 0)         AS total_fat_g
           FROM food_logs
           WHERE user_id = ? AND date(log_datetime) = ?
             AND food_name != '___MEAL_TOTAL___'""",
        (user_id, sd),
    )
    totals = dict(row) if row else {}

    total_cal = float(totals.get("total_calories") or 0.0)
    total_prot = float(totals.get("total_protein_g") or 0.0)
    total_carb = float(totals.get("total_carb_g") or 0.0)
    total_fat = float(totals.get("total_fat_g") or 0.0)
    balance = total_cal - calorie_target

    # Upsert
    summary_id: Optional[str] = None
    existing = db.fetch_one(
        "SELECT summary_id FROM daily_summaries WHERE user_id = ? AND summary_date = ?",
        (user_id, sd),
    )
    if existing:
        summary_id = existing["summary_id"]
        db.execute(
            """UPDATE daily_summaries SET
                 total_calories = ?, total_protein_g = ?, total_carb_g = ?,
                 total_fat_g = ?, calorie_target = ?, calorie_balance = ?
               WHERE summary_id = ?""",
            (total_cal, total_prot, total_carb, total_fat, calorie_target, balance, summary_id),
        )
    else:
        summary_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO daily_summaries (
                 summary_id, user_id, summary_date, total_calories,
                 total_protein_g, total_carb_g, total_fat_g,
                 calorie_target, calorie_balance
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (summary_id, user_id, sd, total_cal, total_prot, total_carb, total_fat, calorie_target, balance),
        )

    return DailySummary(
        user_id=user_id,
        summary_date=sd,
        total_calories=round(total_cal, 1),
        total_protein_g=round(total_prot, 1),
        total_carb_g=round(total_carb, 1),
        total_fat_g=round(total_fat, 1),
        calorie_target=calorie_target,
        calorie_balance=round(balance, 1),
    )


def get_daily_summary(
    db: DBManager, user_id: str, summary_date: Optional[str] = None
) -> Optional[DailySummary]:
    """Read a daily_summaries row; returns None if not found."""
    sd = summary_date or date.today().isoformat()
    row = db.fetch_one(
        "SELECT * FROM daily_summaries WHERE user_id = ? AND summary_date = ?",
        (user_id, sd),
    )
    if not row:
        return None
    r = dict(row)
    return DailySummary(
        user_id=r["user_id"],
        summary_date=r["summary_date"],
        total_calories=float(r.get("total_calories") or 0),
        total_protein_g=float(r.get("total_protein_g") or 0),
        total_carb_g=float(r.get("total_carb_g") or 0),
        total_fat_g=float(r.get("total_fat_g") or 0),
        calorie_target=int(r.get("calorie_target") or 0),
        calorie_balance=float(r.get("calorie_balance") or 0),
        daily_score=r.get("daily_score"),
        score_breakdown=json.loads(r["score_breakdown"]) if r.get("score_breakdown") else None,
    )


# ---------------------------------------------------------------------------
# History comparison
# ---------------------------------------------------------------------------

def get_history_comparison(
    db: DBManager,
    user_id: str,
    today: Optional[date] = None,
) -> List[PeriodComparison]:
    """
    Compare today's intake against multiple historical periods.

    Returns a list of PeriodComparison objects for:
      - vs yesterday
      - vs same day last week
      - vs 7-day trailing average
      - vs plan start (first food_log date)

    Each comparison includes the current and previous period totals + deltas.
    """
    db.initialize()
    td = today or date.today()
    comparisons: List[PeriodComparison] = []

    # ── Helper: get daily totals by querying food_logs directly ───
    def _daily_totals(d: date) -> Dict[str, Any]:
        ds = d.isoformat()
        row = db.fetch_one(
            """SELECT
                 COALESCE(SUM(calories), 0)    AS calories,
                 COALESCE(SUM(protein_g), 0)   AS protein_g,
                 COALESCE(SUM(carb_g), 0)      AS carb_g,
                 COALESCE(SUM(fat_g), 0)       AS fat_g,
                 COUNT(*)                       AS items
               FROM food_logs
               WHERE user_id = ? AND date(log_datetime) = ?
                 AND food_name != '___MEAL_TOTAL___'""",
            (user_id, ds),
        )
        return dict(row) if row else {"calories": 0, "protein_g": 0, "carb_g": 0, "fat_g": 0, "items": 0}

    def _period_totals(start: date, end: date) -> Dict[str, Any]:
        row = db.fetch_one(
            """SELECT
                 COALESCE(SUM(calories), 0)    AS calories,
                 COALESCE(SUM(protein_g), 0)   AS protein_g,
                 COALESCE(SUM(carb_g), 0)      AS carb_g,
                 COALESCE(SUM(fat_g), 0)       AS fat_g,
                 COUNT(DISTINCT date(log_datetime)) AS days
               FROM food_logs
               WHERE user_id = ? AND date(log_datetime) BETWEEN ? AND ?
                 AND food_name != '___MEAL_TOTAL___'""",
            (user_id, start.isoformat(), end.isoformat()),
        )
        r = dict(row) if row else {}
        days = max(int(r.get("days") or 0), 1)
        return {
            "calories": round(float(r.get("calories") or 0) / days, 1),
            "protein_g": round(float(r.get("protein_g") or 0) / days, 1),
            "carb_g": round(float(r.get("carb_g") or 0) / days, 1),
            "fat_g": round(float(r.get("fat_g") or 0) / days, 1),
            "days": days,
        }

    def _calc_delta(curr: Dict, prev: Dict) -> Dict:
        delta = {}
        for k in ("calories", "protein_g", "carb_g", "fat_g"):
            cur_v = float(curr.get(k) or 0)
            prev_v = float(prev.get(k) or 0)
            diff = round(cur_v - prev_v, 1)
            pct = round((diff / prev_v * 100), 1) if prev_v else 0.0
            delta[k] = {"absolute": diff, "pct": pct}
        return delta

    today_totals = _daily_totals(td)

    # 1) vs yesterday
    yday = td.replace(day=td.day - 1) if td.day > 1 else td
    yday_totals = _daily_totals(yday)
    comparisons.append(
        PeriodComparison(
            period_label="vs 昨日",
            current={"date": td.isoformat(), **today_totals},
            previous={"date": yday.isoformat(), **yday_totals},
            delta=_calc_delta(today_totals, yday_totals),
        )
    )

    # 2) vs same day last week
    import datetime as dt_mod
    last_week = td - dt_mod.timedelta(days=7)
    lw_totals = _daily_totals(last_week)
    comparisons.append(
        PeriodComparison(
            period_label="vs 上週同一天",
            current={"date": td.isoformat(), **today_totals},
            previous={"date": last_week.isoformat(), **lw_totals},
            delta=_calc_delta(today_totals, lw_totals),
        )
    )

    # 3) vs 7-day trailing average (prev 7 days excluding today)
    avg_start = td - dt_mod.timedelta(days=8)
    avg_end = td - dt_mod.timedelta(days=1)
    trailing_avg = _period_totals(avg_start, avg_end)
    comparisons.append(
        PeriodComparison(
            period_label="vs 過去 7 天平均",
            current={"date": td.isoformat(), **today_totals},
            previous={"period": f"{avg_start.isoformat()} ~ {avg_end.isoformat()}", **trailing_avg},
            delta=_calc_delta(today_totals, trailing_avg),
        )
    )

    # 4) vs plan start (first recorded food_log)
    first_log = db.fetch_one(
        """SELECT date(log_datetime) AS first_date
           FROM food_logs WHERE user_id = ? AND food_name != '___MEAL_TOTAL___'
           ORDER BY log_datetime LIMIT 1""",
        (user_id,),
    )
    if first_log:
        first_date = str(first_log["first_date"])
        plan_start_totals = _daily_totals(date.fromisoformat(first_date))
        comparisons.append(
            PeriodComparison(
                period_label=f"vs 計劃起始日（{first_date}）",
                current={"date": td.isoformat(), **today_totals},
                previous={"date": first_date, **plan_start_totals},
                delta=_calc_delta(today_totals, plan_start_totals),
            )
        )

    return comparisons


# ---------------------------------------------------------------------------
# Recent trend (rolling 7-day)
# ---------------------------------------------------------------------------

def get_recent_trend(
    db: DBManager, user_id: str, days: int = 7, end_date: Optional[date] = None
) -> List[Dict[str, Any]]:
    """
    Return per-day calorie/protein totals for the last `days` days.

    Useful for sparkline-style trend display.
    """
    db.initialize()
    ed = end_date or date.today()
    sd = ed.replace(day=ed.day - days + 1) if ed.day > days else ed

    rows = db.connect().execute(
        """SELECT date(log_datetime) AS d,
                  COALESCE(SUM(calories), 0)   AS calories,
                  COALESCE(SUM(protein_g), 0)  AS protein_g
           FROM food_logs
           WHERE user_id = ? AND date(log_datetime) BETWEEN ? AND ?
             AND food_name != '___MEAL_TOTAL___'
           GROUP BY date(log_datetime)
           ORDER BY d""",
        (user_id, sd.isoformat(), ed.isoformat()),
    ).fetchall()

    # Fill in missing days with zeros
    result_map: Dict[str, Dict] = {
        r["d"]: {"date": r["d"], "calories": float(r["calories"]), "protein_g": float(r["protein_g"])}
        for r in rows
    }
    trend: List[Dict] = []
    import datetime as dt_mod
    current = sd
    while current <= ed:
        ds = current.isoformat()
        trend.append(result_map.get(ds, {"date": ds, "calories": 0.0, "protein_g": 0.0}))
        current += dt_mod.timedelta(days=1)

    return trend


# ---------------------------------------------------------------------------
# Calorie progress toward daily target
# ---------------------------------------------------------------------------

def get_calorie_progress(
    db: DBManager, user_id: str, target_plan_id: Optional[str] = None, log_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Return a compact calorie progress snapshot:
      - consumed / target / remaining
      - protein consumed / target
      - meal breakdown (breakfast / lunch / dinner / snack)

    If target_plan_id is not provided, reads the active weight_plan.
    """
    db.initialize()
    sd = log_date or date.today().isoformat()

    # Get calorie target from active plan
    plan = db.get_active_plan(user_id) if not target_plan_id else db.fetch_one(
        "SELECT * FROM weight_plans WHERE plan_id = ?", (target_plan_id,)
    )
    if not plan:
        # Fallback: try daily_summaries
        existing = get_daily_summary(db, user_id, sd)
        calorie_target = existing.calorie_target if existing else 0
        protein_target = 0
    else:
        calorie_target = int(plan["daily_calorie_target"] or 0)
        protein_target = int(plan["protein_target_g"] or 0)

    # Per-meal breakdown (exclude ___MEAL_TOTAL___)
    rows = db.connect().execute(
        """SELECT meal_type,
                  COALESCE(SUM(calories), 0)   AS calories,
                  COALESCE(SUM(protein_g), 0)  AS protein_g
           FROM food_logs
           WHERE user_id = ? AND date(log_datetime) = ?
             AND food_name != '___MEAL_TOTAL___'
           GROUP BY meal_type""",
        (user_id, sd),
    ).fetchall()

    meal_breakdown: Dict[str, Dict] = {}
    total_consumed = 0.0
    total_protein = 0.0
    for r in rows:
        mt = r["meal_type"]
        cal = float(r["calories"])
        prot = float(r["protein_g"])
        meal_breakdown[mt] = {"calories": round(cal, 1), "protein_g": round(prot, 1)}
        total_consumed += cal
        total_protein += prot

    return {
        "date": sd,
        "calorie_target": calorie_target,
        "calories_consumed": round(total_consumed, 1),
        "calories_remaining": round(calorie_target - total_consumed, 1),
        "progress_pct": round(total_consumed / calorie_target * 100, 1) if calorie_target else 0.0,
        "protein_target_g": protein_target,
        "protein_consumed_g": round(total_protein, 1),
        "protein_remaining_g": round(protein_target - total_protein, 1),
        "meal_breakdown": meal_breakdown,
    }


# ---------------------------------------------------------------------------
# Formatted output (human-readable)
# ---------------------------------------------------------------------------

def format_progress(progress: Dict[str, Any]) -> str:
    """Render a calorie progress snapshot as a readable string."""
    lines = [
        f"📊 熱量追蹤 — {progress['date']}",
        "",
        f"🍽️ 已攝取：{progress['calories_consumed']:.0f} kcal / 目標 {progress['calorie_target']} kcal",
        f"   剩餘：{progress['calories_remaining']:+.0f} kcal（{progress['progress_pct']:.0f}%）",
        f"🥩 蛋白質：{progress['protein_consumed_g']:.0f}g / 目標 {progress['protein_target_g']}g",
        "",
    ]

    breakdown = progress.get("meal_breakdown", {})
    if breakdown:
        lines.append("餐次明細：")
        for mt in ("breakfast", "lunch", "dinner", "snack"):
            if mt in breakdown:
                m = breakdown[mt]
                mt_label = {"breakfast": "🍳 早餐", "lunch": "🍱 午餐", "dinner": "🍲 晚餐", "snack": "🍪 點心"}.get(mt, mt)
                lines.append(
                    f"  {mt_label}：{m['calories']:.0f} kcal｜蛋白質 {m['protein_g']:.0f}g"
                )

    return "\n".join(lines)


def format_comparison(comparisons: List[PeriodComparison]) -> str:
    """Render history comparisons as a readable string."""
    lines = ["📈 歷史對比"]
    for c in comparisons:
        lines.append(f"\n{c.period_label}：")
        curr = c.current
        prev = c.previous
        delta = c.delta

        cur_cal = float(curr.get("calories") or 0)
        prev_cal = float(prev.get("calories") or 0)
        d = delta.get("calories", {})
        diff = d.get("absolute", 0)
        pct = d.get("pct", 0)
        arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        lines.append(
            f"  熱量：{cur_cal:.0f} kcal（{arrow} {abs(diff):.0f} kcal，{pct:+.1f}% vs 前期 {prev_cal:.0f} kcal）"
        )

        cur_prot = float(curr.get("protein_g") or 0)
        prev_prot = float(prev.get("protein_g") or 0)
        dp = delta.get("protein_g", {})
        lines.append(
            f"  蛋白質：{cur_prot:.0f}g（{'+' if dp.get('absolute', 0) >= 0 else ''}{dp.get('absolute', 0):.0f}g vs 前期 {prev_prot:.0f}g）"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Phase 4 calorie tracker — log, summarize, compare.")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── log ────────────────────────────────────────────────────────────
    log_parser = sub.add_parser("log", help="Log a food analysis result from JSON file")
    log_parser.add_argument("json_file", help="Path to JSON file with food analysis result")
    log_parser.add_argument("--user-id", required=True)
    log_parser.add_argument("--meal-type", default="lunch")
    log_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    # ── summary ────────────────────────────────────────────────────────
    sum_parser = sub.add_parser("summary", help="Recalculate and show daily summary")
    sum_parser.add_argument("--user-id", required=True)
    sum_parser.add_argument("--date", default=date.today().isoformat())
    sum_parser.add_argument("--calorie-target", type=int, default=0)
    sum_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    # ── compare ────────────────────────────────────────────────────────
    cmp_parser = sub.add_parser("compare", help="Compare today vs historical periods")
    cmp_parser.add_argument("--user-id", required=True)
    cmp_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    # ── trend ──────────────────────────────────────────────────────────
    trend_parser = sub.add_parser("trend", help="Show 7-day rolling trend")
    trend_parser.add_argument("--user-id", required=True)
    trend_parser.add_argument("--days", type=int, default=7)
    trend_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    # ── progress ───────────────────────────────────────────────────────
    prog_parser = sub.add_parser("progress", help="Show calorie progress toward daily target")
    prog_parser.add_argument("--user-id", required=True)
    prog_parser.add_argument("--date", default=date.today().isoformat())
    prog_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))

    args = parser.parse_args()
    db = DBManager(Path(args.db_path))

    if args.command == "log":
        payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        foods = payload.get("foods", payload.get("consumed_foods", []))
        total = payload.get("total_nutrition", payload.get("total_consumed"))
        note = payload.get("note")
        ts = payload.get("log_datetime")

        inserted = log_meal_analysis(
            db, args.user_id, args.meal_type, foods, total, log_datetime=ts, note=note
        )
        print(f"✅ Logged {len(inserted)} rows")
        for lid in inserted:
            print(f"   {lid}")

    elif args.command == "summary":
        summary = upsert_daily_summary(db, args.user_id, args.date, args.calorie_target)
        print(json.dumps(
            {
                "date": summary.summary_date,
                "total_calories": summary.total_calories,
                "total_protein_g": summary.total_protein_g,
                "total_carb_g": summary.total_carb_g,
                "total_fat_g": summary.total_fat_g,
                "calorie_target": summary.calorie_target,
                "calorie_balance": summary.calorie_balance,
            },
            indent=2, ensure_ascii=False,
        ))

    elif args.command == "compare":
        comparisons = get_history_comparison(db, args.user_id)
        for c in comparisons:
            print(f"\n{c.period_label}")
            print(f"  當前：{json.dumps(c.current, ensure_ascii=False)}")
            print(f"  前期：{json.dumps(c.previous, ensure_ascii=False)}")
            print(f"  差異：{json.dumps(c.delta, ensure_ascii=False)}")

    elif args.command == "trend":
        trend = get_recent_trend(db, args.user_id, args.days)
        for day in trend:
            print(json.dumps(day, ensure_ascii=False))

    elif args.command == "progress":
        progress = get_calorie_progress(db, args.user_id, log_date=args.date)
        print(format_progress(progress))


if __name__ == "__main__":
    main()