#!/usr/bin/env python3
"""
meal_planner.py — Phase 6: Weekly meal plan generator with shopping list.

Generates a structured 7-day meal plan based on:
- User's daily calorie target & macro targets
- Dietary preferences
- Cuisine type preferences
- Eating location flexibility
- Automatic shopping list from meal plan
- PDF export for printing and sharing

Usage (CLI):
    python3 scripts/meal_planner.py plan
    python3 scripts/meal_planner.py plan --cuisine 台式
    python3 scripts/meal_planner.py plan --meal-preference balanced
    python3 scripts/meal_planner.py plan --json
    python3 scripts/meal_planner.py plan --pdf --output meal_plan.pdf
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()
DEFAULT_MEAL_PLAN_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MEAL_PLAN_TIMEOUT_SECONDS = 30
MEAL_PLAN_LLM_MAX_RETRIES = 2

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
            "source": "template",
        },
    }


def _extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _get_recent_food_preferences(
    db,
    user_id: str,
    *,
    lookback_days: int = 14,
    limit: int = 12,
) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT food_name, COUNT(*) AS freq
          FROM food_logs
         WHERE user_id = ?
           AND food_name IS NOT NULL
           AND food_name != '___MEAL_TOTAL___'
           AND DATE(log_datetime) >= DATE('now', ?)
         GROUP BY food_name
         ORDER BY freq DESC, food_name ASC
         LIMIT ?
        """,
        (user_id, f"-{lookback_days} day", limit),
    )
    return [{"food_name": row["food_name"], "count": int(row["freq"])} for row in rows]


