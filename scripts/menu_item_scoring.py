#!/usr/bin/env python3
from __future__ import annotations

from dining_models import MenuItem, ScoredMenuItem, GoalType


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _score_calorie_fit(
    *,
    calories: float | None,
    calories_remaining: float,
    goal_type: str,
) -> tuple[float, list[str], list[str]]:
    """Calorie fitness sub-score: 0–35."""
    reasons: list[str] = []
    modifications: list[str] = []

    if calories is None:
        return 12.0, ["熱量資料不足，需保守看待"], []

    if calories_remaining <= 0:
        if calories <= 100:
            return 20.0, ["今日熱量額度很低，此品項熱量仍相對可控"], []
        return 5.0, ["今日熱量額度不足，此品項可能超出目標"], ["建議改小份或延後食用"]

    ratio = calories / calories_remaining

    if ratio <= 0.35:
        score = 35.0
        reasons.append("熱量占今日剩餘額度比例低")
    elif ratio <= 0.65:
        score = 30.0
        reasons.append("熱量在今日剩餘額度內")
    elif ratio <= 1.0:
        score = 24.0
        reasons.append("熱量接近今日剩餘額度，仍可接受")
    elif ratio <= 1.25:
        score = 15.0
        over = calories - calories_remaining
        reasons.append(f"熱量略超出今日剩餘額度約 {over:.0f} kcal")
        modifications.append("建議減少份量或主食減半")
    elif ratio <= 1.6:
        score = 8.0
        over = calories - calories_remaining
        reasons.append(f"熱量明顯超出今日剩餘額度約 {over:.0f} kcal")
        modifications.append("建議改小份，或改選低熱量品項")
    else:
        score = 2.0
        reasons.append("熱量大幅超出今日剩餘額度")
        modifications.append("不建議以原份量食用")

    if goal_type == "gain" and calories >= 500 and ratio <= 1.25:
        score += 3.0
        reasons.append("增肌期可接受較高熱量")

    return _clamp(score, 0, 35), reasons, modifications


def _score_protein_fit(
    *,
    protein: float | None,
    protein_gap_g: float,
) -> tuple[float, list[str]]:
    """Protein fitness sub-score: 0–25."""
    reasons: list[str] = []

    if protein is None:
        return 5.0, ["蛋白質資料不足"]

    if protein >= 35:
        score = 25.0
        reasons.append("蛋白質含量高")
    elif protein >= 25:
        score = 21.0
        reasons.append("蛋白質含量不錯")
    elif protein >= 15:
        score = 15.0
        reasons.append("蛋白質含量中等")
    elif protein >= 8:
        score = 9.0
        reasons.append("蛋白質偏低")
    else:
        score = 3.0
        reasons.append("蛋白質不足")

    if protein_gap_g >= 25:
        if protein >= 25:
            score += 3.0
            reasons.append("有助於補足今日蛋白質缺口")
        elif protein < 10:
            score -= 3.0
            reasons.append("目前蛋白質缺口較大，但此品項蛋白質不足")

    return _clamp(score, 0, 25), reasons


def _score_food_quality(tags: list[str]) -> tuple[float, list[str], list[str]]:
    """Food quality sub-score: 0–20."""
    reasons: list[str] = []
    modifications: list[str] = []

    tag_set = set(tags)

    score = 10.0

    good_weights = {
        "high_protein": 3.0,
        "higher_protein": 2.0,
        "low_calorie": 3.0,
        "low_sugar": 3.0,
        "vegetable": 3.0,
        "portion_control": 2.0,
        "whole_food": 3.0,
        "low_fat": 2.0,
        "reduced_sauce": 2.0,
        "low_carb": 2.0,
        "moderate_gi": 1.0,
    }

    bad_weights = {
        "fried": 4.0,
        "sugary_drink": 6.0,
        "high_fat": 4.0,
        "high_calorie": 4.0,
        "low_protein": 3.0,
        "unknown_nutrition": 3.0,
        "processed": 3.0,
        "high_carb": 2.0,
    }

    good_score = sum(weight for tag, weight in good_weights.items() if tag in tag_set)
    bad_score = sum(weight for tag, weight in bad_weights.items() if tag in tag_set)

    score += min(good_score, 8.0)
    score -= min(bad_score, 10.0)

    if tag_set & {"vegetable", "whole_food"}:
        reasons.append("食物品質較佳")
    if "sugary_drink" in tag_set:
        reasons.append("含糖飲料較不利於熱量與血糖控制")
        modifications.append("飲料建議改無糖或去配料")
    if "fried" in tag_set:
        reasons.append("油炸品項脂肪較高")
        modifications.append("若可選擇，優先改成烤、滷、蒸")
    if "high_carb" in tag_set:
        modifications.append("主食可減半，並增加蛋白質或青菜")
    if "processed" in tag_set:
        modifications.append("加工食品建議減量，不作為主要蛋白質來源")

    return _clamp(score, 0, 20), reasons, modifications


