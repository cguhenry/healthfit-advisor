#!/usr/bin/env python3
"""
can_i_eat.py — Feature F: 「今天能不能吃 X？」即時查詢

處理「今天還能吃 X 嗎？」這類即時查詢。

Usage (CLI):
    python3 scripts/can_i_eat.py "一碗拉麵"
    python3 scripts/can_i_eat.py "珍珠奶茶" --meal dinner
    python3 scripts/can_i_eat.py "兩個便當" --quantity 2
    python3 scripts/can_i_eat.py "一碗拉麵" --user-id U --db-path ~/.healthfit/healthfit.db --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from calorie_tracker import get_calorie_progress
from db_manager import DBManager
from food_db_lookup import FoodDBLookup, SearchResult
from food_preference_engine import get_food_fingerprint

DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()

# ─────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────

Verdict = Literal["yes", "yes_with_caveat", "marginal", "no"]


@dataclass
class CanIEatResult:
    food_name: str
    matched_food_display: str  # e.g. "豚骨拉麵（估算一份）"
    estimated_calories: float
    estimated_protein_g: float
    calories_remaining: float
    daily_target: int
    goal_type: str
    protein_gap: float  # positive = still needed, negative = already exceeded
    verdict: Verdict
    advice: str
    alternatives: list[str]  # replacement suggestions when verdict != "yes"
    adjusted_meal_suggestion: str  # "可以吃，但今天晚餐建議..."
    confidence: float = 0.0  # search match confidence
    _is_estimate: bool = False  # True when food wasn't in DB

    def to_dict(self) -> dict:
        d = asdict(self)
        d["_is_estimate"] = self._is_estimate
        return d


# ─────────────────────────────────────────────────────────────────────────
# Verdict logic
# ─────────────────────────────────────────────────────────────────────────

def _determine_verdict(
    food_calories: float,
    remaining: float,
    daily_target: float,
    goal_type: str,
) -> tuple[Verdict, str]:
    """
    Return (verdict, advice_string) based on calorie overshoot.

    Thresholds are relative to daily_target and shift by goal_type.
    For 'gain' (增肌), we are more tolerant since eating above target
    is often the objective.
    """
    overshoot = food_calories - remaining  # positive = over budget

    # 特殊：今日已超標（remaining < 0）
    if remaining < 0:
        return "no", (
            f"❌ 今日已超標 {abs(remaining):.0f} kcal，"
            f"再吃這份（{food_calories:.0f} kcal）將再多超標 {food_calories:.0f} kcal。"
        )

    if goal_type == "gain":
        # 增肌：超標寬容度更高
        threshold_caveat = daily_target * 0.10
        threshold_marginal = daily_target * 0.25
    else:
        threshold_caveat = daily_target * 0.05
        threshold_marginal = daily_target * 0.15

    if overshoot <= 0:
        return "yes", "✅ 可以吃！"
    elif overshoot <= threshold_caveat:
        pct = round(overshoot / daily_target * 100) if daily_target else 0
        return "yes_with_caveat", (
            f"⚠️ 吃完後會略超標 {overshoot:.0f} kcal（{pct}% 的每日目標）"
        )
    elif overshoot <= threshold_marginal:
        pct = round(overshoot / daily_target * 100) if daily_target else 0
        return "marginal", (
            f"🟡 吃完後超標 {overshoot:.0f} kcal（{pct}% 的每日目標），"
            "需要其他餐減量"
        )
    else:
        pct = round(overshoot / daily_target * 100) if daily_target else 0
        return "no", (
            f"❌ 這份食物含 {food_calories:.0f} kcal，超出今日剩餘 "
            f"{abs(remaining):.0f} kcal 太多（{pct}% 的每日目標）"
        )


# ─────────────────────────────────────────────────────────────────────────
# Default serving sizes for common foods (grams) when DB doesn't have serving
# ─────────────────────────────────────────────────────────────────────────

_DEFAULT_SERVINGS: dict[str, float] = {
    "拉麵": 350,
    "珍珠奶茶": 500,
    "便當": 700,
    "飯糰": 150,
    "雞排": 200,
    "水餃": 180,
    "包子": 150,
    "三明治": 180,
    "漢堡": 200,
    "披薩": 200,
    "義大利麵": 300,
    "炒飯": 350,
    "陽春麵": 300,
    "鍋燒意麵": 400,
    "鹽酥雞": 200,
    "滷味": 300,
    "牛肉麵": 450,
    "擔仔麵": 250,
}


def _default_serving_for(food_name: str) -> float:
    """Return default grams for a food name if known, else 200g."""
    for key, grams in _DEFAULT_SERVINGS.items():
        if key in food_name:
            return grams
    return 200.0


# ─────────────────────────────────────────────────────────────────────────
# Alternative food generation (simple heuristic — no LLM needed)
# ─────────────────────────────────────────────────────────────────────────

# Categories for substitution
_CATEGORY_ALTERNATIVES: dict[str, list[dict[str, float]]] = {
    "拉麵": [
        {"name": "蕎麥冷麵", "calories": 380, "protein_g": 12},
        {"name": "烏龍湯麵", "calories": 420, "protein_g": 14},
        {"name": "雞絲涼麵", "calories": 350, "protein_g": 16},
        {"name": "素湯麵", "calories": 300, "protein_g": 8},
    ],
    "珍珠奶茶": [
        {"name": "無糖綠茶", "calories": 0, "protein_g": 0},
        {"name": "純咖啡（無糖）", "calories": 5, "protein_g": 0},
        {"name": "零卡可樂", "calories": 0, "protein_g": 0},
        {"name": "希臘優格 + 水果", "calories": 180, "protein_g": 14},
    ],
    "便當": [
        {"name": "烤鯖魚定食", "calories": 520, "protein_g": 35},
        {"name": "日式雞肉沙拉", "calories": 380, "protein_g": 28},
        {"name": "越南生春卷 2 條", "calories": 280, "protein_g": 12},
    ],
}


def _build_alternatives(
    food_name: str,
    remaining: float,
    protein_gap: float,
) -> list[str]:
    """Generate alternative food suggestions."""
    alternatives: list[str] = []

    for category, options in _CATEGORY_ALTERNATIVES.items():
        if category in food_name:
            for opt in options:
                cal = opt["calories"]
                prot = opt["protein_g"]
                within = cal <= remaining
                within_str = "✅ 在配額內" if within else f"⚠️ 超出 {cal - remaining:.0f} kcal"
                alternatives.append(
                    f"{opt['name']}（約 {cal} kcal）{within_str}"
                )
            break
    else:
        # Generic fallback — 動態標記
        fallback_options = [
            ("蕎麥冷麵", 380), ("雞絲涼麵", 350), ("日式雞肉沙拉", 380)
        ]
        for name, cal in fallback_options:
            within_str = "✅ 在配額內" if cal <= remaining else f"⚠️ 超出 {cal - remaining:.0f} kcal"
            alternatives.append(f"{name}（約 {cal} kcal）{within_str}")

    return alternatives


# ─────────────────────────────────────────────────────────────────────────
# Adjusted meal suggestion
# ─────────────────────────────────────────────────────────────────────────

def _build_adjusted_suggestion(
    food_calories: float,
    remaining: float,
    protein_gap: float,
    food_name: str,
    meal_type: Optional[str],
    goal_type: str,
) -> str:
    """Build a sentence on how to fit this food into today's plan."""
    parts = []
    overshoot = food_calories - remaining

    if overshoot > 0:
        save_per_meal = min(100, overshoot / 2)
        parts.append(f"今天其餘餐次各減少約 {save_per_meal:.0f} kcal")

    if protein_gap > 5 and food_calories <= remaining:
        parts.append(f"蛋白質還差 {protein_gap:.0f}g，建議加一顆溫泉蛋或豆腐")

    if "拉麵" in food_name:
        suggestions = [
            "選清湯（鹽味/醬油）代替豚骨，熱量約少 200 kcal",
            "不加叉燒，可減少約 120 kcal",
            "麵量減半，再省約 130 kcal",
        ]
        parts.extend(suggestions)
    elif "便當" in food_name:
        suggestions = [
            "飯量減半，青菜與蛋白質吃足",
            "不要把滷汁淋在飯上，可省約 100 kcal",
        ]
        parts.extend(suggestions)

    if not parts:
        parts.append("注意醬料與油脂添加量，優先吃蛋白質與蔬菜")

    return "可以吃，但建議做以下調整：\n• " + "\n• ".join(parts)


