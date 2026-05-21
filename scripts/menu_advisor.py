#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional

CuisineType = Literal["taiwanese", "japanese", "western", "korean", "southeast_asian", "any"]
EatingLocation = Literal["home", "convenience_store", "buffet", "chain_restaurant", "restaurant"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]

ALLOWED_CUISINES = {"taiwanese", "japanese", "western", "korean", "southeast_asian", "any"}
ALLOWED_LOCATIONS = {"home", "convenience_store", "buffet", "chain_restaurant", "restaurant"}
ALLOWED_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}

MEAL_CALORIE_SHARE = {
    "breakfast": 0.25,
    "lunch": 0.35,
    "dinner": 0.35,
    "snack": 0.12,
}


@dataclass(frozen=True)
class MenuOption:
    name: str
    cuisine_type: CuisineType
    eating_location: EatingLocation
    meal_types: List[MealType]
    calories: int
    protein_g: int
    carb_g: int
    fat_g: int
    fiber_g: int = 0
    sodium_mg: int = 0
    items: List[str] = field(default_factory=list)
    avoid: List[str] = field(default_factory=list)
    tips: List[str] = field(default_factory=list)


@dataclass
class Recommendation:
    target_calories: int
    target_protein_g: int
    primary: MenuOption
    alternatives: List[MenuOption]
    avoid: List[str]
    rationale: List[str]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_calories": self.target_calories,
            "target_protein_g": self.target_protein_g,
            "primary": asdict(self.primary),
            "alternatives": [asdict(option) for option in self.alternatives],
            "avoid": self.avoid,
            "rationale": self.rationale,
            "warnings": self.warnings,
        }


