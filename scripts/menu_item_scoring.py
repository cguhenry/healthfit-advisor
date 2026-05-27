#!/usr/bin/env python3
from __future__ import annotations

from dining_models import MenuItem, ScoredMenuItem, GoalType


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
    """
    score = 50.0
    reasons: list[str] = []
    modifications: list[str] = []

    calories = item.estimated_calories
    protein = item.estimated_protein_g

    # -------------------------
    # 熱量評分
    # -------------------------
    if calories is not None:
        if calories <= calories_remaining:
            score += 20
            reasons.append("熱量在今日剩餘額度內")
        else:
            over = calories - calories_remaining
            penalty = min(35, over / 20)
            score -= penalty
            reasons.append(f"熱量可能超出今日剩餘額度約 {over:.0f} kcal")

            if over > 100:
                modifications.append("建議減少份量，或主食減半")

        if goal_type == "loss" and calories <= 500:
            score += 8
            reasons.append("較符合減脂期熱量控制")

        if goal_type == "gain" and calories >= 500:
            score += 5
            reasons.append("增肌期可接受較高熱量，但仍需注意食物品質")
        else:
            score -= 8
            reasons.append("營養資料不足，需保守看待")

    # -------------------------
    # 蛋白質評分
    # -------------------------
    if protein is not None:
        if protein >= 30:
            score += 20
            reasons.append("蛋白質含量高")
        elif protein >= 20:
            score += 15
            reasons.append("蛋白質含量不錯")
        elif protein >= 12:
            score += 8
            reasons.append("蛋白質含量中等")
        elif protein_gap_g > 20:
            score -= 10
            reasons.append("目前蛋白質缺口較大，但此品項蛋白質不足")

        if protein_gap_g > 20 and protein >= 25:
            score += 8
            reasons.append("有助於補足今日蛋白質缺口")
    else:
        score -= 5
        reasons.append("蛋白質資料不足")

    # -------------------------
    # 標籤評分
    # -------------------------
    good_tags = {
        "high_protein",
        "higher_protein",
        "low_calorie",
        "low_sugar",
        "vegetable",
        "portion_control",
        "whole_food",
        "low_fat",
        "reduced_sauce",
        "low_carb",
    }

    bad_tags = {
        "fried",
        "sugary_drink",
        "high_fat",
        "high_calorie",
        "low_protein",
        "unknown_nutrition",
        "processed",
        "high_carb",
    }

    for tag in set(item.tags):
        if tag in good_tags:
            score += 6
        if tag in bad_tags:
            score -= 10

    # -------------------------
    # 低 GI 需求
    # -------------------------
    if require_low_gi:
        if "high_carb" in item.tags:
            score -= 10
            reasons.append("低 GI 需求下，需注意此品項碳水比例")
            modifications.append("建議主食減半，並搭配蛋白質與蔬菜")
        if "sugary_drink" in item.tags:
            score -= 20
            reasons.append("含糖飲料不適合低 GI 或血糖控制需求")
            modifications.append("飲料改無糖茶或無糖豆漿")

    # -------------------------
    # 修改建議
    # -------------------------
    if "sugary_drink" in item.tags:
        modifications.append("飲料建議改無糖或去配料")

    if "fried" in item.tags:
        modifications.append("若可選擇，優先改成烤、滷、蒸")

    if "high_calorie" in item.tags:
        modifications.append("建議改小份或與他人分食")

    if "high_carb" in item.tags:
        modifications.append("主食可減半，並增加蛋白質或青菜")

    if "processed" in item.tags:
        modifications.append("加工食品建議減量，不作為主要蛋白質來源")

    # 去重但保留順序
    modifications = list(dict.fromkeys(modifications))
    reasons = list(dict.fromkeys(reasons))

    score = round(max(0, min(100, score)), 2)

    return ScoredMenuItem(
        item=item,
        score=score,
        reasons=reasons,
        modifications=modifications,
    )