def _get_low_score_patterns(
    db,
    user_id: str,
    *,
    lookback_days: int = 14,
    score_threshold: int = 60,
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT fl.food_name, COUNT(*) AS freq
          FROM daily_summaries ds
          JOIN food_logs fl
            ON fl.user_id = ds.user_id
           AND DATE(fl.log_datetime) = ds.summary_date
         WHERE ds.user_id = ?
           AND ds.daily_score IS NOT NULL
           AND ds.daily_score < ?
           AND ds.summary_date >= DATE('now', ?)
           AND fl.food_name != '___MEAL_TOTAL___'
         GROUP BY fl.food_name
         ORDER BY freq DESC, fl.food_name ASC
         LIMIT ?
        """,
        (user_id, score_threshold, f"-{lookback_days} day", limit),
    )
    return [{"food_name": row["food_name"], "count": int(row["freq"])} for row in rows]


def _stringify_food_patterns(items: list[dict[str, Any]], *, empty_text: str) -> str:
    if not items:
        return empty_text
    return "\n".join(f"- {item['food_name']}（{item['count']} 次）" for item in items)


def _build_planning_prompt(
    *,
    daily_calories: int,
    macro_targets: dict[str, float],
    cuisine_pref: str,
    meal_preference: str,
    dietary_restrictions: list[str],
    recent_foods: list[dict[str, Any]],
    avoid_patterns: list[dict[str, Any]],
    days: int,
) -> str:
    return f"""
你是一位專業的台灣飲食計劃師。請為使用者制定 {days} 天的飲食計劃。

== 營養目標（每日）==
- 總熱量：{daily_calories} kcal（允許 ±5%）
- 蛋白質：≥ {macro_targets['protein_g']}g
- 碳水化合物：約 {macro_targets['carb_g']}g
- 脂肪：約 {macro_targets['fat_g']}g

== 偏好設定 ==
- 飲食風格：{cuisine_pref}
- 進食偏好：{meal_preference}
- 飲食限制：{', '.join(dietary_restrictions) or '無'}

== 近期飲食紀錄（請盡量不重複）==
{_stringify_food_patterns(recent_foods, empty_text='- 無近期紀錄')}

== 請避免的飲食模式（根據過去低分記錄）==
{_stringify_food_patterns(avoid_patterns, empty_text='- 無特殊低分模式')}

== 規則 ==
- 同一道菜 7 天內不可出現超過 2 次
- 每天至少包含 breakfast、lunch、dinner，可額外含 snack
- 每餐請提供：name, estimated_calories, protein_g, carb_g, fat_g, prep_note, gi_tier
- 請以台灣常見外食/家常菜為主，名稱要可執行、可購買、可理解
- shopping_items 請列出當天主要採買項目

== 輸出格式 ==
請只回傳 JSON，不要加任何說明文字：
{{
  "days": [
    {{
      "day": 1,
      "meals": {{
        "breakfast": {{"name": "...", "estimated_calories": 350, "protein_g": 20, "carb_g": 40, "fat_g": 10, "prep_note": "...", "gi_tier": "low"}},
        "lunch": {{"name": "...", "estimated_calories": 650, "protein_g": 45, "carb_g": 60, "fat_g": 18, "prep_note": "...", "gi_tier": "medium"}},
        "dinner": {{"name": "...", "estimated_calories": 620, "protein_g": 40, "carb_g": 55, "fat_g": 20, "prep_note": "...", "gi_tier": "low"}},
        "snack": {{"name": "...", "estimated_calories": 120, "protein_g": 12, "carb_g": 10, "fat_g": 4, "prep_note": "...", "gi_tier": "low"}}
      }},
      "daily_total_calories": 1740,
      "shopping_items": ["雞胸肉", "燕麥", "青菜"]
    }}
  ]
}}
""".strip()


def _build_correction_prompt(previous_prompt: str, violations: list[str]) -> str:
    return (
        previous_prompt
        + "\n\n上一次輸出未通過驗證，請只修正違規處並重新輸出完整 JSON。\n"
        + "\n".join(f"- {v}" for v in violations)
    )


def _build_meal_plan_messages(prompt: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是營養規劃師與結構化 JSON 產生器。"
                "請嚴格遵守使用者要求，只輸出單一 JSON 物件，不要 markdown。"
            ),
        },
        {"role": "user", "content": prompt},
    ]


def _env_meal_plan_estimator(prompt: str) -> Optional[dict]:
    model = os.environ.get("HEALTHFIT_MEAL_PLAN_MODEL", "").strip()
    api_key = (
        os.environ.get("HEALTHFIT_MEAL_PLAN_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    if not model or not api_key:
        return None

    api_url = os.environ.get("HEALTHFIT_MEAL_PLAN_API_URL", DEFAULT_MEAL_PLAN_API_URL).strip()
    timeout_seconds = int(os.environ.get("HEALTHFIT_MEAL_PLAN_TIMEOUT_SECONDS", str(DEFAULT_MEAL_PLAN_TIMEOUT_SECONDS)))
    payload = {
        "model": model,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
        "messages": _build_meal_plan_messages(prompt),
    }
    request = urllib_request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except (urllib_error.URLError, TimeoutError, OSError, ValueError):
        return None

    try:
        response_json = json.loads(body)
    except json.JSONDecodeError:
        return None

    content = ""
    choices = response_json.get("choices") or []
    if choices:
        message = choices[0].get("message", {})
        raw_content = message.get("content", "")
        if isinstance(raw_content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in raw_content
            )
        else:
            content = str(raw_content)
    return _extract_json_object(content)


def _call_llm_for_plan(
    prompt: str,
    *,
    llm_estimator: Optional[Callable[[str], Optional[dict]]] = None,
) -> Optional[dict]:
    estimator = llm_estimator or _env_meal_plan_estimator
    return estimator(prompt) if estimator else None


def _validate_day(day_plan: dict, daily_calories: int, macro_targets: dict[str, float]) -> list[str]:
    violations: list[str] = []
    meals = day_plan.get("meals", {})
    total_cal = sum(float(m.get("estimated_calories", 0) or 0) for m in meals.values())
    if daily_calories > 0 and abs(total_cal - daily_calories) / daily_calories > 0.05:
        violations.append(
            f"第 {day_plan.get('day')} 天熱量偏差 {total_cal - daily_calories:+.0f} kcal（目標 {daily_calories}）"
        )

    total_protein = sum(float(m.get("protein_g", 0) or 0) for m in meals.values())
    if total_protein < float(macro_targets["protein_g"]) * 0.85:
        violations.append(
            f"第 {day_plan.get('day')} 天蛋白質 {total_protein:.0f}g 低於目標 {macro_targets['protein_g']}g 的 85%"
        )

    for required in ["breakfast", "lunch", "dinner"]:
        if required not in meals:
            violations.append(f"第 {day_plan.get('day')} 天缺少 {required}")
    return violations


def _normalize_optimized_day(day_plan: dict, *, day_index: int) -> dict:
    meal_labels = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "點心"}
    meals: dict[str, dict[str, Any]] = {}
    total_calories = 0
    total_protein = 0

    for meal_type, meal in (day_plan.get("meals") or {}).items():
        est_cal = round(float(meal.get("estimated_calories", 0) or 0))
        protein = round(float(meal.get("protein_g", 0) or 0))
        carb = round(float(meal.get("carb_g", 0) or 0))
        fat = round(float(meal.get("fat_g", 0) or 0))
        meals[meal_type] = {
            "name": str(meal.get("name", "")).strip(),
            "calories": est_cal,
            "estimated_calories": est_cal,
            "protein_g": protein,
            "carb_g": carb,
            "fat_g": fat,
            "note": str(meal.get("prep_note", "")).strip(),
            "prep_note": str(meal.get("prep_note", "")).strip(),
            "gi_tier": str(meal.get("gi_tier", "unknown")).strip(),
            "label": meal_labels.get(meal_type, meal_type),
        }
        total_calories += est_cal
        total_protein += protein

    shopping_items = [str(item).strip() for item in day_plan.get("shopping_items", []) if str(item).strip()]
    day_value = day_plan.get("day", day_index + 1)
    day_name = day_value if isinstance(day_value, str) and day_value.startswith("週") else f"第{day_index + 1}天"

    return {
        "day": day_name,
        "meals": meals,
        "total_calories": total_calories,
        "total_protein_g": total_protein,
        "shopping_items": shopping_items,
    }


def _validate_weekly_variety(days: list[dict], *, max_repeats: int = 2) -> list[str]:
    counter: Counter[str] = Counter()
    for day in days:
        for meal in day.get("meals", {}).values():
            name = str(meal.get("name", "")).strip()
            if name:
                counter[name] += 1
    return [
        f"同一道菜「{name}」出現 {count} 次，超過上限 {max_repeats} 次"
        for name, count in counter.items()
        if count > max_repeats
    ]


def _build_optimized_plan_response(
    normalized_days: list[dict],
    *,
    daily_calories: int,
    cuisine: str,
    meal_preference: str,
    shopping_seed: set[str],
    source: str,
    days_count: int,
) -> dict:
    collected_items = set(shopping_seed)
    for day in normalized_days:
        for meal in day["meals"].values():
            _extract_items(meal["name"], collected_items)
        for item in day.get("shopping_items", []):
            collected_items.add(item)

    shopping_list = _build_shopping_list(collected_items, cuisine)
    avg_cal = round(sum(d["total_calories"] for d in normalized_days) / max(len(normalized_days), 1))
    avg_protein = round(sum(d["total_protein_g"] for d in normalized_days) / max(len(normalized_days), 1))
    return {
        "plan": normalized_days,
        "shopping_list": shopping_list,
        "summary": {
            "cuisine": cuisine,
            "meal_preference": meal_preference,
            "daily_calorie_target": daily_calories,
            "avg_daily_calories": avg_cal,
            "avg_daily_protein_g": avg_protein,
            "total_items": len(collected_items),
            "days_count": days_count,
            "source": source,
        },
    }


def _parse_and_validate_plan(
    raw_plan: Any,
    *,
    daily_calories: int,
    macro_targets: dict[str, float],
    cuisine: str,
    meal_preference: str,
    expected_days: int = 7,
) -> dict[str, Any]:
    parsed = raw_plan if isinstance(raw_plan, dict) else _extract_json_object(str(raw_plan))
    if not parsed:
        return {"valid": False, "violations": ["LLM 未回傳可解析 JSON"]}

    raw_days = parsed.get("days")
    if not isinstance(raw_days, list) or len(raw_days) != expected_days:
        return {"valid": False, "violations": [f"LLM 回傳天數不正確，預期 {expected_days} 天"]}

    violations: list[str] = []
    normalized_days: list[dict] = []
    shopping_seed: set[str] = set()

    for idx, raw_day in enumerate(raw_days):
        day_violations = _validate_day(raw_day, daily_calories, macro_targets)
        violations.extend(day_violations)
        normalized = _normalize_optimized_day(raw_day, day_index=idx)
        normalized_days.append(normalized)
        for item in normalized.get("shopping_items", []):
            shopping_seed.add(item)

    violations.extend(_validate_weekly_variety(normalized_days))
    if violations:
        return {"valid": False, "violations": violations, "days": normalized_days}

    return {
        "valid": True,
        **_build_optimized_plan_response(
            normalized_days,
            daily_calories=daily_calories,
            cuisine=cuisine,
            meal_preference=meal_preference,
            shopping_seed=shopping_seed,
            source="optimized_llm",
            days_count=expected_days,
        ),
    }


def persist_meal_plan(
    db,
    user_id: str,
    plan: dict,
    *,
    week_start_date: Optional[str] = None,
) -> None:
    db.initialize()
    if week_start_date is None:
        today = date.today()
        week_start_date = (today - timedelta(days=today.weekday())).isoformat()
    summary = plan.get("summary", {})
    db.execute(
        """
        INSERT INTO weekly_meal_plans (
            plan_id, user_id, week_start_date, cuisine, meal_preference,
            source, plan_json, shopping_list_json, summary_json
        ) VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, week_start_date, source) DO UPDATE SET
            cuisine = excluded.cuisine,
            meal_preference = excluded.meal_preference,
            plan_json = excluded.plan_json,
            shopping_list_json = excluded.shopping_list_json,
            summary_json = excluded.summary_json,
            created_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            week_start_date,
            summary.get("cuisine"),
            summary.get("meal_preference"),
            summary.get("source", "template"),
            json.dumps(plan.get("plan", []), ensure_ascii=False),
            json.dumps(plan.get("shopping_list", {}), ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False),
        ),
    )


