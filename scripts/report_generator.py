#!/usr/bin/env python3
"""
report_generator.py — Phase 5: Daily & weekly report generator.

Produces human-readable daily and weekly reports by aggregating data from:
- calorie_tracker (progress, history comparison)
- scoring_engine (daily/weekly scores)
- DB (plans, weight logs, food logs)

All functions are stateless: pass in a DBManager, user_id, and optional parameters.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Ensure sibling scripts are importable ───────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager
from calorie_tracker import get_calorie_progress, get_history_comparison, get_recent_trend
from scoring_engine import (
    DailyNutrition, DailyScore, WeeklyScore, ScoreEvent,
    get_daily_nutrition, score_daily, score_weekly,
    run_daily_scoring, persist_daily_score, persist_weekly_score,
)


# ═══════════════════════════════════════════════════════════════════════════
# Daily report
# ═══════════════════════════════════════════════════════════════════════════

def generate_daily_report(
    db: DBManager,
    user_id: str,
    report_date: Optional[str] = None,
) -> str:
    """
    Generate a full daily health report.

    Includes:
    - Date / plan summary
    - Calorie & macro progress (by meal)
    - Daily score with breakdown
    - Comparison vs yesterday
    - Recommendations

    Args:
        db: Initialized DBManager.
        user_id: Target user.
        report_date: YYYY-MM-DD (defaults to today).

    Returns:
        Formatted text report (traditional Chinese).
    """
    db.initialize()
    rd = report_date or date.today().isoformat()

    # ── Get active plan ──────────────────────────────────────────────
    plan = db.get_active_plan(user_id)
    plan_name = plan["goal_type"] if plan else "無"
    plan_name = {"loss": "減重", "gain": "增肌", "maintain": "維持"}.get(plan_name, plan_name)
    calorie_target = int(plan["daily_calorie_target"] or 0) if plan else 0
    protein_target = int(plan["protein_target_g"] or 0) if plan else 0
    carb_target = int(plan["carb_target_g"] or 0) if plan else 0
    fat_target = int(plan["fat_target_g"] or 0) if plan else 0

    # ── Get progress (meal-by-meal) ──────────────────────────────────
    progress = get_calorie_progress(db, user_id, log_date=rd)

    # ── Get daily score ──────────────────────────────────────────────
    daily_score = run_daily_scoring(db, user_id, rd)

    # ── History comparison ───────────────────────────────────────────
    comps = get_history_comparison(db, user_id, today=date.fromisoformat(rd) if rd else date.today())

    # ── Build report ─────────────────────────────────────────────────
    lines: List[str] = []
    _h(lines, f"📊 每日健康報告 — {rd}")
    lines.append("")

    # Plan bar
    lines.append(f"🎯 目標：{plan_name}　｜　每日 {calorie_target} kcal")
    if protein_target:
        lines.append(f"    蛋白質 {protein_target}g / 碳水 {carb_target}g / 脂肪 {fat_target}g")
    lines.append("")

    # ── Progress section ─────────────────────────────────────────────
    _h(lines, "🍽️ 今日飲食記錄", level=2)
    lines.append("")
    _meal_progress(lines, progress)
    lines.append("")

    # ── Score section ────────────────────────────────────────────────
    _h(lines, "⭐ 每日評分", level=2)
    lines.append("")
    lines.append(f"  分數：{daily_score.final_score} 分　{daily_score.grade}")

    if daily_score.deductions:
        lines.append("")
        lines.append("  扣分項目：")
        for ev in daily_score.deductions:
            lines.append(f"    {ev.description}（{ev.points:+d}）")
    if daily_score.bonus:
        lines.append(f"  ✨ {daily_score.bonus.description}（{daily_score.bonus.points:+d}）")
    lines.append("")

    # ── Comparison section ───────────────────────────────────────────
    _h(lines, "📈 歷史對比", level=2)
    lines.append("")
    _comparison_lines(lines, comps, calorie_target)
    lines.append("")

    # ── Recommendations ──────────────────────────────────────────────
    _h(lines, "💡 建議", level=2)
    lines.append("")
    _daily_recommendations(lines, daily_score, progress, comps, calorie_target, protein_target)
    lines.append("")

    # ── Footer ───────────────────────────────────────────────────────
    lines.append("─" * 40)
    lines.append("HealthFit Advisor · 每日自動生成 · AI 健康顧問")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Weekly report
# ═══════════════════════════════════════════════════════════════════════════

def generate_weekly_report(
    db: DBManager,
    user_id: str,
    week_start_date: Optional[str] = None,
) -> str:
    """
    Generate a full weekly health report.

    Includes:
    - Week range / plan summary
    - 7-day daily scores overview
    - Calorie & macro trend chart (text)
    - Weight change (if logged)
    - Weekly score with breakdown
    - Goal adherence analysis
    - Next-week recommendations

    Args:
        db: Initialized DBManager.
        user_id: Target user.
        week_start_date: YYYY-MM-DD Monday (defaults to current week's Monday).

    Returns:
        Formatted text report (traditional Chinese).
    """
    db.initialize()

    # ── Determine week range ─────────────────────────────────────────
    today = date.today()
    if week_start_date:
        ws_date = date.fromisoformat(week_start_date)
    else:
        # Current week's Monday
        ws_date = today - timedelta(days=today.weekday())
    we_date = ws_date + timedelta(days=6)

    if we_date > today:
        we_date = today  # Don't go past today

    week_dates = [
        (ws_date + timedelta(days=i)).isoformat()
        for i in range((we_date - ws_date).days + 1)
    ]

    # ── Get active plan ──────────────────────────────────────────────
    plan = db.get_active_plan(user_id)
    plan_name = plan["goal_type"] if plan else "無"
    plan_name = {"loss": "減重", "gain": "增肌", "maintain": "維持"}.get(plan_name, plan_name)
    calorie_target = int(plan["daily_calorie_target"] or 0) if plan else 0
    protein_target = int(plan["protein_target_g"] or 0) if plan else 0
    weekly_change_expected = float(plan["weekly_change_kg"] or 0) if plan else 0

    # ── Collect daily data ───────────────────────────────────────────
    daily_scores: List[int] = []
    daily_cals: List[float] = []
    daily_prot: List[float] = []
    daily_data: List[Dict[str, Any]] = []
    adherence_days = 0

    for d in week_dates:
        nutrition = get_daily_nutrition(db, user_id, d)
        daily_data.append({
            "date": d,
            "calories": nutrition.total_calories,
            "protein": nutrition.total_protein_g,
            "meals": nutrition.meal_count,
        })

        # Score each day
        result = score_daily(
            nutrition, calorie_target, protein_target,
            body_weight_kg=float(plan["start_weight_kg"] or 0) if plan else 0,
        )
        # Persist
        persist_daily_score(db, user_id, result, d)

        daily_scores.append(result.final_score)
        daily_cals.append(nutrition.total_calories)
        daily_prot.append(nutrition.total_protein_g)

        if calorie_target > 0 and abs(nutrition.total_calories - calorie_target) / calorie_target <= 0.10:
            adherence_days += 1

    logged_days = sum(1 for c in daily_cals if c > 0)
    total_days = len(week_dates)
    adherence_pct = (adherence_days / total_days) * 100 if calorie_target > 0 else 0

    # ── Weight change ────────────────────────────────────────────────
    weight_change = _get_week_weight_change(db, user_id, ws_date, we_date)

    # ── Weekly score ─────────────────────────────────────────────────
    ws = score_weekly(
        daily_scores, daily_cals, calorie_target,
        goal_adherence_pct=adherence_pct,
        weight_change_kg=weight_change,
        expected_weekly_change_kg=weekly_change_expected,
        logged_days=logged_days,
        total_days=total_days,
    )

    # Persist
    ws.user_id = user_id
    ws.week_start = ws_date.isoformat()
    persist_weekly_score(db, user_id, ws)

    # ── Build report ─────────────────────────────────────────────────
    lines: List[str] = []
    _h(lines, f"📈 每週健康報告 — {ws_date.isoformat()}（一）至 {we_date.isoformat()}（日）")
    lines.append("")

    lines.append(f"🎯 目標：{plan_name}　｜　每日 {calorie_target} kcal")
    if weekly_change_expected != 0:
        direction = "減" if weekly_change_expected < 0 else "增"
        lines.append(f"    預期每週{direction}重 {abs(weekly_change_expected):.2f} kg")
    lines.append("")

    # ── Daily scores bar ─────────────────────────────────────────────
    _h(lines, "📊 每日分數總覽", level=2)
    lines.append("")
    _daily_score_bar(lines, daily_scores, week_dates)
    lines.append("")
    lines.append(f"  平均分數：{ws.avg_daily_score}　｜　達標率：{adherence_pct:.0f}%")

    # Highlight best / worst day
    if daily_scores:
        max_score = max(daily_scores)
        max_day_idx = daily_scores.index(max_score)
        lines.append(f"  🏆 最佳日：{week_dates[max_day_idx]}（{max_score} 分）")
        # Find worst day (lowest positive score)
        positive_scores = [s for s in daily_scores if s > 0]
        if positive_scores:
            min_score = min(positive_scores)
            if min_score < max_score:
                min_idx = daily_scores.index(min_score)
                lines.append(f"  ⚠️ 需注意日：{week_dates[min_idx]}（{min_score} 分）")
    lines.append("")

    # ── Calorie chart ────────────────────────────────────────────────
    _h(lines, "🔥 每日熱量趨勢", level=2)
    lines.append("")
    _calorie_chart(lines, daily_cals, week_dates, calorie_target)
    lines.append("")

    # ── Weight section ───────────────────────────────────────────────
    _h(lines, "⚖️ 體重變化", level=2)
    lines.append("")
    if weight_change is not None:
        direction_sym = "⬇️" if weight_change < 0 else ("⬆️" if weight_change > 0 else "➡️")
        lines.append(f"  本週變化：{direction_sym} {weight_change:+.2f} kg")
        if weekly_change_expected != 0:
            diff = weight_change - weekly_change_expected
            if abs(diff) < 0.2:
                lines.append(f"  ✅ 符合預期（預期 {weekly_change_expected:+.2f} kg）")
            elif (weight_change < 0 and weekly_change_expected < 0 and weight_change < weekly_change_expected) or \
                 (weight_change > 0 and weekly_change_expected > 0 and weight_change > weekly_change_expected):
                lines.append(f"  ⚠️ 超出預期（預期 {weekly_change_expected:+.2f} kg）")
            else:
                lines.append(f"  🔸 低於預期（預期 {weekly_change_expected:+.2f} kg）")
    else:
        lines.append("  尚無體重記錄")
    lines.append("")

    # ── Weekly score ─────────────────────────────────────────────────
    _h(lines, "⭐ 每週評分", level=2)
    lines.append("")
    lines.append(f"  總分：{ws.final_score} 分　{ws.grade}")
    lines.append("")
    lines.append(f"  ┌─────────────────────┬────────┬────────┐")
    lines.append(f"  │ 項目                │ 分數   │ 權重   │")
    lines.append(f"  ├─────────────────────┼────────┼────────┤")
    lines.append(f"  │ 每日評分平均        │ {ws.avg_daily_score:5.0f}  │  50%   │")
    lines.append(f"  │ 體重趨勢            │ {ws.weight_trend_score:5d}  │  20%   │")
    lines.append(f"  │ 飲食多樣性          │ {ws.diversity_score:5d}  │  15%   │")
    lines.append(f"  │ 記錄完整度          │ {ws.completeness_score:5d}  │  15%   │")
    lines.append(f"  └─────────────────────┴────────┴────────┘")
    lines.append("")

    # ── Recommendations ──────────────────────────────────────────────
    _h(lines, "💡 下週建議", level=2)
    lines.append("")
    _weekly_recommendations(lines, daily_data, daily_scores, ws, calorie_target, protein_target)
    lines.append("")

    # ── Footer ───────────────────────────────────────────────────────
    lines.append("─" * 40)
    lines.append("HealthFit Advisor · 每週自動生成 · AI 健康顧問")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Formatter helpers
# ═══════════════════════════════════════════════════════════════════════════

def _h(lines: List[str], text: str, level: int = 1) -> None:
    """Add a heading line."""
    prefix = {1: "", 2: "  "}.get(level, "")
    lines.append(f"{prefix}{text}")


def _meal_progress(lines: List[str], progress: Dict[str, Any]) -> None:
    """Append per-meal breakdown lines."""
    if not progress:
        lines.append("  （尚無今日記錄）")
        return

    calorie_target = progress.get("calorie_target", 0)
    total_cal = progress.get("calories_consumed", 0)
    total_prot = progress.get("protein_consumed_g", 0)
    pct = f"{(total_cal / calorie_target * 100):.0f}%" if calorie_target > 0 else "—"

    lines.append(f"  總攝取：{total_cal:.0f} kcal（目標 {calorie_target} kcal，達成 {pct}）")
    lines.append(f"  蛋白質：{total_prot:.0f} g")
    lines.append("")

    meals = progress.get("meal_breakdown", {})
    if meals:
        for meal_type, data in meals.items():
            meal_name = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "點心"}.get(meal_type, meal_type)
            cal = data.get("calories", 0)
            prot = data.get("protein_g", 0)
            items = data.get("items", 0)
            lines.append(f"  {meal_name}：{cal:.0f} kcal | 蛋白 {prot:.0f}g | {items} 項食物")
    elif total_cal > 0:
        lines.append(f"  已記錄 {total_cal:.0f} kcal，尚無分餐明細")


def _comparison_lines(
    lines: List[str],
    comps: List[Any],
    calorie_target: int,
) -> None:
    """Append history comparison lines."""
    if not comps:
        lines.append("  （尚無歷史資料可比對）")
        return

    for c in comps:
        label = c.period_label
        cur = c.current
        prev = c.previous
        delta = c.delta

        # delta is nested: {'calories': {'absolute': X, 'pct': Y}, ...}
        cal_delta_info = delta.get("calories", {"absolute": 0, "pct": 0})
        cal_delta_abs = float(cal_delta_info["absolute"]) if isinstance(cal_delta_info, dict) else float(cal_delta_info)
        arrow = "⬆️" if cal_delta_abs > 0 else ("⬇️" if cal_delta_abs < 0 else "➡️")

        cur_cal = float(cur.get("calories", 0))
        prev_cal = float(prev.get("calories", 0))

        lines.append(f"  {label}")
        lines.append(f"    當前：{cur_cal:.0f} kcal / {cur.get('protein_g', 0):.0f}g 蛋白")
        if prev_cal > 0:
            lines.append(f"    {arrow} 變化：{cal_delta_abs:+.0f} kcal ({cal_delta_abs / prev_cal * 100:+.0f}%)")
        else:
            lines.append(f"    {arrow} 變化：{cal_delta_abs:+.0f} kcal")


def _daily_recommendations(
    lines: List[str],
    daily_score: DailyScore,
    progress: Dict[str, Any],
    comps: List[Any],
    calorie_target: int,
    protein_target: int,
) -> None:
    """Generate daily recommendations based on scores and data."""
    has_rec = False

    # Check over/under eating
    cal_actual = progress.get("calories_consumed", 0)
    prot_actual = progress.get("protein_consumed_g", 0)

    if calorie_target > 0 and cal_actual > 0:
        cal_ratio = cal_actual / calorie_target
        if cal_ratio > 1.20:
            lines.append("  🔴 今日熱量攝取偏高，建議明天減少份量、避免零食")
            has_rec = True
        elif cal_ratio < 0.75:
            lines.append("  🟡 今日熱量偏低，注意不要過度節食，確保營養均衡")
            has_rec = True

    if protein_target > 0 and prot_actual > 0:
        prot_ratio = prot_actual / protein_target
        if prot_ratio < 0.80:
            lines.append("  🟡 蛋白質攝取不足，明天建議多吃豆類、雞蛋、魚肉補充")
            has_rec = True

    # Check meal coverage
    meals = progress.get("meal_breakdown", {})
    if len(meals) < 3 and cal_actual > 0:
        lines.append("  🔸 部分餐次未記錄，建議完整記錄三餐以便精確追蹤")
        has_rec = True

    if not has_rec:
        lines.append("  ✅ 今日表現良好，繼續保持！")


def _daily_score_bar(
    lines: List[str],
    scores: List[int],
    dates: List[str],
) -> None:
    """Append a visual score bar for 7 days."""
    day_names = ["一", "二", "三", "四", "五", "六", "日"]
    for i, (s, d) in enumerate(zip(scores, dates)):
        day_label = day_names[i] if i < 7 else str(i)
        bar_len = max(1, s // 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)

        grade_icon = _score_icon(s)
        lines.append(f"  {grade_icon} {day_label} {d} [{bar}] {s}分")


def _calorie_chart(
    lines: List[str],
    calories: List[float],
    dates: List[str],
    target: int,
) -> None:
    """Append a text-based calorie trend chart."""
    if not calories or all(c == 0 for c in calories):
        lines.append("  （尚無飲食記錄）")
        return

    max_cal = max(max(calories), target * 1.5) if target > 0 else max(calories) or 2000
    day_names = ["一", "二", "三", "四", "五", "六", "日"]

    for i, (cal, d) in enumerate(zip(calories, dates)):
        day_label = day_names[i] if i < 7 else str(i)
        bar_len = max(1, int(cal / max_cal * 20))
        bar = "█" * bar_len + "░" * (20 - bar_len)

        status = ""
        if target > 0 and cal > 0:
            ratio = cal / target
            if ratio > 1.20:
                status = "🔴"
            elif ratio > 1.10:
                status = "🟡"
            elif ratio < 0.75:
                status = "🟠"
            else:
                status = "🟢"

        lines.append(f"  {status} {day_label} [{bar}] {cal:.0f} kcal")

    if target > 0:
        # Target line
        target_bar_len = max(1, int(target / max_cal * 20))
        target_bar = "─" * target_bar_len + " " * (20 - target_bar_len)
        lines.append(f"     [{target_bar}] {target} kcal（目標）")


def _get_week_weight_change(
    db: DBManager,
    user_id: str,
    week_start: date,
    week_end: date,
) -> Optional[float]:
    """Get weight change for the week from weight_logs. Returns None if no data."""
    ws_str = week_start.isoformat()
    we_str = week_end.isoformat()

    end_of_week_row = db.fetch_one(
        """SELECT weight_kg FROM weight_logs
           WHERE user_id = ? AND log_date <= ?
           ORDER BY log_date DESC LIMIT 1""",
        (user_id, we_str),
    )
    start_of_week_row = db.fetch_one(
        """SELECT weight_kg FROM weight_logs
           WHERE user_id = ? AND log_date <= ?
           ORDER BY log_date DESC LIMIT 1""",
        (user_id, ws_str),
    )
    if not end_of_week_row or not start_of_week_row:
        return None

    return float(end_of_week_row["weight_kg"] or 0) - float(start_of_week_row["weight_kg"] or 0)


def _score_icon(score: int) -> str:
    if score >= 90:
        return "⭐"
    elif score >= 75:
        return "✅"
    elif score >= 60:
        return "🔸"
    elif score >= 40:
        return "🟡"
    else:
        return "🔴"


def _weekly_recommendations(
    lines: List[str],
    daily_data: List[Dict[str, Any]],
    daily_scores: List[int],
    ws: WeeklyScore,
    calorie_target: int,
    protein_target: int,
) -> None:
    """Generate next-week recommendations."""
    has_rec = False

    avg_cal = sum(d["calories"] for d in daily_data) / len(daily_data) if daily_data else 0

    if calorie_target > 0 and avg_cal > 0:
        cal_deviation = (avg_cal - calorie_target) / calorie_target
        if cal_deviation > 0.10:
            lines.append(f"  🔴 本週平均熱量偏高 {cal_deviation*100:.0f}%，下週建議控制份量")
            has_rec = True
        elif cal_deviation < -0.10:
            lines.append(f"  🟡 本週平均熱量偏低 {abs(cal_deviation)*100:.0f}%，注意營養攝取")
            has_rec = True

    # Protein check
    avg_prot = sum(d["protein"] for d in daily_data) / len(daily_data) if daily_data else 0
    if protein_target > 0 and avg_prot > 0:
        if avg_prot < protein_target * 0.8:
            lines.append(f"  🟡 本週蛋白質平均 {avg_prot:.0f}g（目標 {protein_target}g），建議增加優質蛋白來源")
            has_rec = True

    # Consistency check
    if ws.completeness_score < 70:
        lines.append("  🔸 記錄完整度偏低，下週建議盡量記錄每一餐")
        has_rec = True

    # Weight trend
    if ws.weight_trend_score < 50:
        lines.append("  🟡 體重未如預期變化，建議回顧飲食記錄並確認熱量估算是否準確")
        has_rec = True

    if not has_rec:
        lines.append("  ✅ 本週表現優異！保持現有習慣即可")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="HealthFit report generator")
    sub = parser.add_subparsers(dest="command")

    # ── daily ───────────────────────────────────────────────────────
    daily_parser = sub.add_parser("daily", help="Generate daily report")
    daily_parser.add_argument("--user-id", required=True)
    daily_parser.add_argument("--date", default=date.today().isoformat())
    daily_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))
    daily_parser.add_argument("--json", action="store_true", help="Output structured JSON")

    # ── weekly ──────────────────────────────────────────────────────
    weekly_parser = sub.add_parser("weekly", help="Generate weekly report")
    weekly_parser.add_argument("--user-id", required=True)
    weekly_parser.add_argument("--week-start", default=None, help="YYYY-MM-DD Monday")
    weekly_parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))
    weekly_parser.add_argument("--json", action="store_true", help="Output structured JSON")

    args = parser.parse_args()
    db = DBManager(Path(args.db_path))

    if args.command == "daily":
        report = generate_daily_report(db, args.user_id, report_date=args.date)
        if args.json:
            print(json.dumps({"report_text": report}, ensure_ascii=False))
        else:
            print(report)

    elif args.command == "weekly":
        report = generate_weekly_report(db, args.user_id, week_start_date=args.week_start)
        if args.json:
            print(json.dumps({"report_text": report}, ensure_ascii=False))
        else:
            print(report)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
