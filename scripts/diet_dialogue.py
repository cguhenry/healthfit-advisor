#!/usr/bin/env python3
"""
Phase 2: Guided diet-consultation dialogue tree.
Provides a reusable conversation flow for the agent to collect
cuisine_type, eating_location, and meal_type — then defer to
MenuAdvisor for the actual recommendation.
"""

from __future__ import annotations

import sys
import re
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

try:
    from menu_advisor import MenuAdvisor, recommend_from_payload
    from calorie_tracker import log_meal_manual, upsert_daily_summary
    from db_manager import DBManager
except ImportError:
    # allow running as a script without modifying sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from menu_advisor import MenuAdvisor, recommend_from_payload
    from calorie_tracker import log_meal_manual, upsert_daily_summary
    from db_manager import DBManager


# ---------------------------------------------------------------------------
# Constants (must match menu_advisor.py literals)
# ---------------------------------------------------------------------------
CUISINE_OPTIONS = ["taiwanese", "japanese", "western", "korean", "southeast_asian", "no_preference"]
LOCATION_OPTIONS = ["home", "convenience_store", "buffet", "chain_restaurant", "restaurant", "no_preference"]
MEAL_OPTIONS = ["breakfast", "lunch", "dinner", "snack"]

CUISINE_LABELS: Dict[str, str] = {
    "taiwanese": "台式（台菜、川菜、滷味、自助餐）",
    "japanese": "日式（定食、拉麵、壽司、便當）",
    "western": "西式（美式、義式、地中海）",
    "korean": "韓式",
    "southeast_asian": "東南亞（越南、泰國、印尼）",
    "no_preference": "沒有特別偏好（AI 推薦）",
}

LOCATION_LABELS: Dict[str, str] = {
    "home": "在家烹飪",
    "convenience_store": "超商（7-11 / 全家 / 萊爾富）",
    "buffet": "自助餐 / 便當店",
    "chain_restaurant": "連鎖餐廳（麥當勞、肯德基、Subway 等）",
    "restaurant": "一般餐廳 / 合菜",
    "no_preference": "沒有特別偏好",
}

MEAL_LABELS: Dict[str, str] = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
    "snack": "點心 / 消夜",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _match(options: list[str], raw: str) -> Optional[str]:
    """Fuzzy-match user text to one of options (Chinese or English).

    Priority (first wins):
      1. Exact key match (raw == key)
      2. Chinese keyword match (ordered by specificity, longest first)
      3. Fallback: raw in key (e.g. "breakfast" in "breakfast")

    Does NOT substring-match against display labels because that creates
    false positives (e.g. "餐廳" inside "連鎖餐廳" label).
    """
    raw = raw.lower().strip()

    # 1. Exact key match
    if raw in options:
        return raw

    # 2. Chinese keyword matching — ordered by specificity, longest first
    KEYWORDS: List[Tuple[str, str]] = [
        # Locations
        ("便利商店", "convenience_store"),
        ("連鎖餐廳", "chain_restaurant"),
        ("餐廳", "restaurant"),
        ("合菜", "restaurant"),
        ("超商", "convenience_store"),
        ("7-11", "convenience_store"),
        ("全家", "convenience_store"),
        ("萊爾富", "convenience_store"),
        ("自助餐", "buffet"),
        ("便當店", "buffet"),
        ("便當", "buffet"),
        ("在家", "home"),
        ("家裡", "home"),
        ("自己煮", "home"),
        ("麥當勞", "chain_restaurant"),
        ("subway", "chain_restaurant"),
        # Cuisines
        ("台式", "taiwanese"),
        ("台菜", "taiwanese"),
        ("日式", "japanese"),
        ("日本料理", "japanese"),
        ("拉麵", "japanese"),
        ("壽司", "japanese"),
        ("西式", "western"),
        ("義式", "western"),
        ("美式", "western"),
        ("韓式", "korean"),
        ("韓國料理", "korean"),
        ("東南亞", "southeast_asian"),
        ("越式", "southeast_asian"),
        ("泰式", "southeast_asian"),
        # Meals
        ("早餐", "breakfast"),
        ("午餐", "lunch"),
        ("晚餐", "dinner"),
        ("消夜", "snack"),
        ("宵夜", "snack"),
        ("點心", "snack"),
        # No-preference synonyms
        ("沒有偏好", "no_preference"),
        ("沒有特別偏好", "no_preference"),
        ("沒有", "no_preference"),
        ("隨便", "no_preference"),
        ("都行", "no_preference"),
        ("no_preference", "no_preference"),
        ("any", "no_preference"),
    ]
    for keyword, value in KEYWORDS:
        if keyword in raw and value in options:
            return value

    # 3. Fallback: raw is a substring of the option key
    for key in options:
        if raw in key:
            return key

    return None


