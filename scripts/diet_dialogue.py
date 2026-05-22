#!/usr/bin/env python3
"""
Phase 2: Guided diet-consultation dialogue tree.
Provides a reusable conversation flow for the agent to collect
cuisine_type, eating_location, and meal_type — then defer to
MenuAdvisor for the actual recommendation.
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

try:
    from menu_advisor import MenuAdvisor, recommend_from_payload
except ImportError:
    # allow running as a script without modifying sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from menu_advisor import MenuAdvisor, recommend_from_payload


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
            print(f"[state so far: cuisine={result['state']['cuisine_type']}, "
                  f"location={result['state']['eating_location']}, "
                  f"meal={result['state']['meal_type']}]")
        else:
            print(result["formatted"])


if __name__ == "__main__":
    main()