def _score_goal_fit(
    *,
    calories: float | None,
    protein: float | None,
    tags: list[str],
    goal_type: str,
    require_low_gi: bool,
) -> tuple[float, list[str], list[str]]:
    """Goal alignment sub-score: 0–10."""
    reasons: list[str] = []
    modifications: list[str] = []

    tag_set = set(tags)
    score = 5.0

    if goal_type == "loss":
        if calories is not None and calories <= 500:
            score += 3.0
            reasons.append("較符合減脂期熱量控制")
        if "high_calorie" in tag_set or "fried" in tag_set or "sugary_drink" in tag_set:
            score -= 3.0

    elif goal_type == "gain":
        if protein is not None and protein >= 25:
            score += 3.0
            reasons.append("增肌期蛋白質表現較佳")
        if calories is not None and calories >= 500:
            score += 1.0

    elif goal_type == "maintain":
        if calories is not None and 300 <= calories <= 700:
            score += 2.0
            reasons.append("熱量較適合維持期的一餐")

    if require_low_gi:
        if "sugary_drink" in tag_set:
            score -= 5.0
            reasons.append("含糖飲料不適合低 GI 或血糖控制需求")
            modifications.append("飲料改無糖茶或無糖豆漿")
        if "high_carb" in tag_set:
            score -= 2.0
            reasons.append("低 GI 需求下，需注意碳水比例")
            modifications.append("建議主食減半，搭配蛋白質與蔬菜")
        if "low_sugar" in tag_set or "whole_food" in tag_set:
            score += 2.0

    return _clamp(score, 0, 10), reasons, modifications


def _score_confidence(item: MenuItem) -> tuple[float, list[str]]:
    """Data confidence sub-score: 0–10."""
    reasons: list[str] = []

    confidence = getattr(item, "confidence", 0.5) or 0.5
    score = _clamp(float(confidence) * 10.0, 0, 10)

    if confidence < 0.5:
        reasons.append("營養估算信心較低，建議保守看待")

    return score, reasons


def score_menu_item(
    item: MenuItem,
    *,
    calories_remaining: float,
    protein_gap_g: float,
    goal_type: GoalType = "loss",
    require_low_gi: bool = False,
) -> ScoredMenuItem:
    """
    根據使用者今日狀態對菜單品項評分。

    分數範圍：0~100。
    分項：
      - 熱量適配：35
      - 蛋白質適配：25
      - 食物品質：20
      - 目標適配：10
      - 資料信心：10
    """
    calories = item.estimated_calories
    protein = item.estimated_protein_g
    tags = item.tags or []

    calorie_score, calorie_reasons, calorie_mods = _score_calorie_fit(
        calories=calories,
        calories_remaining=calories_remaining,
        goal_type=goal_type,
    )

    protein_score, protein_reasons = _score_protein_fit(
        protein=protein,
        protein_gap_g=protein_gap_g,
    )

    quality_score, quality_reasons, quality_mods = _score_food_quality(tags)

    goal_score, goal_reasons, goal_mods = _score_goal_fit(
        calories=calories,
        protein=protein,
        tags=tags,
        goal_type=goal_type,
        require_low_gi=require_low_gi,
    )

    confidence_score, confidence_reasons = _score_confidence(item)

    raw_score = (
        calorie_score
        + protein_score
        + quality_score
        + goal_score
        + confidence_score
    )

    reasons = (
        calorie_reasons
        + protein_reasons
        + quality_reasons
        + goal_reasons
        + confidence_reasons
    )

    modifications = calorie_mods + quality_mods + goal_mods

    # 去重但保留順序
    reasons = list(dict.fromkeys(reasons))
    modifications = list(dict.fromkeys(modifications))

    score = round(_clamp(raw_score, 0, 100), 2)

    return ScoredMenuItem(
        item=item,
        score=score,
        reasons=reasons,
        modifications=modifications,
    )