MENU_OPTIONS = [
    MenuOption(
        name="超商高蛋白均衡午餐",
        cuisine_type="any",
        eating_location="convenience_store",
        meal_types=["lunch", "dinner"],
        calories=560,
        protein_g=34,
        carb_g=62,
        fat_g=18,
        fiber_g=7,
        sodium_mg=1250,
        items=["鮭魚或雞肉飯糰 1 個", "茶葉蛋 2 顆", "無糖豆漿 1 瓶", "生菜沙拉或關東煮蔬菜 1 份"],
        avoid=["含糖飲料", "炸雞排便當", "奶油白醬義大利麵"],
        tips=["優先選原型蛋白質與無糖飲品", "沙拉醬減半或分開加"],
    ),
    MenuOption(
        name="自助餐減脂盤",
        cuisine_type="taiwanese",
        eating_location="buffet",
        meal_types=["lunch", "dinner"],
        calories=640,
        protein_g=42,
        carb_g=70,
        fat_g=20,
        fiber_g=9,
        sodium_mg=1500,
        items=["半碗飯或地瓜 1 份", "滷雞腿去皮或清蒸魚 1 份", "青菜 2 份", "豆腐或滷蛋 1 份"],
        avoid=["三杯、糖醋、勾芡類主菜", "炸排骨", "滷汁淋飯"],
        tips=["飯量先固定，蛋白質和蔬菜補足", "請店家少淋滷汁可明顯降低鈉與油脂"],
    ),
    MenuOption(
        name="日式定食保守版",
        cuisine_type="japanese",
        eating_location="restaurant",
        meal_types=["lunch", "dinner"],
        calories=680,
        protein_g=38,
        carb_g=78,
        fat_g=22,
        fiber_g=6,
        sodium_mg=1700,
        items=["烤魚或雞肉定食", "白飯半份到 2/3 份", "味噌湯半碗", "海帶芽或青菜小菜"],
        avoid=["炸豬排咖哩", "拉麵加叉燒加飯", "美乃滋系沙拉"],
        tips=["湯品鈉高，喝半碗即可", "若蛋白質不足，加一份冷豆腐比加炸物好"],
    ),
    MenuOption(
        name="韓式拌飯調整版",
        cuisine_type="korean",
        eating_location="restaurant",
        meal_types=["lunch", "dinner"],
        calories=720,
        protein_g=36,
        carb_g=92,
        fat_g=20,
        fiber_g=8,
        sodium_mg=1850,
        items=["石鍋拌飯少醬", "加蛋或豆腐", "泡菜少量", "海帶湯半碗"],
        avoid=["韓式炸雞", "起司辣炒年糕", "醬料全加"],
        tips=["辣醬分開加，先用一半", "若當天碳水已高，飯留 1/4 碗"],
    ),
    MenuOption(
        name="地中海雞肉碗",
        cuisine_type="western",
        eating_location="chain_restaurant",
        meal_types=["lunch", "dinner"],
        calories=650,
        protein_g=45,
        carb_g=58,
        fat_g=24,
        fiber_g=10,
        sodium_mg=1200,
        items=["烤雞胸或雞腿排", "糙米或馬鈴薯 1 份", "沙拉蔬菜 2 份", "橄欖油醬減半"],
        avoid=["雙層漢堡套餐", "薯條加含糖飲料", "奶油濃湯"],
        tips=["醬料熱量密度高，先減半", "選烤物比炸物更容易貼近目標"],
    ),
    MenuOption(
        name="東南亞河粉輕盈版",
        cuisine_type="southeast_asian",
        eating_location="restaurant",
        meal_types=["lunch", "dinner"],
        calories=620,
        protein_g=32,
        carb_g=86,
        fat_g=14,
        fiber_g=5,
        sodium_mg=1800,
        items=["清湯牛肉或雞肉河粉", "加青菜", "湯少喝", "不加含糖飲料"],
        avoid=["椰奶咖哩飯", "炸春捲", "煉乳飲品"],
        tips=["湯麵鈉通常偏高，吃料不喝完湯", "若蛋白質缺口大，加蛋或加肉"],
    ),
    MenuOption(
        name="在家簡易增肌餐",
        cuisine_type="any",
        eating_location="home",
        meal_types=["lunch", "dinner"],
        calories=760,
        protein_g=55,
        carb_g=82,
        fat_g=22,
        fiber_g=10,
        sodium_mg=850,
        items=["雞胸或瘦牛/豬 180g", "白飯或馬鈴薯 1.5 份", "青菜 2 份", "橄欖油或堅果少量"],
        avoid=["只吃蛋白粉不吃正餐", "大量加工肉品"],
        tips=["增肌餐重點是穩定蛋白質與可持續總熱量", "訓練日前後可把碳水放高一點"],
    ),
    MenuOption(
        name="早餐高蛋白組合",
        cuisine_type="any",
        eating_location="convenience_store",
        meal_types=["breakfast"],
        calories=430,
        protein_g=30,
        carb_g=45,
        fat_g=13,
        fiber_g=5,
        sodium_mg=900,
        items=["無糖豆漿 1 瓶", "茶葉蛋 2 顆", "地瓜 1 條或飯糰 1 個"],
        avoid=["甜麵包加含糖咖啡", "奶酥厚片", "大杯含糖奶茶"],
        tips=["早餐先補蛋白質，午晚餐比較不容易失控"],
    ),
    MenuOption(
        name="點心補蛋白",
        cuisine_type="any",
        eating_location="convenience_store",
        meal_types=["snack"],
        calories=240,
        protein_g=18,
        carb_g=22,
        fat_g=8,
        fiber_g=3,
        sodium_mg=450,
        items=["希臘優格或高蛋白飲 1 份", "香蕉 1 根或小地瓜 1 條"],
        avoid=["洋芋片", "含糖手搖飲", "蛋糕甜點"],
        tips=["點心用來補缺口，不要變成額外一餐"],
    ),
]