def generate_optimized_meal_plan(
    db,
    user_id: str,
    daily_calories: int,
    macro_targets: dict[str, float],
    cuisine_pref: str = "台式",
    dietary_restrictions: Optional[list[str]] = None,
    days: int = 7,
    meal_preference: str = "balanced",
    llm_estimator: Optional[Callable[[str], Optional[dict]]] = None,
    persist: bool = False,
) -> dict:
    """LLM-optimized weekly meal plan with validation and template fallback."""
    recent_foods = _get_recent_food_preferences(db, user_id, lookback_days=14)
    low_score_patterns = _get_low_score_patterns(db, user_id)
    prompt = _build_planning_prompt(
        daily_calories=daily_calories,
        macro_targets=macro_targets,
        cuisine_pref=cuisine_pref,
        meal_preference=meal_preference,
        dietary_restrictions=dietary_restrictions or [],
        recent_foods=recent_foods,
        avoid_patterns=low_score_patterns,
        days=days,
    )

    validation_result: Optional[dict[str, Any]] = None
    for _attempt in range(MEAL_PLAN_LLM_MAX_RETRIES + 1):
        raw = _call_llm_for_plan(prompt, llm_estimator=llm_estimator)
        if not raw:
            break
        validation_result = _parse_and_validate_plan(
            raw,
            daily_calories=daily_calories,
            macro_targets=macro_targets,
            cuisine=cuisine_pref,
            meal_preference=meal_preference,
            expected_days=days,
        )
        if validation_result.get("valid"):
            if persist:
                persist_meal_plan(db, user_id, validation_result)
            return validation_result
        prompt = _build_correction_prompt(prompt, validation_result.get("violations", []))

    fallback = generate_meal_plan(
        daily_calories=daily_calories,
        cuisine=cuisine_pref,
        meal_preference=meal_preference,
        protein_target_g=int(macro_targets.get("protein_g", 0)) or None,
    )
    fallback["summary"]["source"] = "template_fallback"
    if validation_result and validation_result.get("violations"):
        fallback["summary"]["fallback_reason"] = validation_result["violations"]
    if persist:
        persist_meal_plan(db, user_id, fallback)
    return fallback


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