# ─────────────────────────────────────────────────────────────────────────
# Core check function
# ─────────────────────────────────────────────────────────────────────────

def check_can_i_eat(
    db: DBManager,
    user_id: str,
    food_query: str,
    quantity: float = 1.0,
    meal_type: Optional[str] = None,
    log_date: Optional[str] = None,
) -> CanIEatResult:
    """
    Determine if the user can eat a given food within today's calorie budget.

    Steps:
    1. get_calorie_progress() → today's budget
    2. FoodDBLookup.search(food_query) → nutrition lookup
    3. Apply quantity multiplier
    4. Determine verdict and build advice
    5. If marginal/no, query food_preference_engine for alternatives
    6. Build adjusted meal suggestion
    """
    db.initialize()

    # 1) Today's calorie progress
    progress = get_calorie_progress(db, user_id, log_date=log_date)
    calories_remaining = float(progress.get("calories_remaining", 0))
    daily_target = int(progress.get("calorie_target", 0))
    # Default to 2000 if no plan/fallback exists
    if daily_target <= 0:
        daily_target = 2000
    protein_consumed = float(progress.get("protein_consumed_g", 0))
    protein_target = float(progress.get("protein_target_g", 0))
    protein_gap = protein_target - protein_consumed  # positive = still need more

    # Get goal_type from active plan
    plan = db.get_active_plan(user_id)
    goal_type = str(plan["goal_type"]) if plan else "loss"

    # 2) Food search
    lookup = FoodDBLookup(db=db)
    results = lookup.search(food_query, top=3)

    # Use best match
    if results:
        best: SearchResult = results[0]
        ni = best.item
        serving_g = float(ni.serving_size_g or 0) or _default_serving_for(food_query)
        grams = serving_g * quantity
        # ni.calories_for / protein_for already use the scaled grams
        food_cal = ni.calories_for(grams)
        food_prot = ni.protein_for(grams)
        confidence = best.match_score
        matched_name = ni.food_name
        is_estimate = confidence < 0.5
    else:
        # No match in DB — use heuristic defaults
        grams = _default_serving_for(food_query) * quantity
        # Rough calorie-per-100g estimate for unknown food
        food_cal = grams * 2.5  # ~250 kcal / 100g default
        food_prot = grams * 0.05  # ~5g protein / 100g default
        confidence = 0.0
        matched_name = f"{food_query}（估算）"
        is_estimate = True

    # 3) Verdict
    verdict, advice = _determine_verdict(
        food_cal, calories_remaining, daily_target, goal_type
    )

    # 4) Alternatives (only when verdict != yes)
    if verdict == "yes":
        alternatives: list[str] = []
    else:
        alternatives = _build_alternatives(food_query, calories_remaining, protein_gap)

    # 5) Adjusted meal suggestion
    if verdict in ("yes", "yes_with_caveat", "marginal"):
        adjusted = _build_adjusted_suggestion(
            food_cal, calories_remaining, protein_gap,
            food_query, meal_type, goal_type
        )
    else:
        adjusted = ""  # no verdict only

    # Protein gap note
    if protein_gap > 10 and verdict != "no":
        advice += (
            f"\n⚠️ 今日蛋白質還差 {protein_gap:.0f}g，"
            "即使吃這份也要記得補蛋白質。"
        )

    # Low-confidence disclaimer
    if is_estimate:
        advice += (
            "\n⚠️ 系統未找到精確資料，熱量為估算值，"
            "實際數值可能有 ±20% 誤差。"
        )

    if is_estimate:
        matched_food_display = f"{matched_name}（估算 1 份）"
    else:
        quantity_str = "" if quantity == 1.0 else f" × {quantity:.0g}"
        matched_food_display = f"{matched_name}{quantity_str}"

    return CanIEatResult(
        food_name=food_query,
        matched_food_display=matched_food_display,
        estimated_calories=round(food_cal, 1),
        estimated_protein_g=round(food_prot, 1),
        calories_remaining=round(calories_remaining, 1),
        daily_target=daily_target,
        goal_type=goal_type,
        protein_gap=round(protein_gap, 1),
        verdict=verdict,
        advice=advice,
        alternatives=alternatives,
        adjusted_meal_suggestion=adjusted,
        confidence=confidence,
        _is_estimate=is_estimate,
    )