class MenuAdvisor:
    def recommend_meal(
        self,
        *,
        cuisine_type: CuisineType = "any",
        eating_location: EatingLocation,
        meal_type: MealType,
        daily_calorie_target: Optional[int] = None,
        remaining_daily_calories: Optional[int] = None,
        protein_target_g: Optional[int] = None,
        protein_consumed_g: int = 0,
    ) -> Recommendation:
        self._validate(cuisine_type, eating_location, meal_type)
        target_calories = self._target_calories(meal_type, daily_calorie_target, remaining_daily_calories)
        target_protein_g = self._target_protein(meal_type, protein_target_g, protein_consumed_g)

        candidates = self._candidates(cuisine_type, eating_location, meal_type)
        ranked = sorted(candidates, key=lambda option: self._score(option, target_calories, target_protein_g))
        if not ranked:
            raise ValueError("no menu options matched the requested context")

        primary = ranked[0]
        alternatives = ranked[1:3]
        warnings = self._warnings(primary, target_calories, target_protein_g)
        rationale = self.explain_recommendation(primary, target_calories, target_protein_g)
        avoid = list(dict.fromkeys(primary.avoid + self._general_avoidance(meal_type)))
        return Recommendation(
            target_calories=target_calories,
            target_protein_g=target_protein_g,
            primary=primary,
            alternatives=alternatives,
            avoid=avoid,
            rationale=rationale,
            warnings=warnings,
        )

    def explain_recommendation(self, menu: MenuOption, target_calories: int, target_protein_g: int) -> List[str]:
        calorie_gap = menu.calories - target_calories
        protein_gap = menu.protein_g - target_protein_g
        rationale = [
            f"熱量約 {menu.calories} kcal，和本餐目標 {target_calories} kcal 差距 {calorie_gap:+d} kcal。",
            f"蛋白質約 {menu.protein_g} g，和本餐目標 {target_protein_g} g 差距 {protein_gap:+d} g。",
        ]
        rationale.extend(menu.tips)
        if menu.sodium_mg >= 1600:
            rationale.append("鈉含量可能偏高，湯汁、醬料或醃漬配菜建議減量。")
        if menu.fiber_g < 6 and menu.eating_location != "snack":
            rationale.append("膳食纖維偏少，建議加一份青菜或水果。")
        return rationale

    def format_recommendation(self, recommendation: Recommendation) -> str:
        primary = recommendation.primary
        lines = [
            f"{primary.name}（目標約 {recommendation.target_calories} kcal）",
            "",
            "建議搭配：",
        ]
        lines.extend(f"- {item}" for item in primary.items)
        lines.append(
            f"合計：約 {primary.calories} kcal｜蛋白質 {primary.protein_g} g｜碳水 {primary.carb_g} g｜脂肪 {primary.fat_g} g"
        )
        lines.append("")
        lines.append("搭配原因：")
        lines.extend(f"- {reason}" for reason in recommendation.rationale)
        if recommendation.alternatives:
            lines.append("")
            lines.append("替代選項：")
            lines.extend(f"- {option.name}（約 {option.calories} kcal / 蛋白質 {option.protein_g} g）" for option in recommendation.alternatives)
        if recommendation.avoid:
            lines.append("")
            lines.append("避免或減量：")
            lines.extend(f"- {item}" for item in recommendation.avoid)
        if recommendation.warnings:
            lines.append("")
            lines.append("注意：")
            lines.extend(f"- {warning}" for warning in recommendation.warnings)
        return "\n".join(lines)

    @staticmethod
    def _validate(cuisine_type: str, eating_location: str, meal_type: str) -> None:
        if cuisine_type not in ALLOWED_CUISINES:
            raise ValueError(f"cuisine_type must be one of: {', '.join(sorted(ALLOWED_CUISINES))}")
        if eating_location not in ALLOWED_LOCATIONS:
            raise ValueError(f"eating_location must be one of: {', '.join(sorted(ALLOWED_LOCATIONS))}")
        if meal_type not in ALLOWED_MEAL_TYPES:
            raise ValueError(f"meal_type must be one of: {', '.join(sorted(ALLOWED_MEAL_TYPES))}")

    @staticmethod
    def _target_calories(meal_type: MealType, daily_calorie_target: Optional[int], remaining_daily_calories: Optional[int]) -> int:
        if remaining_daily_calories is not None:
            return max(150, int(remaining_daily_calories))
        if daily_calorie_target is None:
            raise ValueError("daily_calorie_target or remaining_daily_calories is required")
        return round(daily_calorie_target * MEAL_CALORIE_SHARE[meal_type])

    @staticmethod
    def _target_protein(meal_type: MealType, protein_target_g: Optional[int], protein_consumed_g: int) -> int:
        if protein_target_g is None:
            return 15 if meal_type == "snack" else 30
        remaining = max(protein_target_g - protein_consumed_g, 0)
        if meal_type == "snack":
            return max(12, round(remaining * 0.20))
        return max(20, round(remaining * MEAL_CALORIE_SHARE[meal_type]))

    @staticmethod
    def _candidates(cuisine_type: CuisineType, eating_location: EatingLocation, meal_type: MealType) -> List[MenuOption]:
        candidate_groups = [
            lambda option: option.cuisine_type == cuisine_type and option.eating_location == eating_location,
            lambda option: cuisine_type != "any" and option.cuisine_type == cuisine_type,
            lambda option: option.cuisine_type == "any" and option.eating_location == eating_location,
            lambda option: cuisine_type == "any" and option.eating_location == eating_location,
            lambda option: option.cuisine_type == "any",
        ]
        for matcher in candidate_groups:
            matches = [option for option in MENU_OPTIONS if meal_type in option.meal_types and matcher(option)]
            if matches:
                return matches
        return [option for option in MENU_OPTIONS if meal_type in option.meal_types]

    @staticmethod
    def _score(option: MenuOption, target_calories: int, target_protein_g: int) -> float:
        calorie_score = abs(option.calories - target_calories) / max(target_calories, 1)
        protein_shortfall = max(target_protein_g - option.protein_g, 0) / max(target_protein_g, 1)
        sodium_penalty = max(option.sodium_mg - 1800, 0) / 1800
        return calorie_score + (protein_shortfall * 1.5) + (sodium_penalty * 0.35)

    @staticmethod
    def _warnings(option: MenuOption, target_calories: int, target_protein_g: int) -> List[str]:
        warnings: List[str] = []
        if option.calories > target_calories * 1.2:
            warnings.append("此建議熱量超過本餐目標 20%，建議減少主食或醬料。")
        if option.protein_g < target_protein_g * 0.8:
            warnings.append("此建議蛋白質低於本餐目標 80%，建議加蛋、豆腐、雞肉或魚。")
        if option.sodium_mg > 1800:
            warnings.append("此餐鈉含量偏高，湯汁與醬料不要喝完或全加。")
        return warnings

    @staticmethod
    def _general_avoidance(meal_type: MealType) -> List[str]:
        if meal_type == "snack":
            return ["把點心加大成正餐份量"]
        return ["含糖飲料", "炸物加大", "醬料全加"]


