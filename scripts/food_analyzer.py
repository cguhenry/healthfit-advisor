#!/usr/bin/env python3
"""
food_analyzer.py — Vision-agnostic food image analysis coordinator.

This module does NOT call any Vision API directly. Instead it:

1. Defines structured prompt templates for the agent's LLM to analyze images.
2. Provides response schema definitions so the agent knows how to format output.
3. Post-processes and validates the LLM's structured response.

The actual image analysis is performed by the Agent framework's own LLM
(multimodal models like Claude 3 Sonnet, GPT-4o, Gemini 1.5 Pro, etc.)
when it receives the prompt we return. The agent passes the image along
with our prompt to its LLM and returns the structured analysis result.

Three scenarios:
  1. analyze_menu_image  — OCR + menu item extraction from a restaurant menu photo
  2. analyze_food_image  — Identify foods in a meal photo + estimate portion + nutrition
  3. analyze_before_after — Compare pre-meal and post-meal photos to estimate intake

Confidence tiers:
  >85%: direct value
  60–85%: range estimate with note
  <60%: flag for manual confirmation
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------

class AnalysisScenario(str, Enum):
    MENU = "menu"
    FOOD = "food"
    BEFORE_AFTER = "before_after"


class ConfidenceTier(str, Enum):
    HIGH = "high"      # > 85%
    MEDIUM = "medium"  # 60–85%
    LOW = "low"        # < 60%


# ---------------------------------------------------------------------------
# Response dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IdentifiedFood:
    name: str                          # e.g. "烤雞腿便當"
    name_en: Optional[str] = None     # English fallback
    estimated_g: float = 0.0          # Portion size in grams (0 = unknown)
    confidence: float = 0.0           # 0.0–1.0
    confidence_tier: str = "medium"   # "high" | "medium" | "low"

    def calories(self, calorie_per_100g: float) -> float:
        return round(calorie_per_100g * self.estimated_g / 100, 1)

    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.85


@dataclass(frozen=True)
class NutritionEstimate:
    calories: float = 0.0
    protein_g: float = 0.0
    carb_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0
    sodium_mg: float = 0.0
    confidence: float = 0.0
    confidence_tier: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # round numerics for readability
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = round(v, 1)
        return d


@dataclass(frozen=True)
class MealAnalysisResult:
    scenario: str
    foods: List[IdentifiedFood] = field(default_factory=list)
    total_nutrition: Optional[NutritionEstimate] = None
    confidence: float = 0.0
    confidence_tier: str = "medium"
    low_confidence_warnings: List[str] = field(default_factory=list)
    nutrition_advice: str = ""
    raw_llm_response: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario,
            "foods": [
                {
                    "name": f.name,
                    "name_en": f.name_en,
                    "estimated_g": f.estimated_g,
                    "confidence": round(f.confidence, 3),
                    "confidence_tier": f.confidence_tier,
                }
                for f in self.foods
            ],
            "total_nutrition": self.total_nutrition.to_dict() if self.total_nutrition else None,
            "confidence": round(self.confidence, 3),
            "confidence_tier": self.confidence_tier,
            "low_confidence_warnings": self.low_confidence_warnings,
            "nutrition_advice": self.nutrition_advice,
        }


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

MENU_ANALYSIS_PROMPT_TEMPLATE = """你是一個專業的營養諮詢師，專精於台灣與亞洲料理。請分析這張**餐廳菜單照片**。

任務：
1. 辨識出畫面中盡可能多的菜餚名稱（中英文）
2. 評估每道菜的份量大小（大 / 中 / 小）
3. 估算每道菜的熱量（大卡）和主要巨量營養素（蛋白質、碳水、脂肪，單位為克）
4. 依據以下飲食目標過濾出建議與避免的項目

使用者飲食目標：
- 每日熱量目標：{daily_calorie_target} kcal
- 蛋白質目標：{protein_target_g} g/日
- 剩餘可攝取熱量（本餐）：{remaining_calories} kcal

