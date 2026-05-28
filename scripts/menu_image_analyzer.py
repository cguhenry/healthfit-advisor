#!/usr/bin/env python3
"""
menu_image_analyzer.py — Feature F-2: 菜單照片 → MenuItem list

使用 vision LLM / OCR 將菜單圖片轉成 MenuItem list。

注意：
    這個函式只負責「讀菜單」。
    不負責推薦。
    推薦交給 dining_context_engine.recommend_from_menu_items()。

LLM 回傳格式（JSON）：
    {
        "restaurant_type": "breakfast_shop",
        "items": [
            {"name": "鮪魚蛋吐司", "price": 55, "category": "吐司", "description": null},
            {"name": "奶茶", "price": 25, "category": "飲料", "description": null}
        ]
    }

未來接上後流程：
    from menu_image_analyzer import analyze_menu_image
    from dining_context_engine import recommend_from_menu_items

    items = analyze_menu_image("menu.jpg")
    result = recommend_from_menu_items(
        items=items,
        scene="breakfast_shop",
        calories_remaining=500,
        protein_gap_g=25,
    )
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from dining_models import MenuItem


# ─────────────────────────────────────────────────────────────────────────
# JSON fence stripper
# ─────────────────────────────────────────────────────────────────────────

def _strip_json_fence(text: str) -> str:
    """
    Remove markdown code-fence wrappers from LLM output.

    Handles:
      ```json\n{...}\n```    — normal multi-line
      ```json\n{...}          — no trailing fence (LLM sometimes omits it)
      ```{...}```             — inline open+close on same line
      plain JSON             — returned as-is
    """
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()

    # Case: inline ```json{...}``` (open and close on same line)
    if len(lines) == 1 and lines[0].startswith("```"):
        inner = lines[0][3:].strip()  # remove opening ```
        # remove optional language tag and trailing ```
        inner = re.sub(r"^json\s*", "", inner, flags=re.IGNORECASE)
        inner = re.sub(r"\s*```$", "", inner)
        return inner.strip()

    # Multi-line: skip opening line (```json)
    if len(lines) >= 2 and lines[0].startswith("```"):
        lines = lines[1:]
    # Remove trailing closing ```
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    return "\n".join(lines).strip()


# ─────────────────────────────────────────────────────────────────────────
# JSON → MenuItem parser（純函式，無需 LLM）
# ─────────────────────────────────────────────────────────────────────────

def parse_menu_items_from_llm_json(raw_json: str) -> tuple[Optional[str], list[MenuItem]]:
    """Strip markdown fences then parse LLM JSON into MenuItem list."""
    data = json.loads(_strip_json_fence(raw_json))

    restaurant_type: Optional[str] = data.get("restaurant_type")
    rows: list[dict[str, Any]] = data.get("items") or []

    items: list[MenuItem] = []

    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue

        price = row.get("price")
        try:
            price = int(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        items.append(
            MenuItem(
                name=name,
                price=price,
                category=row.get("category"),
                description=row.get("description"),
                source="menu_image",
                confidence=0.65,
            )
        )

    return restaurant_type, items


# ─────────────────────────────────────────────────────────────────────────
# Vision LLM 接入點（stub；等待實作）
# ─────────────────────────────────────────────────────────────────────────

def analyze_menu_image(
    image_path: str,
    *,
    api_key: Optional[str] = None,
    model: str = "gpt-4o",
) -> list[MenuItem]:
    """
    讀取菜單圖片，使用 vision LLM 辨識並回傳 MenuItem list。

    TODO（尚未實作）：
    - 使用 vision model（如 GPT-4o vision）識別圖片中文字
    - 搭配 OCR 萃取價格、品項
    - 依店家常見品項營養資料庫補足熱量估算
    - 自動偵測 restaurant_type

    Parameters
    ----------
    image_path : str
        菜單圖片檔案路徑（支援 jpg / png / webp）
    api_key : str, optional
        API key；若未提供，嘗試讀取環境變數 OPENAI_API_KEY
    model : str
        使用的 vision model（預設 gpt-4o）

    Returns
    -------
    list[MenuItem]
        圖片中識別出的所有品項，source 欄位為 "menu_image"

    Raises
    ------
    NotImplementedError
        明確標示尚未實作；請等 API key 設定後再啟用。
    """
    raise NotImplementedError(
        "menu_image_analyzer is not implemented yet. "
        "Set OPENAI_API_KEY and implement the vision LLM call here."
    )


# ─────────────────────────────────────────────────────────────────────────
# Convenience wrapper（未来：支援直接呼叫）
# ─────────────────────────────────────────────────────────────────────────

def analyze_and_recommend(
    image_path: str,
    *,
    scene: Optional[str] = None,
    calories_remaining: float,
    protein_gap_g: float,
    goal_type: str = "loss",
    require_low_gi: bool = False,
    top_n: int = 5,
) -> tuple[list[MenuItem], Any]:  # Any = DiningRecommendation
    """
    一次性完成：讀菜單 → 估算營養 → 推薦。

    目前為 stub，未來實作後可這樣用：
        items, result = analyze_and_recommend(
            image_path="menu.jpg",
            scene="bento_shop",
            calories_remaining=500,
            protein_gap_g=25,
        )

    Parameters
    ----------
    image_path : str
    scene : str, optional
        若為 None，會從 LLM 回傳的 restaurant_type 自動推斷
    calories_remaining, protein_gap_g, goal_type, require_low_gi, top_n
        傳給 recommend_from_menu_items 的參數

    Returns
    -------
    tuple[list[MenuItem], DiningRecommendation]
    """
    raise NotImplementedError("analyze_and_recommend is not implemented yet")