# ─────────────────────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────────────────────

def format_result(result: CanIEatResult) -> str:
    """Render a CanIEatResult as a human-readable string."""
    lines = [
        f"🍜 查詢結果：{result.matched_food_display}",
        "",
        f"熱量估算：約 {result.estimated_calories:.0f} kcal",
        f"蛋白質：約 {result.estimated_protein_g:.0f} g",
        f"今日剩餘：{result.calories_remaining:+.0f} kcal（目標 {result.daily_target} kcal）",
        "",
    ]

    lines.append(result.advice)
    lines.append("")

    if result.verdict in ("marginal", "no"):
        if result.adjusted_meal_suggestion:
            lines.append(f"💡 建議：\n{result.adjusted_meal_suggestion}")
            lines.append("")
        if result.alternatives:
            lines.append(f"🔄 替代選項：")
            for alt in result.alternatives:
                lines.append(f"• {alt}")
            lines.append("")
    elif result.verdict in ("yes", "yes_with_caveat"):
        if result.adjusted_meal_suggestion:
            lines.append(f"💡 建議：\n{result.adjusted_meal_suggestion}")
            lines.append("")

    if result.protein_gap > 5:
        gap_label = "還差" if result.protein_gap > 0 else "已超標"
        lines.append(f"🥩 蛋白質缺口：{gap_label} {abs(result.protein_gap):.0f}g")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="can_i_eat.py",
        description="「今天能不能吃 X？」— 即時熱量評估",
    )
    parser.add_argument("food_query", help="食物名稱，例如：一碗拉麵、珍珠奶茶")
    parser.add_argument("--meal", dest="meal_type",
                        choices=("breakfast", "lunch", "dinner", "snack"),
                        help="預計哪一餐吃")
    parser.add_argument("--quantity", "-q", type=float, default=1.0,
                        help="份量倍數（預設 1）")
    parser.add_argument("--user-id", "-u", default="default_user")
    parser.add_argument("--db-path", "-d", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--date", help="查詢日期（YYYY-MM-DD，預設今天）")
    parser.add_argument("--json", action="store_true", help="輸出 JSON 格式")

    args = parser.parse_args()

    db = DBManager(Path(args.db_path).expanduser())
    result = check_can_i_eat(
        db,
        user_id=args.user_id,
        food_query=args.food_query,
        quantity=args.quantity,
        meal_type=args.meal_type,
        log_date=args.date,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()