輸出格式（JSON）：
{{
  "readable_items": [
    {{
      "name": "菜餚名稱",
      "name_en": "English name（若有）",
      "portion_size": "大｜中｜小",
      "estimated_calories": 450,
      "protein_g": 25,
      "carb_g": 40,
      "fat_g": 18,
      "confidence": 0.82,
      "source_note": "備註，例如：醬汁熱量較高、適合減脂等"
    }}
  ],
  "recommended": ["菜名1", "菜名2"],
  "avoid": ["菜名3"],
  "combo_suggestion": "最佳搭配組合建議（不超過3道菜，總熱量控制在remaining_calories以內）",
  "overall_confidence": 0.78,
  "nutrition_advice": "針對這張菜單的整體飲食建議（不超過3句）"
}}

注意：
- 若無法確認熱量，給出合理區間（如 350-500 kcal）而非隨意估計
- 若有油炸、糖醋、勾芡等高熱量烹調方式，請在 source_note 標註
- confidence 低於 0.6 的項目請標註「低信心，建議手動確認」
"""


FOOD_ANALYSIS_PROMPT_TEMPLATE = """你是一個專業的營養辨識AI，專精於亞洲與台式料理的份量估算。請分析這張**食物照片**。

任務：
1. 列出照片中所有可辨識的食物
2. 以常見餐具（筷子、湯匙、碗、盤）作為比例尺，估算每樣食物的份量（以克為單位）
3. 估算總熱量與巨量營養素
4. 計算與使用者今日剩餘熱量的關係

使用者資訊：
- 今日剩餘熱量：{remaining_calories} kcal
- 蛋白質缺口：{protein_gap} g
- 飲食目標：{goal_type}（loss=減重，gain=增肌，maintain=維持）

輸出格式（JSON）：
{{
  "foods": [
    {{
      "name": "食物名稱",
      "name_en": "English name（若有）",
      "estimated_g": 180,
      "calories": 280,
      "protein_g": 22,
      "carb_g": 25,
      "fat_g": 9,
      "confidence": 0.88,
      "confidence_tier": "high｜medium｜low",
      "size_reference": "以直徑15cm盤子作為比例尺"
    }}
  ],
  "total_calories": 520,
  "macros": {{
    "protein_g": 28,
    "carb_g": 55,
    "fat_g": 15,
    "fiber_g": 4
  }},
  "confidence": 0.82,
  "confidence_tier": "high",
  "low_confidence_warnings": ["豆腐乳拌空心菜 confidence 0.55，建議手動輸入"],
  "nutrition_advice": "針對這餐的飲食建議，不超過3句話",
  "remaining_after_meal": {remaining_calories} - 520 = {remaining_after_meal} kcal"
}}

注意：
- 份量估算應參考亞洲常見份量標準（白飯一碗約200g，雞腿一隻約150g等）
- 不要猜測完全無法辨識的食材，標註為「無法辨識」並略過
- confidence < 0.6 的項目請在 low_confidence_warnings 陣列中說明
"""


BEFORE_AFTER_ANALYSIS_PROMPT_TEMPLATE = """你是一個專業的飲食記帳分析師。請比較**餐前**與**餐後**的兩張照片，估算這頓飯的實際攝取量。

任務：
1. 比對兩張照片，估算每樣食物被消耗的比例（100% = 完全吃光，0% = 完全沒吃）
2. 計算實際攝取的份量（原始份量 × 消耗比例）
3. 若拍攝角度不同無法比對，請說明並使用「餐前照」單獨估算

使用者資訊：
- 拍這餐前剩餘熱量：{remaining_calories} kcal
- 蛋白質缺口：{protein_gap} g

輸出格式（JSON）：
{{
  "consumed_foods": [
    {{
      "name": "食物名稱",
      "original_g": 200,
      "consumed_pct": 80,
      "consumed_g": 160,
      "calories": 240,
      "protein_g": 18,
      "carb_g": 28,
      "fat_g": 7,
      "confidence": 0.75,
      "note": "飯有剩約20%"
    }}
  ],
  "total_consumed": {{
    "calories": 380,
    "protein_g": 32,
    "carb_g": 50,
    "fat_g": 12
  }},
  "confidence": 0.72,
  "confidence_tier": "medium",
  "leftover_description": "飯約剩20%、青菜約50%",
  "calorie_estimate_range": {{"min": 340, "max": 420}},
  "nutrition_advice": "針對這餐攝取狀況的建議，不超過3句話",
  "low_confidence_warnings": []
}}

