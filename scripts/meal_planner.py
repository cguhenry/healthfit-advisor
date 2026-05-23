#!/usr/bin/env python3
"""
meal_planner.py — Phase 6: Weekly meal plan generator with shopping list.

Generates a structured 7-day meal plan based on:
- User's daily calorie target & macro targets
- Dietary preferences
- Cuisine type preferences
- Eating location flexibility
- Automatic shopping list from meal plan

Usage (CLI):
    python3 scripts/meal_planner.py plan
    python3 scripts/meal_planner.py plan --cuisine 台式
    python3 scripts/meal_planner.py plan --meal-preference balanced
    python3 scripts/meal_planner.py plan --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()

# ─────────────────────────────────────────────────────────────
# Meal plan templates
# ─────────────────────────────────────────────────────────────

# 7-day meal plan templates by cuisine type and meal preference
# Each meal includes: name, estimated calories, est. protein (g),
# and a short preparation note.

_MEAL_TEMPLATES: dict[str, dict[str, Any]] = {
    "台式": {
        "balanced": {
            "breakfast": [
                ("鮪魚蛋三明治 + 無糖豆漿", 380, 25, "自製，選全麥吐司"),
                ("地瓜 + 水煮蛋 × 2 + 黑咖啡", 350, 18, "地瓜可前一晚蒸好"),
                ("燕麥粥 + 堅果 + 香蕉", 400, 15, "燕麥用牛奶泡、隔夜"),
            ],
            "lunch": [
                ("自助餐：三菜一肉（白飯半碗）", 600, 35, "選蒸/煮烹調，不選勾芡"),
                ("雞肉便當（飯少一半+多加一道菜）", 650, 38, "主菜選滷雞腿去皮下"),
                ("湯麵：蕎麥麵 + 燙青菜 + 滷蛋", 550, 30, "湯喝完、料全吃"),
            ],
            "dinner": [
                ("家常：煎鮭魚 + 燙青菜 + 半碗飯", 550, 35, "鮭魚用不沾鍋煎不用油"),
                ("雞胸肉沙拉 + 烤地瓜", 450, 40, "地瓜替代麵包丁"),
                ("滷牛腱 + 涼拌小黃瓜 + 紫米飯半碗", 550, 42, "牛腱自製控鹽分"),
            ],
        },
        "light": {
            "breakfast": [("希臘優格 + 水果 + 燕麥", 300, 20, "無糖優格")],
            "lunch": [("關東煮（多蔬菜豆腐）+ 茶碗蒸", 400, 25, "選清湯底")],
            "dinner": [("燙青菜 + 雞胸肉 + 冬粉湯", 350, 35, "低熱量高蛋白")],
        },
        "high_protein": {
            "breakfast": [("水煮蛋 × 3 + 無糖豆漿", 350, 30, "高蛋白早餐")],
            "lunch": [("雞胸肉便當（雙主菜）+ 茶葉蛋", 700, 55, "多加一份蛋白質")],
            "dinner": [("牛排 + 烤蔬菜 + 藜麥飯半碗", 600, 50, "瘦肉部位")],
        },
    },
    "日式": {
        "balanced": {
            "breakfast": [
                ("納豆蛋拌飯（糙米）+ 味噌湯", 400, 22, "糙米飯半碗"),
                ("烤魚定食（去餐廳）", 500, 30, "魚選鯖魚/鮭魚"),
            ],
            "lunch": [
                ("壽司（不加美乃滋） + 味噌湯", 550, 25, "選生魚壽司非炸物"),
                ("牛丼（肉多飯少）+ 沙拉", 600, 32, "可請店家飯減半"),
            ],
            "dinner": [
                ("涮涮鍋（不喝湯/不沾醬）", 500, 35, "多蔬菜少加工品"),
                ("生魚片定食（飯一半）+ 涼拌豆腐", 500, 35, "高蛋白低脂"),
            ],
        },
        "light": {
            "breakfast": [("豆腐沙拉 + 無糖綠茶", 250, 15, "嫩豆腐 + 柴魚片")],
            "lunch": [("茶泡飯 + 漬物", 350, 12, "飯量控制半碗")],
            "dinner": [("關東煮（多蔬菜）+ 蒟蒻", 300, 20, "清淡高纖")],
        },
        "high_protein": {
            "breakfast": [("鮭魚飯糰（糙米）+ 味噌湯", 450, 28, "自製飯糰")],
            "lunch": [("生魚片丼（飯一半）+ 茶碗蒸", 650, 45, "高蛋白低碳水")],
            "dinner": [("烤鯖魚 + 涼拌豆腐 + 毛豆", 500, 45, "Omega-3豐富")],
        },
    },
    "西式": {
        "balanced": {
            "breakfast": [
                ("全麥吐司 + 水煮蛋 + 酪梨", 400, 20, "酪梨含健康脂肪"),
                ("希臘優格 + 莓果 + 燕麥", 350, 20, "無糖優格"),
            ],
            "lunch": [
                ("義大利麵（全麥）+ 雞肉 + 沙拉", 600, 35, "青醬或清炒"),
                ("地中海沙拉 + 鷹嘴豆", 450, 20, "高纖飽足感"),
            ],
            "dinner": [
                ("煎雞胸 + 烤蔬菜 + 地瓜泥", 500, 40, "雞胸用香料醃"),
                ("鮭魚 + 蘆筍 + 藜麥", 500, 35, "Omega-3豐富"),
            ],
        },
        "light": {
            "breakfast": [("黑咖啡 + 水煮蛋 × 1", 200, 12, "輕食早餐")],
            "lunch": [("凱撒沙拉（醬另放）", 350, 20, "雞肉沙拉")],
            "dinner": [("蔬菜濃湯 + 雞肉片", 300, 25, "自製無奶油版本")],
        },
        "high_protein": {
            "breakfast": [("希臘優格 + 蛋白粉 + 穀物", 400, 35, "高蛋白早餐")],
            "lunch": [("烤雞胸 + 藜麥 + 花椰菜", 550, 50, "lean protein")],
            "dinner": [("牛排 + 炒蘆筍", 500, 45, "瘦肉部位")],
        },
    },
}

# Shopping list item categories
_SHOPPING_CATEGORIES = {
    "蛋白質": ["雞胸肉", "雞蛋", "鮭魚", "豆腐", "希臘優格", "毛豆",
              "滷牛腱", "鯖魚", "水煮蛋", "納豆", "雞肉", "牛排"],
    "蔬菜": ["燙青菜", "小黃瓜", "花椰菜", "蘆筍", "番茄", "生菜",
             "菠菜", "青椒", "洋蔥", "高麗菜", "豆芽菜", "菇類"],
    "水果": ["蘋果", "香蕉", "奇異果", "芭樂", "草莓", "藍莓", "酪梨"],
    "主食": ["糙米", "全麥吐司", "蕎麥麵", "藜麥", "地瓜", "燕麥片",
             "紫米", "冬粉", "義大利麵(全麥)"],
    "飲料/調味": ["無糖豆漿", "無糖綠茶", "黑咖啡", "無糖優格",
                    "橄欖油", "鹽", "黑胡椒", "香料"],
    "堅果/種子": ["堅果", "亞麻籽", "奇亞籽"],
}


def _rotate(items: list, day_index: int) -> tuple:
    """Rotate through meal options for variety."""
    return items[day_index % len(items)]


def get_daily_calorie_distribution(meal_pref: str = "balanced") -> dict[str, float]:
    """Get recommended calorie distribution across meals."""
    distributions = {
        "balanced": {"breakfast": 0.25, "lunch": 0.35, "dinner": 0.35, "snack": 0.05},
        "light":    {"breakfast": 0.20, "lunch": 0.35, "dinner": 0.35, "snack": 0.10},
        "high_protein": {"breakfast": 0.25, "lunch": 0.35, "dinner": 0.35, "snack": 0.05},
    }
    return distributions.get(meal_pref, distributions["balanced"])


def generate_meal_plan(
    daily_calories: int = 1800,
    cuisine: str = "台式",
    meal_preference: str = "balanced",
    protein_target_g: Optional[int] = None,
) -> dict:
    """Generate a 7-day meal plan.

    Args:
        daily_calories: Daily calorie target
        cuisine: Cuisine type (台式/日式/西式)
        meal_preference: balanced/light/high_protein
        protein_target_g: Optional protein target for per-meal guidance

    Returns dict with days, shopping_list, summary.
    """
    cuisine_data = _MEAL_TEMPLATES.get(cuisine, _MEAL_TEMPLATES["台式"])
    pref_data = cuisine_data.get(meal_preference, cuisine_data["balanced"])

    distribution = get_daily_calorie_distribution(meal_preference)
    weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]

    days = []
    collected_items = set()

    for day_idx, day_name in enumerate(weekdays):
        meals = {}
        total_cal = 0
        total_protein = 0
        items_names = []

        for meal_type, cal_ratio in distribution.items():
            options = pref_data.get(meal_type, pref_data.get("lunch", []))
            if not options:
                continue

            name, cal, protein, note = _rotate(options, day_idx + (0 if meal_type == "breakfast" else (1 if meal_type == "lunch" else 2)))
            meal_cal = round(daily_calories * cal_ratio) if cal_ratio > 0 else 0

            meals[meal_type] = {
                "name": name,
                "calories": meal_cal,
                "protein_g": round(protein * (meal_cal / max(cal, 1))),
                "cal_ratio": cal_ratio,
                "note": note,
            }
            total_cal += meal_cal
            total_protein += meals[meal_type]["protein_g"]
            items_names.append(name)

        # Collect shopping items from meal names
        for name in items_names:
            _extract_items(name, collected_items)

        days.append({
            "day": day_name,
            "meals": meals,
            "total_calories": total_cal,
            "total_protein_g": total_protein,
        })

    # Build shopping list
    shopping_list = _build_shopping_list(collected_items, cuisine)

    # Summary
    avg_cal = sum(d["total_calories"] for d in days) // 7
    avg_protein = sum(d["total_protein_g"] for d in days) // 7

    return {
        "plan": days,
        "shopping_list": shopping_list,
        "summary": {
            "cuisine": cuisine,
            "meal_preference": meal_preference,
            "daily_calorie_target": daily_calories,
            "avg_daily_calories": avg_cal,
            "avg_daily_protein_g": avg_protein,
            "total_items": len(collected_items),
            "days_count": 7,
        },
    }


def _extract_items(meal_name: str, collected: set) -> None:
    """Extract shopping items from a meal name."""
    for item in ["雞胸肉", "雞蛋", "鮭魚", "豆腐", "地瓜", "糙米", "全麥吐司",
                 "香蕉", "蘋果", "堅果", "無糖豆漿", "花椰菜", "蘆筍", "青菜",
                 "希臘優格", "番茄", "酪梨", "藜麥", "毛豆", "雞肉"]:
        if item in meal_name:
            collected.add(item)
    # Add protein sources generically
    if any(w in meal_name for w in ["魚", "肉", "雞", "牛", "蛋", "豆"]):
        collected.add("蛋白質來源")


def _build_shopping_list(
    collected_items: set[str], cuisine: str
) -> dict[str, list[str]]:
    """Organize collected items into shopping list categories."""
    shopping: dict[str, set[str]] = {cat: set() for cat in _SHOPPING_CATEGORIES}

    for item in collected_items:
        for cat, keywords in _SHOPPING_CATEGORIES.items():
            for kw in keywords:
                if kw in item:
                    shopping[cat].add(item)
                    break
            else:
                continue
            break

    # Add cuisine-specific items
    if cuisine == "日式":
        shopping["蛋白質"].add("鮭魚")
        shopping["蛋白質"].add("納豆")
    elif cuisine == "西式":
        shopping["蛋白質"].add("藜麥")
        shopping["蛋白質"].add("希臘優格")

    return {k: sorted(v) for k, v in shopping.items() if v}


# ─────────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────────

def format_meal_plan(plan: dict) -> str:
    """Format 7-day meal plan as human-readable text."""
    lines = []
    s = plan["summary"]

    lines.append(f"🍽️  一週飲食計劃（{s['cuisine']} · {s['meal_preference']}）")
    lines.append(f"   每日目標：{s['daily_calorie_target']} kcal")
    lines.append(f"   平均熱量：{s['avg_daily_calories']} kcal/天")
    lines.append(f"   平均蛋白質：{s['avg_daily_protein_g']} g/天")
    lines.append("─" * 45)

    for day in plan["plan"]:
        lines.append(f"\n📅 {day['day']}（{day['total_calories']} kcal, 蛋白質 {day['total_protein_g']}g）")
        meal_type_labels = {"breakfast": "🌅 早餐", "lunch": "☀️ 午餐",
                            "dinner": "🌙 晚餐", "snack": "🍪 點心"}
        for meal_type, meal in day["meals"].items():
            label = meal_type_labels.get(meal_type, f"  {meal_type}")
            lines.append(f"  {label}：{meal['name']}（{meal['calories']} kcal, 蛋白質 {meal['protein_g']}g）")
            if meal.get("note"):
                lines.append(f"      💡 {meal['note']}")

    # Shopping list
    if plan["shopping_list"]:
        lines.append("\n\n🛒 採購清單")
        lines.append("─" * 30)
        for cat, items in plan["shopping_list"].items():
            lines.append(f"📦 {cat}：{', '.join(items)}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def cmd_plan(args: argparse.Namespace) -> None:
    db_path = Path(os.environ.get("HEALTHFIT_DB_PATH", DEFAULT_DB_PATH))

    # Try to read the user's active plan for calorie target
    daily_calories = args.calories or 1800
    protein_target = None

    if db_path.exists():
        from scripts.db_manager import DBManager
        try:
            db = DBManager(db_path=db_path)

            profile_path = Path(os.environ.get("HEALTHFIT_PROFILE",
                                               Path("~/.healthfit/profile.json").expanduser()))
            if profile_path.exists():
                with open(profile_path) as f:
                    profile = json.load(f)
                user_id = profile.get("user_id") or profile.get("user", {}).get("user_id", "")
                if user_id:
                    plan = db.fetch_one(
                        """SELECT daily_calorie_target, protein_target_g FROM weight_plans
                           WHERE user_id = ? AND is_active = 1 LIMIT 1""",
                        (user_id,),
                    )
                    if plan:
                        if not args.calories and plan["daily_calorie_target"]:
                            daily_calories = plan["daily_calorie_target"]
                        if "protein_target_g" in plan and plan["protein_target_g"]:
                            protein_target = plan["protein_target_g"]
        except Exception:
            pass  # Fallback to defaults

    plan = generate_meal_plan(
        daily_calories=daily_calories,
        cuisine=args.cuisine,
        meal_preference=args.meal_preference,
        protein_target_g=protein_target,
    )

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(format_meal_plan(plan))


def main() -> None:
    parser = argparse.ArgumentParser(prog="meal_planner.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Generate a 7-day meal plan")
    p_plan.add_argument("--calories", "-c", type=int, help="Daily calorie target (default: from active plan or 1800)")
    p_plan.add_argument("--cuisine", default="台式", help="Cuisine: 台式/日式/西式")
    p_plan.add_argument("--meal-preference", "-p", default="balanced",
                        choices=["balanced", "light", "high_protein"],
                        help="Meal preference (balanced/light/high_protein)")
    p_plan.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args()

    if args.command == "plan":
        cmd_plan(args)


if __name__ == "__main__":
    main()