def _sanitize_pdf_text(value: Any) -> str:
    """Strip emoji/symbol glyphs that common CJK fonts or PDF core fonts cannot render."""
    text = str(value).replace("•", "-")
    cleaned: list[str] = []
    for char in text:
        if ord(char) in (0x200D, 0xFE0F):
            continue
        if unicodedata.category(char) in {"So", "Cs"}:
            continue
        cleaned.append(char)
    return "".join(cleaned)


def _configure_pdf_fonts(pdf: Any) -> tuple[str, str]:
    """Register a CJK-capable font for PDF export or raise a clear setup error."""
    custom_font = os.environ.get("HEALTHFIT_PDF_FONT", "").strip()
    candidates: list[Path] = []
    if custom_font:
        candidates.append(Path(custom_font).expanduser())
    candidates.extend(
        [
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
            Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ]
    )

    seen: set[Path] = set()
    for font_path in candidates:
        if font_path in seen:
            continue
        seen.add(font_path)
        if not font_path.exists():
            continue
        try:
            pdf.add_font("CJK", style="", fname=str(font_path))
            pdf.add_font("CJK", style="B", fname=str(font_path))
            return "CJK", "CJK"
        except Exception:
            continue

    if custom_font:
        raise RuntimeError(
            "PDF export requires a CJK font. HEALTHFIT_PDF_FONT was set but not loadable: "
            f"{custom_font}. Install fonts-wqy-zenhei or Noto CJK, or point HEALTHFIT_PDF_FONT "
            "to a readable .ttf/.ttc/.otf file."
        )

    raise RuntimeError(
        "PDF export requires a CJK font, but none was found. Install fonts-wqy-zenhei or Noto CJK, "
        "or set HEALTHFIT_PDF_FONT=/path/to/font.ttf"
    )


