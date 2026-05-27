#!/usr/bin/env python3
"""
menu_image_analyzer.py — Feature F-2: 菜單照片 → MenuItem list

使用 vision LLM / OCR 將菜單圖片轉成 MenuItem list。

注意：
    這個函式只負責「讀菜單」。
    不負責推薦。
    推薦交給 dining_context_engine.recommend_from_menu_items()。

預期輸出格式：
    [
        MenuItem(name="鮪魚蛋吐司", price=55, category="吐司", source="menu_image"),
        MenuItem(name="奶茶", price=25, category="飲料", source="menu_image"),
    ]

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

from dining_models import MenuItem


def analyze_menu_image(image_path: str) -> list[MenuItem]:
    """
    TODO:
    使用 vision LLM / OCR 將菜單圖片轉成 MenuItem list。

    目前為 stub，未來實作方向：
    - 使用 vision model（如 GPT-4o vision）識別圖片中文字
    - 搭配 OCR 萃取價格、品項
    - 依店家常見品項營養資料庫補足熱量估算

    Parameters
    ----------
    image_path : str
        菜單圖片檔案路徑（支援 jpg / png / webp）

    Returns
    -------
    list[MenuItem]
        圖片中識別出的所有品項，source 欄位為 "menu_image"
    """
    raise NotImplementedError("menu_image_analyzer is not implemented yet")