#!/usr/bin/env python3
"""
brand_menu_repository.py — Feature F-3: 品牌菜單資料庫

從 JSON 檔案載入品牌菜單，轉成 MenuItem list。

JSON 格式範例：
    [
        {
            "brand": "八方雲集",
            "name": "招牌鍋貼 10 顆",
            "category": "鍋貼",
            "calories": 650,
            "protein_g": 22,
            "carb_g": 70,
            "fat_g": 32,
            "tags": ["high_calorie", "fried"]
        }
    ]

未來可以建立：
    assets/brand_menus/bafang_yunji.json
    assets/brand_menus/convenience_store.json

使用方式：
    from brand_menu_repository import load_brand_menu_from_json

    items = load_brand_menu_from_json("assets/brand_menus/bafang_yunji.json", brand="八方雲集")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from dining_models import MenuItem


def load_brand_menu_from_json(
    path: str | Path,
    brand: str,
    *,
    default_confidence: float = 0.85,
) -> list[MenuItem]:
    """
    從 JSON 載入品牌菜單。

    Parameters
    ----------
    path : str | Path
        JSON 檔案路徑
    brand : str
        要過濾的品牌名稱（只回傳 matching brand 的品項）
    default_confidence : float
        當 JSON 未提供 confidence 時的預設值（預設 0.85）

    Returns
    -------
    list[MenuItem]
        符合品牌的 MenuItem list，source 為 "brand_db"
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    items: list[MenuItem] = []

    for row in data:
        if row.get("brand") != brand:
            continue

        tags: list[str] = list(row.get("tags") or [])

        # 自動給定 confidence（若未提供）
        confidence = float(row.get("confidence", default_confidence))

        items.append(
            MenuItem(
                name=str(row["name"]),
                category=row.get("category"),
                estimated_calories=_maybe_float(row.get("calories")),
                estimated_protein_g=_maybe_float(row.get("protein_g")),
                estimated_carb_g=_maybe_float(row.get("carb_g")),
                estimated_fat_g=_maybe_float(row.get("fat_g")),
                estimated_sodium_mg=_maybe_float(row.get("sodium_mg")),
                tags=tags,
                source="brand_db",
                confidence=confidence,
            )
        )

    return items


def load_all_brands_from_json(path: str | Path) -> dict[str, list[MenuItem]]:
    """
    從 JSON 一次載入所有品牌，回傳 {brand: [MenuItem, ...]}。

    適用於不知道要查哪個品牌、只想列出所有可用品牌時。
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    result: dict[str, list[MenuItem]] = {}

    for row in data:
        brand = str(row.get("brand", ""))
        if not brand:
            continue

        if brand not in result:
            result[brand] = []

        tags: list[str] = list(row.get("tags") or [])
        confidence = float(row.get("confidence", 0.85))

        result[brand].append(
            MenuItem(
                name=str(row["name"]),
                category=row.get("category"),
                estimated_calories=_maybe_float(row.get("calories")),
                estimated_protein_g=_maybe_float(row.get("protein_g")),
                estimated_carb_g=_maybe_float(row.get("carb_g")),
                estimated_fat_g=_maybe_float(row.get("fat_g")),
                estimated_sodium_mg=_maybe_float(row.get("sodium_mg")),
                tags=tags,
                source="brand_db",
                confidence=confidence,
            )
        )

    return result


def _maybe_float(value: Optional[dict[str, float] | float | int | str]) -> float | None:
    """Convert a numeric value to float, or return None if not present."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None