def recommend_from_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    advisor = MenuAdvisor()
    recommendation = advisor.recommend_meal(
        cuisine_type=payload.get("cuisine_type", "any"),
        eating_location=payload["eating_location"],
        meal_type=payload["meal_type"],
        daily_calorie_target=payload.get("daily_calorie_target"),
        remaining_daily_calories=payload.get("remaining_daily_calories"),
        protein_target_g=payload.get("protein_target_g"),
        protein_consumed_g=payload.get("protein_consumed_g", 0),
    )
    return recommendation.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Recommend a Phase 2 meal option from a HealthFit request payload.")
    parser.add_argument("payload", help="Path to JSON request payload.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    args = parser.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    advisor = MenuAdvisor()
    recommendation = advisor.recommend_meal(
        cuisine_type=payload.get("cuisine_type", "any"),
        eating_location=payload["eating_location"],
        meal_type=payload["meal_type"],
        daily_calorie_target=payload.get("daily_calorie_target"),
        remaining_daily_calories=payload.get("remaining_daily_calories"),
        protein_target_g=payload.get("protein_target_g"),
        protein_consumed_g=payload.get("protein_consumed_g", 0),
    )
    if args.format == "json":
        print(json.dumps(recommendation.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(advisor.format_recommendation(recommendation))


if __name__ == "__main__":
    main()
