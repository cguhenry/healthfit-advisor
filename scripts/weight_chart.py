#!/usr/bin/env python3
"""
weight_chart.py — ASCII weight prediction vs actual visualization.

Charts the predicted weight trajectory from a BWPCalculator plan against
actual logged weights, rendered as a terminal-friendly ASCII chart.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# Ensure sibling scripts are importable
import sys as _sys

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager


# ═══════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class WeightChartData:
    plan_start_date: date
    dates: list[date]
    predicted: list[float]  # len == len(dates); float("nan") if outside trajectory
    actual: list[Optional[float]]  # None if no log for that date
    goal_weight_kg: float
    plan_daily_target_kcal: int
    plan_label: str


# ═══════════════════════════════════════════════════════════════════════════
# Step G4: Fallback trajectory generator
# ═══════════════════════════════════════════════════════════════════════════


def _linear_trajectory(
    *,
    start_weight: float,
    goal_weight: float,
    duration_days: int,
) -> list[float]:
    """Generate a linear weight trajectory from start to goal."""
    if duration_days <= 0:
        return [start_weight]
    return [
        round(start_weight + (goal_weight - start_weight) * (i / duration_days), 3)
        for i in range(duration_days + 1)
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Step G5: Load trajectory from DB
# ═══════════════════════════════════════════════════════════════════════════


def _load_trajectory(plan: dict) -> Optional[list[float]]:
    """Parse trajectory_json from a plan row. Returns None on failure."""
    raw = plan.get("trajectory_json")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    result: list[float] = []
    for value in parsed:
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            return None
    return result or None


# ═══════════════════════════════════════════════════════════════════════════
# Step G6: Fetch chart data
# ═══════════════════════════════════════════════════════════════════════════


def fetch_chart_data(
    db: DBManager,
    user_id: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> Optional[WeightChartData]:
    """
    Build WeightChartData from the active plan and weight logs.

    Returns None if no active plan exists.
    """
    db.initialize()

    plan_row = db.get_active_plan(user_id)
    if not plan_row:
        return None

    plan = dict(plan_row)

    today = date.today()
    to_date = to_date or today

    # Determine plan start date
    start_raw = plan.get("plan_start_date") or str(plan.get("created_at") or "")[:10]
    try:
        plan_start = date.fromisoformat(start_raw)
    except ValueError:
        first_log = db.fetch_one(
            """
            SELECT log_date
            FROM weight_logs
            WHERE user_id = ?
            ORDER BY log_date ASC
            LIMIT 1
            """,
            (user_id,),
        )
        plan_start = (
            date.fromisoformat(first_log["log_date"])
            if first_log
            else today
        )

    # Build or load trajectory
    duration_days = int(plan.get("target_weeks") or 0) * 7
    duration_days = max(duration_days, 1)

    trajectory = _load_trajectory(plan)
    if not trajectory:
        trajectory = _linear_trajectory(
            start_weight=float(plan["start_weight_kg"]),
            goal_weight=float(plan["goal_weight_kg"]),
            duration_days=duration_days,
        )

    # Clamp to_date to trajectory end
    max_trajectory_date = plan_start + timedelta(days=len(trajectory) - 1)
    to_date = min(to_date, max_trajectory_date)

    # Default from_date: up to 90 days before to_date, but not before plan_start
    default_from = max(plan_start, to_date - timedelta(days=90))
    from_date = from_date or default_from
    # Always clamp to plan_start to avoid blank chart prefix
    from_date = max(from_date, plan_start)

    if from_date > to_date:
        return None

    # Build date index
    total_days = (to_date - from_date).days + 1
    dates = [from_date + timedelta(days=i) for i in range(total_days)]

    # Fetch actual weight logs
    rows = db.fetchall(
        """
        SELECT log_date, weight_kg
        FROM weight_logs
        WHERE user_id = ?
          AND log_date BETWEEN ? AND ?
        ORDER BY log_date ASC
        """,
        (user_id, from_date.isoformat(), to_date.isoformat()),
    )

    actual_by_date = {
        date.fromisoformat(row["log_date"]): float(row["weight_kg"])
        for row in rows
        if row["weight_kg"] is not None
    }

    # Build predicted list
    predicted: list[float] = []
    actual: list[Optional[float]] = []
    for d in dates:
        idx = (d - plan_start).days
        if 0 <= idx < len(trajectory):
            predicted.append(float(trajectory[idx]))
        else:
            predicted.append(float("nan"))
        actual.append(actual_by_date.get(d))

    goal_type = str(plan.get("goal_type") or "")
    plan_label = {
        "loss": "減重計劃",
        "gain": "增肌計劃",
        "maintain": "維持計劃",
    }.get(goal_type, "體重計劃")

    return WeightChartData(
        plan_start_date=plan_start,
        dates=dates,
        predicted=predicted,
        actual=actual,
        goal_weight_kg=float(plan["goal_weight_kg"]),
        plan_daily_target_kcal=int(plan["daily_calorie_target"] or 0),
        plan_label=f"{plan_label}（{plan_start.isoformat()} 起）",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Step G7: ASCII chart renderer
# ═══════════════════════════════════════════════════════════════════════════


def _is_nan(value: float) -> bool:
    return value != value


def render_ascii_chart(
    data: WeightChartData,
    width: int = 50,
    height: int = 12,
    show_dates: bool = True,
) -> str:
    """Render WeightChartData as a terminal-friendly ASCII chart."""

    # Collect all valid numeric values for scale calculation
    values = [
        v for v in data.predicted
        if isinstance(v, float) and not _is_nan(v)
    ]
    values.extend(v for v in data.actual if v is not None)
    values.append(data.goal_weight_kg)

    if not values:
        return "（沒有可視覺化的體重資料）"

    data_min = min(values)
    data_max = max(values)
    span = max(data_max - data_min, 0.5)
    pad = span * 0.08
    y_min = data_min - pad
    y_max = data_max + pad

    n = len(data.dates)
    if n == 0:
        return "（沒有可視覺化的日期資料）"

    grid = [[" " for _ in range(width)] for _ in range(height)]

    def col_for_idx(i: int) -> int:
        if n <= 1:
            return 0
        return round(i / (n - 1) * (width - 1))

    def row_for_value(value: float) -> int:
        ratio = (value - y_min) / max(y_max - y_min, 0.01)
        return height - 1 - round(ratio * (height - 1))

    # Plot predicted trajectory
    for i, v in enumerate(data.predicted):
        if _is_nan(v):
            continue
        r = row_for_value(v)
        c = col_for_idx(i)
        if 0 <= r < height and 0 <= c < width:
            grid[r][c] = "·"

    # Plot actual values (override predicted)
    for i, v in enumerate(data.actual):
        if v is None:
            continue
        r = row_for_value(v)
        c = col_for_idx(i)
        if 0 <= r < height and 0 <= c < width:
            grid[r][c] = "●"

    # Plot goal line
    goal_row = row_for_value(data.goal_weight_kg)
    if 0 <= goal_row < height:
        for c in range(width):
            if grid[goal_row][c] == " ":
                grid[goal_row][c] = "━"

    # Build output
    lines: list[str] = []
    lines.append(data.plan_label)

    for r, row in enumerate(grid):
        value_label = y_max - (r / max(height - 1, 1)) * (y_max - y_min)
        lines.append(f"{value_label:5.1f}│{''.join(row)}")

    lines.append(" └" + "─" * width)

    if show_dates and data.dates:
        left = data.dates[0].strftime("%m/%d")
        right = data.dates[-1].strftime("%m/%d")
        lines.append(f" {left}{' ' * max(width - len(left) - len(right), 1)}{right}")

    lines.append("")
    lines.append(" · 預測曲線  ● 實際記錄  ━ 目標體重")
    lines.append(_compute_progress_label(data))

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Step G8: Progress label
# ═══════════════════════════════════════════════════════════════════════════


def _compute_progress_label(data: WeightChartData) -> str:
    """Generate a human-readable progress status line."""
    actual_points = [
        (i, v)
        for i, v in enumerate(data.actual)
        if v is not None
    ]
    if not actual_points:
        return " 📊 進度：尚無實際體重記錄"

    idx, actual = actual_points[-1]
    predicted_today = data.predicted[idx]

    if _is_nan(predicted_today):
        return f" 📊 目前體重：{actual:.1f} kg"

    diff = actual - predicted_today
    goal_is_lower = data.goal_weight_kg < data.predicted[0]  # weight-loss plan

    # Find closest predicted point to actual
    closest_idx = min(
        range(len(data.predicted)),
        key=lambda i: abs(data.predicted[i] - actual)
        if not _is_nan(data.predicted[i])
        else 9999,
    )
    day_delta = closest_idx - idx

    if abs(diff) < 0.3:
        status = "如期進行 ✅"
    elif goal_is_lower:
        # For weight loss: lower actual than predicted = ahead
        if actual < predicted_today:
            status = f"超前約 {abs(day_delta)} 天 ✅"
        else:
            status = f"落後約 {abs(day_delta)} 天 ⚠️"
    else:
        # For weight gain: higher actual than predicted = ahead
        if actual > predicted_today:
            status = f"超前約 {abs(day_delta)} 天 ✅"
        else:
            status = f"落後約 {abs(day_delta)} 天 ⚠️"

    return (
        f" 📊 進度：{status}\n"
        f" 目前體重：{actual:.1f} kg"
        f"（預測值：{predicted_today:.1f} kg，差距 {diff:+.1f} kg）"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Step G9: CLI
# ═══════════════════════════════════════════════════════════════════════════


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="體重預測 vs 實際曲線")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))
    parser.add_argument("--weeks", type=int, help="Show last N weeks from --to-date (or today)")
    parser.add_argument("--from-date", dest="from_date", help="YYYY-MM-DD")
    parser.add_argument("--to-date", dest="to_date", help="YYYY-MM-DD")
    parser.add_argument("--width", type=int, default=50)
    parser.add_argument("--height", type=int, default=12)

    args = parser.parse_args(argv)

    # Validate width/height
    if args.width < 10:
        parser.error("--width must be at least 10")
    if args.height < 4:
        parser.error("--height must be at least 4")

    to_date = date.fromisoformat(args.to_date) if args.to_date else None
    from_date = date.fromisoformat(args.from_date) if args.from_date else None

    if args.weeks and not from_date:
        end = to_date or date.today()
        from_date = end - timedelta(weeks=args.weeks)

    db = DBManager(Path(args.db_path).expanduser())
    data = fetch_chart_data(
        db,
        args.user_id,
        from_date=from_date,
        to_date=to_date,
    )

    if not data:
        print("沒有可視覺化的 active plan 或體重資料。")
        return 1

    print(render_ascii_chart(data, width=args.width, height=args.height))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())