注意：
- 若兩張照片拍攝角度或光線差異太大，請在 confidence 標註 low 並說明原因
- 飲料若難以估算份量，請標註容量範圍（如現打果汁 250-350ml）
"""


# ---------------------------------------------------------------------------
# Structured output schema hints (for LLM system prompt)
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA_HINT = """
重要：你的輸出必須是有效的 JSON 物件，不要包含 markdown 程式碼 block 標記。
回應的 JSON 結構必須完全符合上述格式。
confidence 欄位必須是 0.0 到 1.0 的數字。
不要臆測資訊，若無法確認請明確標註 confidence 與估算範圍。
"""


# ---------------------------------------------------------------------------
# Agent prompt builder (the main entry point)
# ---------------------------------------------------------------------------

def build_llm_prompt(
    scenario: AnalysisScenario,
    image_available: bool = True,
    **context: Any,
) -> tuple[str, str]:
    """
    Build the full prompt (system + user) and user instruction for the
    Agent framework's multimodal LLM to process an image.

    Args:
        scenario: MENU | FOOD | BEFORE_AFTER
        image_available: Set to False if no image will be provided
                         (returns the text-only version for confirmation steps)
        **context: Scenario-specific fields (see templates above)

    Returns:
        (system_prompt, user_message) — pass both to your multimodal LLM.
        The LLM's JSON response should then be passed to parse_llm_response().
    """
    scenario_context = {
        "goal_type": context.get("goal_type", "loss"),
        "remaining_calories": context.get("remaining_calories", 0),
        "protein_gap": context.get("protein_gap", 0),
        "remaining_after_meal": max(
            context.get("remaining_calories", 0) - context.get("estimated_meal_calories", 0), 0
        ),
        "daily_calorie_target": context.get("daily_calorie_target", 0),
        "protein_target_g": context.get("protein_target_g", 0),
    }

    if scenario == AnalysisScenario.MENU:
        template = MENU_ANALYSIS_PROMPT_TEMPLATE
        system_role = "你是一個專業的營養諮詢師，專精於台灣與亞洲料理菜單分析。"
    elif scenario == AnalysisScenario.FOOD:
        template = FOOD_ANALYSIS_PROMPT_TEMPLATE
        system_role = "你是一個專業的營養辨識AI，專精於亞洲與台式料理的份量估算。"
    else:  # BEFORE_AFTER
        template = BEFORE_AFTER_ANALYSIS_PROMPT_TEMPLATE
        system_role = "你是一個專業的飲食記帳分析師，專精於估算實際攝取量。"

    user_message = template.format(**scenario_context) + RESPONSE_SCHEMA_HINT

    if not image_available:
        user_message = (
            "【提示】目前沒有圖片可供分析。\n"
            "請根據以下文字描述來估算營養成分：\n\n" + user_message
        )

    system_prompt = (
        f"{system_role}\n\n"
        "你將收到一張食物或菜單的照片。請根據所見內容分析並以 JSON 格式回應。\n"
        "重要：輸出乾淨的 JSON，不要用 markdown 程式碼 block 包裝。"
    )

    return system_prompt, user_message


# ---------------------------------------------------------------------------
# Response parser (parses LLM JSON → MealAnalysisResult)
# ---------------------------------------------------------------------------

def parse_llm_response(
    scenario: AnalysisScenario,
    llm_json: Dict[str, Any],
) -> MealAnalysisResult:
    """
    Parse and validate the LLM's structured JSON response into a
    MealAnalysisResult dataclass.

    Applies confidence tier classification and collects low-confidence warnings.
    """
    confidence = float(llm_json.get("overall_confidence") or llm_json.get("confidence") or 0.7)
    confidence_tier = _confidence_tier(confidence)

    low_confidence_warnings: List[str] = []

    # ── MENU scenario ────────────────────────────────────────────────────────
    if scenario == AnalysisScenario.MENU:
        readable_items = llm_json.get("readable_items", [])
        foods = []
        for item in readable_items:
            conf = float(item.get("confidence", 0.7))
            if conf < 0.6:
                low_confidence_warnings.append(
                    f"「{item.get('name')}」confidence {conf:.0%}，建議手動確認"
                )
            foods.append(
                IdentifiedFood(
                    name=item.get("name", "未知"),
                    name_en=item.get("name_en"),
                    estimated_g=0.0,  # menu analysis doesn't estimate gram weight
                    confidence=conf,
                    confidence_tier=_confidence_tier(conf),
                )
            )

        recommended = llm_json.get("recommended", [])
        avoid = llm_json.get("avoid", [])

        result = MealAnalysisResult(
            scenario="menu",
            foods=foods,
            confidence=confidence,
            confidence_tier=confidence_tier,
            low_confidence_warnings=low_confidence_warnings,
            nutrition_advice=llm_json.get("nutrition_advice", ""),
            raw_llm_response=llm_json,
        )
        return result

    # ── FOOD / BEFORE_AFTER scenario ───────────────────────────────────────
    is_before_after = scenario == AnalysisScenario.BEFORE_AFTER
    key = "consumed_foods" if is_before_after else "foods"
    items = llm_json.get(key, [])
    nutrition_key = "total_consumed" if is_before_after else "macros"

    parsed_foods: List[IdentifiedFood] = []
    for item in items:
        conf = float(item.get("confidence", 0.7))
        if conf < 0.6:
            low_confidence_warnings.append(
                f"「{item.get('name')}」confidence {conf:.0%}，建議手動確認"
            )
        parsed_foods.append(
            IdentifiedFood(
                name=item.get("name", "未知"),
                name_en=item.get("name_en"),
                estimated_g=float(item.get("estimated_g") or item.get("consumed_g", 0)),
                confidence=conf,
                confidence_tier=_confidence_tier(conf),
            )
        )

    nutrition_raw = llm_json.get(nutrition_key, {})
    total_calories = float(
        llm_json.get("total_consumed", {}).get("calories")
        if is_before_after
        else llm_json.get("total_calories", 0)
    )

    nutrition = NutritionEstimate(
        calories=total_calories,
        protein_g=float(nutrition_raw.get("protein_g", 0)),
        carb_g=float(nutrition_raw.get("carb_g", 0)),
        fat_g=float(nutrition_raw.get("fat_g", 0)),
        fiber_g=float(nutrition_raw.get("fiber_g", 0)),
        sodium_mg=float(nutrition_raw.get("sodium_mg", 0)),
        confidence=confidence,
        confidence_tier=confidence_tier,
    )

    advice = llm_json.get("nutrition_advice", "")
    if is_before_after and llm_json.get("leftover_description"):
        advice = f"（剩餘說明：{llm_json['leftover_description']}）{advice}"

    return MealAnalysisResult(
        scenario=scenario.value,
        foods=parsed_foods,
        total_nutrition=nutrition,
        confidence=confidence,
        confidence_tier=confidence_tier,
        low_confidence_warnings=low_confidence_warnings,
        nutrition_advice=advice,
        raw_llm_response=llm_json,
    )


def _confidence_tier(confidence: float) -> str:
    if confidence >= 0.85:
        return ConfidenceTier.HIGH.value
    elif confidence >= 0.6:
        return ConfidenceTier.MEDIUM.value
    return ConfidenceTier.LOW.value


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_analysis_result(result: MealAnalysisResult, remaining_calories: int = 0) -> str:
    """Format a MealAnalysisResult into human-readable text for the user."""

    if result.scenario == "menu":
        return _format_menu_result(result)

    lines = ["📊 這餐的營養分析"]

    if remaining_calories:
        lines.append(f"熱量：{int(result.total_nutrition.calories)} kcal（今日剩餘：{remaining_calories} kcal）")
    else:
        lines.append(f"熱量：約 {int(result.total_nutrition.calories)} kcal")

    if result.total_nutrition:
        n = result.total_nutrition
        lines.append(
            f"巨量營養素：蛋白質 {n.protein_g:.0f}g｜碳水 {n.carb_g:.0f}g｜脂肪 {n.fat_g:.0f}g"
        )
        if n.fiber_g:
            lines.append(f"膳食纖維：{n.fiber_g:.0f}g")

    if result.foods:
        lines.append("\n食物明細：")
        for food in result.foods:
            g = f"{food.estimated_g:.0f}g" if food.estimated_g else "份量不詳"
            conf_icon = "🟢" if food.confidence >= 0.85 else ("🟡" if food.confidence >= 0.6 else "🔴")
            lines.append(f"{conf_icon} {food.name}（{g}，confidence {food.confidence:.0%}）")

    if result.low_confidence_warnings:
        lines.append("\n⚠️ 低信心項目：")
        for w in result.low_confidence_warnings:
            lines.append(f"  • {w}")

    if result.nutrition_advice:
        lines.append(f"\n💬 營養師建議：{result.nutrition_advice}")

    if remaining_calories and result.total_nutrition:
        after = remaining_calories - result.total_nutrition.calories
        sign = "+" if after >= 0 else ""
        lines.append(f"\n攝取後剩餘：{sign}{int(after)} kcal")

    return "\n".join(lines)


def _format_menu_result(result: MealAnalysisResult) -> str:
    lines = ["📋 菜單分析結果"]

    if result.foods:
        lines.append("\n可辨識菜餚：")
        for food in result.foods:
            conf_icon = "🟢" if food.confidence >= 0.85 else ("🟡" if food.confidence >= 0.6 else "🔴")
            lines.append(f"{conf_icon} {food.name}")

    r = result.raw_llm_response or {}
    if r.get("recommended"):
        lines.append("\n✅ 推薦：")
        for item in r["recommended"]:
            lines.append(f"  • {item}")

    if r.get("avoid"):
        lines.append("\n❌ 建議避免：")
        for item in r["avoid"]:
            lines.append(f"  • {item}")

    if r.get("combo_suggestion"):
        lines.append(f"\n🍽️ 最佳搭配：{r['combo_suggestion']}")

    if result.nutrition_advice:
        lines.append(f"\n💬 建議：{result.nutrition_advice}")

    return "\n".join(lines)


def format_llm_prompt_only(scenario: str, **context: Any) -> str:
    """
    Convenience: return just the user-message prompt for the given scenario.
    Useful when the agent wants to inspect the prompt without running analysis.
    """
    scen = AnalysisScenario(scenario)
    _, user_msg = build_llm_prompt(scen, image_available=True, **context)
    return user_msg


# ---------------------------------------------------------------------------
# CLI for testing (simulates a round-trip with mock LLM response)
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Phase 3 food analyzer — prompt builder and parser.")
    parser.add_argument("--scenario", choices=["menu", "food", "before_after"], required=True)
    parser.add_argument("--remaining-calories", type=int, default=600)
    parser.add_argument("--protein-gap", type=int, default=30)
    parser.add_argument("--goal-type", default="loss")
    parser.add_argument("--show-prompt", action="store_true")
    parser.add_argument("--mock-response", help="Path to JSON file simulating LLM response")
    args = parser.parse_args()

    context = {
        "remaining_calories": args.remaining_calories,
        "protein_gap": args.protein_gap,
        "goal_type": args.goal_type,
    }

    system_prompt, user_message = build_llm_prompt(
        AnalysisScenario(args.scenario), image_available=True, **context
    )

    if args.show_prompt:
        print("=== SYSTEM PROMPT ===")
        print(system_prompt)
        print()
        print("=== USER MESSAGE ===")
        print(user_message)
        return

    if args.mock_response:
        llm_json = json.loads(Path(args.mock_response).read_text(encoding="utf-8"))
    else:
        print("No --mock-response given. Showing prompt only:")
        print(user_message)
        return

    result = parse_llm_response(AnalysisScenario(args.scenario), llm_json)
    print(format_analysis_result(result, args.remaining_calories))


if __name__ == "__main__":
    main()