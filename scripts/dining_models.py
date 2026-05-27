#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal


MenuSource = Literal[
    "menu_image",
    "brand_db",
    "scenario_template",
    "user_restaurant_profile",
    "user_text",
]


GoalType = Literal["loss", "maintain", "gain"]


@dataclass
class MenuItem:
    """
    單一菜單品項。

    source:
    - menu_image: 由菜單照片辨識
    - brand_db: 由品牌菜單資料庫取得
    - scenario_template: 由店家類型模板推估
    - user_restaurant_profile: 使用者自訂常去店家
    - user_text: 使用者直接輸入
    """

    name: str
    price: int | None = None
    category: str | None = None
    description: str | None = None

    estimated_calories: float | None = None
    estimated_protein_g: float | None = None
    estimated_carb_g: float | None = None
    estimated_fat_g: float | None = None
    estimated_sodium_mg: float | None = None

    tags: list[str] = field(default_factory=list)
    source: MenuSource = "scenario_template"
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RestaurantScenarioTemplate:
    """
    店家類型模板。

    這不是固定菜單，而是：
    - 常見品項
    - 推薦方向
    - 避免方向
    - 點餐修改規則
    - 場景風險提醒
    """

    scene: str
    display_name: str
    common_items: list[str]
    recommended_patterns: list[str]
    avoid_patterns: list[str]
    customization_rules: list[str]
    risk_notes: list[str]


@dataclass
class ScoredMenuItem:
    item: MenuItem
    score: float
    reasons: list[str]
    modifications: list[str]

    def to_dict(self) -> dict:
        return {
            "item": self.item.to_dict(),
            "score": self.score,
            "reasons": self.reasons,
            "modifications": self.modifications,
        }


@dataclass
class DiningRecommendation:
    source_mode: MenuSource
    recommended: list[ScoredMenuItem]
    avoid: list[ScoredMenuItem]
    general_modifications: list[str]
    warnings: list[str]
    summary: str

    def to_dict(self) -> dict:
        return {
            "source_mode": self.source_mode,
            "recommended": [x.to_dict() for x in self.recommended],
            "avoid": [x.to_dict() for x in self.avoid],
            "general_modifications": self.general_modifications,
            "warnings": self.warnings,
            "summary": self.summary,
        }