def export_plan_pdf(plan: dict, output_path: str | Path) -> None:
    """Export meal plan to a formatted PDF file."""
    try:
        from fpdf import FPDF
    except ImportError:
        print("ERROR: fpdf2 not installed. Run: pip install fpdf2", file=sys.stderr)
        return

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    try:
        F, FB = _configure_pdf_fonts(pdf)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return
    S = plan["summary"]
    cuisine = S["cuisine"]; meal_pref = S["meal_preference"]
    cal_tgt = S["daily_calorie_target"]; avg_cal = S["avg_daily_calories"]; avg_prot = S["avg_daily_protein_g"]

    # ── Cover ──────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(0x1A, 0x7A, 0x5C)
    pdf.rect(0, 0, 210, 50, "F")
    pdf.set_font(FB, size=22); pdf.set_text_color(255, 255, 255); pdf.set_y(15)
    pdf.cell(0, 12, _sanitize_pdf_text("一週飲食計劃"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(F, size=13)
    pdf.cell(0, 8, _sanitize_pdf_text(f"{cuisine} · {meal_pref}  |  {cal_tgt} kcal/天"),
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8); pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(240, 248, 240); pdf.set_font(FB, size=11)
    for i, (lbl, val) in enumerate([
        ("每日目標", f"{cal_tgt} kcal"),
        ("平均熱量", f"{avg_cal} kcal"),
        ("平均蛋白質", f"{avg_prot} g"),
    ]):
        x = 10 + (i % 3) * 63
        pdf.set_xy(x, pdf.get_y()); pdf.cell(61, 10, _sanitize_pdf_text(f"{lbl}: {val}"), border=1, align="C", fill=True)
    pdf.ln(16)

    # ── Daily pages ─────────────────────────────────────────────
    bgs = [(240,248,255),(245,255,250),(255,245,238),(245,245,220),
           (240,255,240),(255,250,240),(248,248,255)]
    meal_lbl = {"breakfast":"早餐","lunch":"午餐","dinner":"晚餐","snack":"點心"}

    for di, day in enumerate(plan["plan"]):
        pdf.add_page()
        bg = bgs[di % len(bgs)]; pdf.set_fill_color(*bg); pdf.rect(0, 0, 210, 277, "F")
        pdf.set_fill_color(0x1A,0x7A,0x5C); pdf.rect(0, pdf.get_y(), 210, 10, "F")
        pdf.set_font(FB, size=13); pdf.set_text_color(255,255,255)
        day_name = day["day"]
        total_cal = day["total_calories"]
        total_prot = day["total_protein_g"]
        pdf.cell(0, 10, _sanitize_pdf_text(f"  {day_name}  |  {total_cal} kcal  |  蛋白質 {total_prot}g"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4); pdf.set_text_color(0,0,0)
        for mt, meal in day["meals"].items():
            pdf.set_font(FB, size=11); pdf.set_x(12)
            meal_name = meal["name"]
            pdf.multi_cell(186, 7, _sanitize_pdf_text(f"{meal_lbl.get(mt,mt)}：{meal_name}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(F, size=10); pdf.set_x(18)
            meal_cal = meal["calories"]; meal_prot = meal["protein_g"]
            pdf.cell(0, 6, _sanitize_pdf_text(f"  🔥 {meal_cal} kcal  |  💪 蛋白質 {meal_prot}g"),
                     new_x="LMARGIN", new_y="NEXT")
            if meal.get("note"):
                pdf.set_x(18); pdf.set_font(F, size=9); pdf.set_text_color(80,80,80)
                note = meal["note"]
                pdf.multi_cell(174, 5, _sanitize_pdf_text(f"  💡 {note}"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0,0,0)
            pdf.ln(2)

    # ── Shopping list ───────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(0x1A,0x7A,0x5C); pdf.rect(0, pdf.get_y(), 210, 10, "F")
    pdf.set_font(FB, size=13); pdf.set_text_color(255,255,255)
    pdf.cell(0, 10, _sanitize_pdf_text("  🛒 採購清單"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0,0,0); pdf.ln(3)
    for cat in ["蛋白質","蔬菜","水果","主食","飲料/調味","堅果/種子"]:
        items = plan["shopping_list"].get(cat, [])
        if not items: continue
        pdf.set_font(FB, size=11); pdf.set_x(12)
        pdf.cell(0, 7, _sanitize_pdf_text(f"📦 {cat}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(F, size=10)
        half = (len(items)+1)//2; c1, c2 = items[:half], items[half:]
        for i, item in enumerate(c1):
            y = pdf.get_y()+6; pdf.set_xy(16, y)
            pdf.cell(87, 6, _sanitize_pdf_text(f"  • {item}"))
            if i < len(c2): pdf.cell(87, 6, _sanitize_pdf_text(f"  • {c2[i]}"))
            pdf.ln(6)
        pdf.ln(2)

    pdf.output(str(output_path))
    print(f"✅ PDF 已匯出：{output_path}")



# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def cmd_plan(args: argparse.Namespace) -> None:
    db_path = Path(os.environ.get("HEALTHFIT_DB_PATH", DEFAULT_DB_PATH))

    # Try to read the user's active plan for calorie target
    daily_calories = args.calories or 1800
    protein_target = None
    carb_target = None
    fat_target = None
    user_id = ""
    db = None

    if db_path.exists():
        from db_manager import DBManager
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
                        """SELECT daily_calorie_target, protein_target_g, carb_target_g, fat_target_g FROM weight_plans
                           WHERE user_id = ? AND is_active = 1 LIMIT 1""",
                        (user_id,),
                    )
                    if plan:
                        if not args.calories and plan["daily_calorie_target"]:
                            daily_calories = plan["daily_calorie_target"]
                        if "protein_target_g" in plan and plan["protein_target_g"]:
                            protein_target = plan["protein_target_g"]
                        if "carb_target_g" in plan and plan["carb_target_g"]:
                            carb_target = plan["carb_target_g"]
                        if "fat_target_g" in plan and plan["fat_target_g"]:
                            fat_target = plan["fat_target_g"]
        except Exception:
            pass  # Fallback to defaults

    macro_targets = {
        "protein_g": protein_target or max(90, round(daily_calories * 0.25 / 4)),
        "carb_g": carb_target or round(daily_calories * 0.45 / 4),
        "fat_g": fat_target or round(daily_calories * 0.30 / 9),
    }
    restrictions = [item.strip() for item in (args.restrictions or "").split(",") if item.strip()]

    if args.template_only or not db or not user_id:
        plan = generate_meal_plan(
            daily_calories=daily_calories,
            cuisine=args.cuisine,
            meal_preference=args.meal_preference,
            protein_target_g=protein_target,
        )
    else:
        plan = generate_optimized_meal_plan(
            db=db,
            user_id=user_id,
            daily_calories=daily_calories,
            macro_targets=macro_targets,
            cuisine_pref=args.cuisine,
            dietary_restrictions=restrictions,
            meal_preference=args.meal_preference,
            persist=args.persist,
        )

    if args.pdf:
        export_plan_pdf(plan, args.output or "meal_plan.pdf")
    elif args.json:
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
    p_plan.add_argument("--restrictions", default="", help="Comma-separated dietary restrictions")
    p_plan.add_argument("--template-only", action="store_true", help="Force legacy template planner")
    p_plan.add_argument("--persist", action="store_true", help="Persist weekly meal plan into SQLite when user_id is available")
    p_plan.add_argument("--json", action="store_true", help="Output JSON")
    p_plan.add_argument("--pdf", action="store_true", help="Export to PDF")
    p_plan.add_argument("--output", "-o", type=str, help="Output file path (default: meal_plan.pdf)")

    args = parser.parse_args()

    if args.command == "plan":
        cmd_plan(args)


if __name__ == "__main__":
    main()
