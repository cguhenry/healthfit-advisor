#!/usr/bin/env python3
from __future__ import annotations

from dining_models import MenuItem, DiningRecommendation, GoalType
from restaurant_scenarios import get_scenario_template
from menu_nutrition_estimator import estimate_menu_item_nutrition
from menu_item_scoring import score_menu_item


def _unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_items_from_scenario_template(scene: str) -> list[MenuItem]:
    """
    從店家類型模板建立候選品項。

    注意：
    這些不是該店實際菜單，只是該類型店家的常見品項與推薦組合。
    """
    template = get_scenario_template(scene)

    raw_names: list[str] = []
    raw_names.extend(template.recommended_patterns)
    raw_names.extend(template.common_items)

    unique_names = _unique_keep_order(raw_names)

    return [
        MenuItem(
            name=name,
            source="scenario_template",
            confidence=0.45,
        )
        for name in unique_names
    ]


def recommend_without_menu(
    *,
    scene: str,
    calories_remaining: float,
    protein_gap_g: float,
    goal_type: GoalType = "loss",
    require_low_gi: bool = False,
    top_n: int = 5,
) -> DiningRecommendation:
    """
    沒有實際菜單照片時，用店家類型模板 fallback。
    """
    template = get_scenario_template(scene)

    items = build_items_from_scenario_template(scene)

    estimated_items = [
        estimate_menu_item_nutrition(item, scene=scene)
        for item in items
    ]

    scored = [
        score_menu_item(
            item,
            calories_remaining=calories_remaining,
            protein_gap_g=protein_gap_g,
            goal_type=goal_type,
            require_low_gi=require_low_gi,
        )
        for item in estimated_items
    ]

    scored.sort(key=lambda x: x.score, reverse=True)

    avoid_items = [
        MenuItem(
            name=name,
            source="scenario_template",
            confidence=0.45,
        )
        for name in template.avoid_patterns
    ]

    avoid_scored = [
        score_menu_item(
            estimate_menu_item_nutrition(item, scene=scene),
            calories_remaining=calories_remaining,
            protein_gap_g=protein_gap_g,
            goal_type=goal_type,
            require_low_gi=require_low_gi,
        )
        for item in avoid_items
    ]

    avoid_scored.sort(key=lambda x: x.score)

    return DiningRecommendation(
        source_mode="scenario_template",
        recommended=scored[:top_n],
        avoid=avoid_scored[:top_n],
        general_modifications=template.customization_rules,
        warnings=template.risk_notes,
        summary=(
            f"以下依照「{template.display_name}」常見品項推估，"
            "不代表該店一定有販售。若提供實際菜單照片，可做更精準推薦。"
        ),
        avoid_mode="template_patterns",
    )


def recommend_from_menu_items(
    *,
    items: list[MenuItem],
    scene: str | None,
    calories_remaining: float,
    protein_gap_g: float,
    goal_type: GoalType = "loss",
    require_low_gi: bool = False,
    top_n: int = 5,
) -> DiningRecommendation:
    """
    已有菜單品項時使用。

    未來 menu_image_analyzer 或 brand_menu_repository 都可以把資料轉成 MenuItem list，
    再呼叫此函式。
    """
    estimated_items = [
        estimate_menu_item_nutrition(item, scene=scene)
        for item in items
    ]

    scored = [
        score_menu_item(
            item,
            calories_remaining=calories_remaining,
            protein_gap_g=protein_gap_g,
            goal_type=goal_type,
            require_low_gi=require_low_gi,
        )
        for item in estimated_items
    ]

    scored.sort(key=lambda x: x.score, reverse=True)

    source_mode = items[0].source if items else "user_text"

    AVOID_SCORE_THRESHOLD = 50
    CAUTION_SCORE_THRESHOLD = 65
    recommended = [s for s in scored if s.score >= AVOID_SCORE_THRESHOLD][:top_n]
    avoid = [s for s in sorted(scored, key=lambda x: x.score) if s.score < AVOID_SCORE_THRESHOLD][:top_n]

    modifications: list[str] = []
    warnings: list[str] = []
    summary = "已根據實際菜單品項、今日剩餘熱量與蛋白質缺口排序。"

    if scene:
        try:
            template = get_scenario_template(scene)
            modifications = template.customization_rules
            warnings = template.risk_notes
        except ValueError:
            pass

    return DiningRecommendation(
        source_mode=source_mode,
        recommended=recommended,
        avoid=avoid,
        general_modifications=modifications,
        warnings=warnings,
        summary=summary,
        avoid_mode="score_threshold",
    )