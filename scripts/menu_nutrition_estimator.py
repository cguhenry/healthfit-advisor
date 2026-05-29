#!/usr/bin/env python3
from __future__ import annotations

from dining_models import MenuItem


def _add_tag(item: MenuItem, tag: str) -> None:
    if tag not in item.tags:
        item.tags.append(tag)


def _set_if_empty(
    item: MenuItem,
    *,
    calories: float,
    protein_g: float,
    carb_g: float | None = None,
    fat_g: float | None = None,
    confidence: float = 0.55,
) -> None:
    if item.estimated_calories is None:
        item.estimated_calories = calories
    if item.estimated_protein_g is None:
        item.estimated_protein_g = protein_g
    if carb_g is not None and item.estimated_carb_g is None:
        item.estimated_carb_g = carb_g
    if fat_g is not None and item.estimated_fat_g is None:
        item.estimated_fat_g = fat_g
    item.confidence = max(item.confidence, confidence)


def estimate_menu_item_nutrition(item: MenuItem, scene: str | None = None) -> MenuItem:
    """
    外食品項營養估算。

    第一版採 rule-based。
    未來可改成：
    1. 先查 food_nutrition_cache / FoodDBLookup
    2. 查不到再 rule-based
    3. 仍查不到再 LLM 估算
    """
    name = item.name

    # -------------------------
    # 便當（須在雞胸通用規則之前，先匹配先贏）
    # -------------------------
    if "雞胸便當" in name:
        _set_if_empty(item, calories=620, protein_g=45, carb_g=75, fat_g=15, confidence=0.6)
        _add_tag(item, "high_protein")
        if "飯半碗" in name:
            item.estimated_calories = max(0, (item.estimated_calories or 620) - 180)
            item.estimated_carb_g = max(0, (item.estimated_carb_g or 75) - 40)
            _add_tag(item, "portion_control")
        return item

    if "烤雞腿便當" in name or "滷雞腿便當" in name:
        _set_if_empty(item, calories=750, protein_g=42, carb_g=85, fat_g=28, confidence=0.6)
        _add_tag(item, "high_protein")
        if "飯半碗" in name:
            item.estimated_calories = max(0, (item.estimated_calories or 750) - 180)
            item.estimated_carb_g = max(0, (item.estimated_carb_g or 85) - 40)
            _add_tag(item, "portion_control")
        return item

    if "炸" in name and "便當" in name:
        _set_if_empty(item, calories=900, protein_g=35, carb_g=90, fat_g=45, confidence=0.55)
        _add_tag(item, "fried")
        _add_tag(item, "high_calorie")
        return item

    if "控肉" in name or "三寶飯" in name:
        _set_if_empty(item, calories=950, protein_g=28, carb_g=85, fat_g=55, confidence=0.55)
        _add_tag(item, "high_fat")
        _add_tag(item, "high_calorie")
        return item

    # -------------------------
    # 通用飲料（鮮奶茶要搶在無糖茶之前，因為「鮮奶茶」含「茶」）
    # -------------------------
    if "鮮奶茶" in name:
        _set_if_empty(item, calories=180, protein_g=8, carb_g=12, fat_g=8, confidence=0.6)
        if "無糖" in name:
            _add_tag(item, "low_sugar")
        if "去珍珠" in name:
            _add_tag(item, "reduced_toppings")
        return item

    if "無糖" in name \
       and any(x in name for x in ["綠茶", "青茶", "烏龍茶", "紅茶"]) \
       and "奶" not in name:
        # 不含奶才算無糖純茶；鮮奶茶 / 奶茶已搶先處理
        _set_if_empty(item, calories=0, protein_g=0, carb_g=0, fat_g=0, confidence=0.8)
        _add_tag(item, "low_calorie")
        _add_tag(item, "low_sugar")
        return item

    if "珍珠奶茶" in name:
        _set_if_empty(item, calories=550, protein_g=8, carb_g=85, fat_g=18, confidence=0.65)
        _add_tag(item, "sugary_drink")
        _add_tag(item, "high_calorie")
        return item

    if "奶蓋" in name:
        _set_if_empty(item, calories=450, protein_g=5, carb_g=45, fat_g=25, confidence=0.6)
        _add_tag(item, "sugary_drink")
        _add_tag(item, "high_fat")
        _add_tag(item, "high_calorie")
        return item

    if "奶茶" in name:
        _set_if_empty(item, calories=300, protein_g=5, carb_g=45, fat_g=10, confidence=0.6)
        _add_tag(item, "sugary_drink")
        return item

    if "無糖豆漿" in name:
        _set_if_empty(item, calories=160, protein_g=12, carb_g=8, fat_g=8, confidence=0.7)
        _add_tag(item, "high_protein")
        _add_tag(item, "low_sugar")
        return item

    # -------------------------
    # 早餐店
    # -------------------------
    if "茶葉蛋" in name:
        _set_if_empty(item, calories=80, protein_g=7, carb_g=1, fat_g=5, confidence=0.75)
        _add_tag(item, "high_protein")
        _add_tag(item, "low_carb")
        return item

    if "蛋餅" in name:
        calories = 420
        protein = 14
        carb = 45
        fat = 20

        if "加蛋" in name:
            calories += 80
            protein += 7
            fat += 5
            _add_tag(item, "higher_protein")

        _set_if_empty(item, calories=calories, protein_g=protein, carb_g=carb, fat_g=fat, confidence=0.6)
        _add_tag(item, "moderate_calorie")
        return item

    if "鮪魚" in name and "吐司" in name:
        _set_if_empty(item, calories=480, protein_g=24, carb_g=45, fat_g=20, confidence=0.6)
        _add_tag(item, "high_protein")
        if "少醬" in name:
            item.estimated_calories = max(0, (item.estimated_calories or 480) - 80)
            item.estimated_fat_g = max(0, (item.estimated_fat_g or 20) - 8)
            _add_tag(item, "reduced_sauce")
        return item

    if "里肌" in name and "吐司" in name:
        _set_if_empty(item, calories=500, protein_g=28, carb_g=45, fat_g=18, confidence=0.6)
        _add_tag(item, "high_protein")
        if "少醬" in name:
            item.estimated_calories = max(0, (item.estimated_calories or 500) - 70)
            item.estimated_fat_g = max(0, (item.estimated_fat_g or 18) - 7)
            _add_tag(item, "reduced_sauce")
        return item

    if "薯餅" in name:
        _set_if_empty(item, calories=180, protein_g=2, carb_g=20, fat_g=10, confidence=0.65)
        _add_tag(item, "fried")
        _add_tag(item, "low_protein")
        return item

    if "熱狗" in name or "雞塊" in name:
        _set_if_empty(item, calories=220, protein_g=8, carb_g=15, fat_g=14, confidence=0.55)
        _add_tag(item, "processed")
        _add_tag(item, "fried")
        return item

    if "鐵板麵" in name:
        _set_if_empty(item, calories=650, protein_g=18, carb_g=85, fat_g=25, confidence=0.55)
        _add_tag(item, "high_carb")
        _add_tag(item, "high_calorie")
        return item

    # -------------------------
    # 便利商店
    # -------------------------
    # 雞胸通用規則：便當已在前面先匹配，先搶到先贏，這裡只處理非便當的雞胸品項
    if ("烤雞胸" in name or "雞胸" in name) and "便當" not in name:
        _set_if_empty(item, calories=180, protein_g=30, carb_g=5, fat_g=4, confidence=0.75)
        _add_tag(item, "high_protein")
        _add_tag(item, "low_fat")
        return item

    if "地瓜" in name:
        _set_if_empty(item, calories=220, protein_g=3, carb_g=52, fat_g=0.5, confidence=0.7)
        _add_tag(item, "whole_food")
        _add_tag(item, "moderate_gi")
        return item

    if "生菜沙拉" in name or "沙拉" in name:
        _set_if_empty(item, calories=180, protein_g=8, carb_g=15, fat_g=8, confidence=0.55)
        _add_tag(item, "vegetable")
        _add_tag(item, "low_calorie")
        return item

    if "飯糰" in name or "御飯糰" in name:
        _set_if_empty(item, calories=250, protein_g=6, carb_g=48, fat_g=4, confidence=0.65)
        _add_tag(item, "high_carb")
        return item

    # -------------------------
    # 便當  ── 見上方「便當」區塊（往前移動以高於便利商店雞胸規則）
    # -------------------------
    if "滷蛋" in name:
        _set_if_empty(item, calories=80, protein_g=7, carb_g=1, fat_g=5, confidence=0.7)
        _add_tag(item, "high_protein")
        return item

    if "青菜" in name and ("豆腐" in name or "豆干" in name) and ("雞" in name or "肉" in name):
        _set_if_empty(item, calories=420, protein_g=35, carb_g=25, fat_g=16, confidence=0.55)
        _add_tag(item, "high_protein")
        _add_tag(item, "vegetable")
        return item

    if "王子麵" in name:
        _set_if_empty(item, calories=300, protein_g=8, carb_g=45, fat_g=12, confidence=0.65)
        _add_tag(item, "high_carb")
        _add_tag(item, "processed")
        return item

    if "甜不辣" in name or "貢丸" in name or "米血" in name:
        _set_if_empty(item, calories=250, protein_g=10, carb_g=25, fat_g=12, confidence=0.55)
        _add_tag(item, "processed")
        return item

    # -------------------------
    # 火鍋
    # -------------------------
    if "雞肉鍋" in name or "海鮮鍋" in name:
        _set_if_empty(item, calories=600, protein_g=40, carb_g=45, fat_g=25, confidence=0.55)
        _add_tag(item, "high_protein")
        return item

    if "牛肉鍋" in name or "豬肉鍋" in name:
        _set_if_empty(item, calories=750, protein_g=38, carb_g=50, fat_g=40, confidence=0.55)
        _add_tag(item, "high_protein")
        return item

    if "火鍋料" in name or "沙茶" in name:
        _set_if_empty(item, calories=350, protein_g=8, carb_g=35, fat_g=20, confidence=0.5)
        _add_tag(item, "processed")
        _add_tag(item, "high_calorie")
        return item

    # -------------------------
    # 麵店
    # -------------------------
    if "牛肉麵" in name:
        _set_if_empty(item, calories=800, protein_g=35, carb_g=90, fat_g=30, confidence=0.55)
        _add_tag(item, "high_protein")
        _add_tag(item, "high_carb")
        return item

    if "乾麵" in name:
        _set_if_empty(item, calories=550, protein_g=15, carb_g=75, fat_g=20, confidence=0.55)
        _add_tag(item, "high_carb")
        return item

    if "湯麵" in name or "陽春麵" in name:
        _set_if_empty(item, calories=450, protein_g=12, carb_g=70, fat_g=10, confidence=0.55)
        _add_tag(item, "high_carb")
        _add_tag(item, "low_protein")
        return item

    if "燙青菜" in name:
        _set_if_empty(item, calories=120, protein_g=4, carb_g=10, fat_g=6, confidence=0.6)
        _add_tag(item, "vegetable")
        _add_tag(item, "low_calorie")
        return item

    # -------------------------
    # fallback — but skip if item already has credible external data
    # -------------------------
    has_external_nutrition = (
        item.estimated_calories is not None
        or item.estimated_protein_g is not None
        or item.estimated_carb_g is not None
        or item.estimated_fat_g is not None
    )

    if has_external_nutrition:
        # brand_db / user_restaurant_profile items already carry verified data;
        # don't demote their confidence just because rule-based missed them.
        if item.source in ("brand_db", "user_restaurant_profile"):
            item.confidence = max(item.confidence, 0.75)
        return item

    _add_tag(item, "unknown_nutrition")
    item.confidence = min(item.confidence, 0.45)
    return item