def _extract_quantity_grams(fragment: str) -> tuple[str, float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|克)", fragment, flags=re.IGNORECASE)
    if not match:
        return fragment, 0.0
    quantity_g = float(match.group(1))
    cleaned = (fragment[:match.start()] + fragment[match.end():]).strip()
    return cleaned, quantity_g


def _normalize_food_name(fragment: str) -> str:
    cleaned = fragment.strip()
    cleaned = re.sub(r"^(我|今天|剛剛|剛才|剛|早餐|午餐|晚餐|點心|宵夜|消夜)+", "", cleaned)
    cleaned = re.sub(r"^(有|吃了|吃|喝了|喝|是|大概|大約|大致上)", "", cleaned)
    cleaned = re.sub(r"(了|喔|哦|啊|呀|欸)$", "", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned.strip("，。；、,. ")


def extract_foods_from_text(answer_text: str) -> List[Dict[str, Any]]:
    """
    Parse a short natural-language meal reply into manual food entries.

    This is intentionally heuristic and lightweight: it extracts food names,
    optional gram quantities, and leaves nutrition fields empty for later
    enrichment.
    """
    raw = answer_text.strip()
    if not raw:
        return []
    if any(token in raw for token in ("沒吃", "没吃", "還沒吃", "skip", "不吃")):
        return []

    normalized = raw
    normalized = re.sub(r"[。；;\n]+", "，", normalized)
    normalized = re.sub(r"(還有|再加|另外|以及|還吃了|跟|和|與|及)", "，", normalized)
    normalized = re.sub(r"\bplus\b", "，", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*\+\s*", "，", normalized)

    foods: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for fragment in re.split(r"[，、,]", normalized):
        candidate = fragment.strip()
        if not candidate:
            continue
        candidate, quantity_g = _extract_quantity_grams(candidate)
        candidate = _normalize_food_name(candidate)
        if not candidate:
            continue
        if candidate in {"都沒有", "沒有", "沒", "無"}:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        foods.append(
            {
                "name": candidate,
                "estimated_g": quantity_g,
                "food_db_source": "MANUAL",
                "confidence": 1.0,
            }
        )

    return foods


def process_checkin_response(
    answer_text: str,
    *,
    user_id: str,
    meal_type: Optional[str] = None,
    db_path: str = str(DBManager.DEFAULT_DB_PATH),
    log_datetime: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse a daily check-in answer and persist it as a manual meal log.
    """
    resolved_meal_type = meal_type or _match(MEAL_OPTIONS, answer_text)
    if not resolved_meal_type:
        return {
            "status": "clarification_needed",
            "field": "meal_type",
            "prompt": get_meal_prompt(DialogueState()),
        }

    foods = extract_foods_from_text(answer_text)
    if not foods:
        return {
            "status": "clarification_needed",
            "field": "foods",
            "prompt": "我還沒抓到你這餐吃了哪些食物，請直接列出食物名稱，例如：雞胸肉、茶葉蛋、無糖豆漿。",
            "meal_type": resolved_meal_type,
        }

    db = DBManager(Path(db_path))
    inserted = log_meal_manual(
        db,
        user_id,
        resolved_meal_type,
        foods,
        log_datetime=log_datetime,
        note=note or "daily_checkin",
    )
    active_plan = db.get_active_plan(user_id)
    calorie_target = int(active_plan["daily_calorie_target"] or 0) if active_plan else 0
    summary_date = date.today().isoformat()
    if log_datetime:
        summary_date = datetime.fromisoformat(log_datetime.replace("Z", "+00:00")).date().isoformat()
    summary = upsert_daily_summary(
        db,
        user_id,
        summary_date=summary_date,
        calorie_target=calorie_target,
    )
    return {
        "status": "logged",
        "meal_type": resolved_meal_type,
        "foods": foods,
        "logged_rows": len(inserted),
        "log_ids": inserted,
        "summary": {
            "date": summary.summary_date,
            "total_calories": summary.total_calories,
            "total_protein_g": summary.total_protein_g,
            "total_carb_g": summary.total_carb_g,
            "total_fat_g": summary.total_fat_g,
            "calorie_target": summary.calorie_target,
            "calorie_balance": summary.calorie_balance,
        },
    }


# ---------------------------------------------------------------------------
# Dialogue state machine
# ---------------------------------------------------------------------------
class DialogueState:
    __slots__ = ("cuisine_type", "eating_location", "meal_type", "extra")

    def __init__(self) -> None:
        self.cuisine_type: Optional[str] = None
        self.eating_location: Optional[str] = None
        self.meal_type: Optional[str] = None
        self.extra: Dict[str, Any] = {}


def get_cuisine_prompt(state: DialogueState, prior_response: Optional[str] = None) -> str:
    """Return the prompt text for the cuisine-selection step."""
    lines = []
    if prior_response:
        lines.append(f"抱歉，我不太確定「{prior_response}」是什麼類型。\n")
    lines.append("請問您想吃哪種類型的料理？")
    lines.append("")
    for key in CUISINE_OPTIONS:
        label = CUISINE_LABELS[key]
        lines.append(f"  {key}: {label}")
    lines.append("")
    lines.append("（可以直接說「台式」「日式」「沒有偏好」等）")
    return "\n".join(lines)


def get_location_prompt(state: DialogueState, prior_response: Optional[str] = None) -> str:
    """Return the prompt text for the eating-location step."""
    lines = []
    if prior_response:
        lines.append(f"我不確定「{prior_response}」屬於哪種場合。\n")
    lines.append("請問您在哪裡吃？")
    lines.append("")
    for key in LOCATION_OPTIONS:
        label = LOCATION_LABELS[key]
        lines.append(f"  {key}: {label}")
    lines.append("")
    lines.append("（可以說「超商」「自助餐」「餐廳」「在家」等）")
    return "\n".join(lines)


def get_meal_prompt(state: DialogueState) -> str:
    """Return the prompt text for the meal-type step."""
    lines = ["請問這是哪一餐？"]
    for key in MEAL_OPTIONS:
        lines.append(f"  {key}: {MEAL_LABELS[key]}")
    lines.append("")
    lines.append("（說「早餐」「午餐」「晚餐」或「點心」即可）")
    return "\n".join(lines)


def get_missing_context_prompt(state: DialogueState) -> str:
    """Return a consolidated question for the next missing piece of context."""
    missing: List[str] = []
    if state.cuisine_type is None:
        missing.append("想吃什麼類型")
    if state.eating_location is None:
        missing.append("在哪裡吃")
    if state.meal_type is None:
        missing.append("是哪一餐")
    return "我需要確認以下資訊：" + "、".join(missing) + "。"


# ---------------------------------------------------------------------------
# Main flow function (agent-facing)
# ---------------------------------------------------------------------------
def build_recommendation(
    cuisine_input: Optional[str] = None,
    location_input: Optional[str] = None,
    meal_input: Optional[str] = None,
    user_context: Optional[Dict[str, Any]] = None,
    state: Optional[DialogueState] = None,
) -> Dict[str, Any]:
    """
    Phase 2 recommendation flow.

    Handles three cases:
      1. Complete inputs → direct recommendation (no conversation needed).
      2. Partial inputs → returns the next clarifying question.
      3. Full state from prior turns → continues from missing fields.

    user_context accepts: daily_calorie_target, remaining_daily_calories,
    protein_target_g, protein_consumed_g.
    """
    user_context = user_context or {}

    if state is None:
        state = DialogueState()

    # ── resolve cuisine ──────────────────────────────────────────────────
    if cuisine_input and state.cuisine_type is None:
        matched = _match(CUISINE_OPTIONS, cuisine_input)
        if matched:
            state.cuisine_type = matched
        elif cuisine_input.strip():
            return {
                "status": "clarification_needed",
                "field": "cuisine_type",
                "prompt": get_cuisine_prompt(state, prior_response=cuisine_input),
                "state": _state_dict(state),
            }

    # ── resolve location ──────────────────────────────────────────────────
    if location_input and state.eating_location is None:
        matched = _match(LOCATION_OPTIONS, location_input)
        if matched:
            state.eating_location = matched
        elif location_input.strip():
            return {
                "status": "clarification_needed",
                "field": "eating_location",
                "prompt": get_location_prompt(state, prior_response=location_input),
                "state": _state_dict(state),
            }

    # ── resolve meal ──────────────────────────────────────────────────────
    if meal_input and state.meal_type is None:
        matched = _match(MEAL_OPTIONS, meal_input)
        if matched:
            state.meal_type = matched
        else:
            return {
                "status": "clarification_needed",
                "field": "meal_type",
                "prompt": get_meal_prompt(state),
                "state": _state_dict(state),
            }

    # ── check if still missing fields ─────────────────────────────────────
    missing: List[str] = []
    if state.eating_location is None:
        missing.append("eating_location")
    if state.meal_type is None:
        missing.append("meal_type")

    if missing:
        prompt_map = {
            "cuisine_type": get_cuisine_prompt(state),
            "eating_location": get_location_prompt(state),
            "meal_type": get_meal_prompt(state),
        }
        # ask for the first missing field
        next_field = "cuisine_type" if state.cuisine_type is None else (
            "eating_location" if state.eating_location is None else "meal_type"
        )
        return {
            "status": "clarification_needed",
            "field": next_field,
            "prompt": prompt_map[next_field],
            "state": _state_dict(state),
        }

    # ── all fields resolved — call MenuAdvisor ─────────────────────────────
    advisor = MenuAdvisor()
    cuisine_type = state.cuisine_type or "any"
    # normalise no_preference → any
    if cuisine_type == "no_preference":
        cuisine_type = "any"
    if state.eating_location == "no_preference":
        # pick the most common fallback
        state.eating_location = "convenience_store"

    recommendation = advisor.recommend_meal(
        cuisine_type=cuisine_type,
        eating_location=state.eating_location,
        meal_type=state.meal_type,
        daily_calorie_target=user_context.get("daily_calorie_target"),
        remaining_daily_calories=user_context.get("remaining_daily_calories"),
        protein_target_g=user_context.get("protein_target_g"),
        protein_consumed_g=user_context.get("protein_consumed_g", 0),
    )
    return {
        "status": "ready",
        "cuisine_type": cuisine_type,
        "eating_location": state.eating_location,
        "meal_type": state.meal_type,
        "recommendation": recommendation.to_dict(),
        "formatted": advisor.format_recommendation(recommendation),
        "state": _state_dict(state),
    }


def _state_dict(state: DialogueState) -> Dict[str, Any]:
    return {
        "cuisine_type": state.cuisine_type,
        "eating_location": state.eating_location,
        "meal_type": state.meal_type,
    }


# ---------------------------------------------------------------------------
# CLI for manual testing
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse, json

    parser = argparse.ArgumentParser(description="Phase 2 menu recommendation dialogue flow")
    parser.add_argument("--cuisine", default=None)
    parser.add_argument("--location", default=None)
    parser.add_argument("--meal", default=None)
    parser.add_argument("--checkin-text", default=None, help="Natural-language daily check-in reply to parse and log.")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--db-path", default=str(DBManager.DEFAULT_DB_PATH))
    parser.add_argument("--log-datetime", default=None)
    parser.add_argument("--note", default=None)
    parser.add_argument("--calories", type=int, default=None)
    parser.add_argument("--remaining-calories", type=int, default=None)
    parser.add_argument("--protein-target", type=int, default=None)
    parser.add_argument("--protein-consumed", type=int, default=0)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    user_context = {}
    if args.calories is not None:
        user_context["daily_calorie_target"] = args.calories
    if args.remaining_calories is not None:
        user_context["remaining_daily_calories"] = args.remaining_calories
    if args.protein_target is not None:
        user_context["protein_target_g"] = args.protein_target
    user_context["protein_consumed_g"] = args.protein_consumed

    if args.checkin_text:
        if not args.user_id:
            raise ValueError("--user-id is required with --checkin-text")
        result = process_checkin_response(
            args.checkin_text,
            user_id=args.user_id,
            meal_type=args.meal,
            db_path=args.db_path,
            log_datetime=args.log_datetime,
            note=args.note,
        )
    else:
        result = build_recommendation(
            cuisine_input=args.cuisine,
            location_input=args.location,
            meal_input=args.meal,
            user_context=user_context,
        )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["status"] == "clarification_needed":
            print(result["prompt"])
            print()
            if "state" in result:
                print(f"[state so far: cuisine={result['state']['cuisine_type']}, "
                      f"location={result['state']['eating_location']}, "
                      f"meal={result['state']['meal_type']}]")
        elif result["status"] == "logged":
            print(f"已記錄 {len(result['foods'])} 項食物到 {MEAL_LABELS.get(result['meal_type'], result['meal_type'])}。")
        else:
            print(result["formatted"])


if __name__ == "__main__":
    main()
