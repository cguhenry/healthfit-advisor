#!/usr/bin/env python3
"""
gi_guide.py — Phase 6: Glycemic Index (GI) food guidance.

Provides low-GI eating strategies for blood-sugar-conscious weight management:
- Classify foods into low/medium/high GI tiers
- Recommend food swaps (high → low GI alternatives)
- Eating-order strategy (protein+veg first, carbs last)
- Meal-phase guidance (pre-workout, post-workout, evening)

Data sources:
- University of Sydney GI Database
- Taiwan FDA Food Nutrition Database (supplemental)
- USDA FoodData Central (supplemental)

Usage (CLI):
    python3 scripts/gi_guide.py classify --food "白米飯"
    python3 scripts/gi_guide.py swap --food "白麵包"
    python3 scripts/gi_guide.py strategy --meal lunch
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ─────────────────────────────────────────────────────────────
# GI Food Database
# ─────────────────────────────────────────────────────────────

# GI classification thresholds (University of Sydney criteria)
# Low: ≤55, Medium: 56–69, High: ≥70
GI_LOW = 55
GI_HIGH = 70

# Comprehensive GI food database (GI value, tier, category)
# GI values sourced from University of Sydney GI Database
_FOOD_GI_DB: dict[str, dict[str, object]] = {
    # ── Grains & Rice ──
    "白米飯": {"gi": 83, "tier": "high", "category": "穀物"},
    "糙米飯": {"gi": 50, "tier": "low", "category": "穀物"},
    "五穀飯": {"gi": 55, "tier": "low", "category": "穀物"},
    "白粥": {"gi": 88, "tier": "high", "category": "穀物"},
    "燕麥粥": {"gi": 55, "tier": "low", "category": "穀物"},
    "燕麥片": {"gi": 55, "tier": "low", "category": "穀物"},
    "即食燕麥": {"gi": 79, "tier": "high", "category": "穀物"},
    "白吐司": {"gi": 75, "tier": "high", "category": "穀物"},
    "全麥吐司": {"gi": 50, "tier": "low", "category": "穀物"},
    "白麵包": {"gi": 71, "tier": "high", "category": "穀物"},
    "全麥麵包": {"gi": 53, "tier": "low", "category": "穀物"},
    "饅頭": {"gi": 68, "tier": "medium", "category": "穀物"},
    "白麵條": {"gi": 60, "tier": "medium", "category": "穀物"},
    "蕎麥麵": {"gi": 50, "tier": "low", "category": "穀物"},
    "義大利麵": {"gi": 45, "tier": "low", "category": "穀物"},
    "烏龍麵": {"gi": 58, "tier": "medium", "category": "穀物"},
    "米粉": {"gi": 55, "tier": "low", "category": "穀物"},
    "冬粉": {"gi": 33, "tier": "low", "category": "穀物"},
    "年糕": {"gi": 82, "tier": "high", "category": "穀物"},
    "糯米飯": {"gi": 87, "tier": "high", "category": "穀物"},
    "粽子": {"gi": 83, "tier": "high", "category": "穀物"},
    "壽司": {"gi": 52, "tier": "low", "category": "穀物"},
    # ── Root Vegetables ──
    "馬鈴薯": {"gi": 78, "tier": "high", "category": "根莖類"},
    "烤馬鈴薯": {"gi": 85, "tier": "high", "category": "根莖類"},
    "地瓜": {"gi": 44, "tier": "low", "category": "根莖類"},
    "烤地瓜": {"gi": 54, "tier": "low", "category": "根莖類"},
    "山藥": {"gi": 37, "tier": "low", "category": "根莖類"},
    "芋頭": {"gi": 48, "tier": "low", "category": "根莖類"},
    "南瓜": {"gi": 51, "tier": "low", "category": "根莖類"},
    "玉米": {"gi": 52, "tier": "low", "category": "根莖類"},
    "胡蘿蔔": {"gi": 39, "tier": "low", "category": "根莖類"},
    # ── Fruits ──
    "西瓜": {"gi": 72, "tier": "high", "category": "水果"},
    "鳳梨": {"gi": 59, "tier": "medium", "category": "水果"},
    "香蕉": {"gi": 51, "tier": "low", "category": "水果"},
    "蘋果": {"gi": 36, "tier": "low", "category": "水果"},
    "奇異果": {"gi": 42, "tier": "low", "category": "水果"},
    "葡萄": {"gi": 53, "tier": "low", "category": "水果"},
    "芒果": {"gi": 48, "tier": "low", "category": "水果"},
    "梨": {"gi": 38, "tier": "low", "category": "水果"},
    "芭樂": {"gi": 12, "tier": "low", "category": "水果"},
    "草莓": {"gi": 40, "tier": "low", "category": "水果"},
    "荔枝": {"gi": 57, "tier": "medium", "category": "水果"},
    "龍眼": {"gi": 57, "tier": "medium", "category": "水果"},
    "柳橙": {"gi": 43, "tier": "low", "category": "水果"},
    "柚子": {"gi": 25, "tier": "low", "category": "水果"},
    "木瓜": {"gi": 60, "tier": "medium", "category": "水果"},
    "哈密瓜": {"gi": 65, "tier": "medium", "category": "水果"},
    # ── Beverages ──
    "可樂": {"gi": 63, "tier": "medium", "category": "飲料"},
    "運動飲料": {"gi": 78, "tier": "high", "category": "飲料"},
    "柳橙汁": {"gi": 50, "tier": "low", "category": "飲料"},
    "蘋果汁": {"gi": 41, "tier": "low", "category": "飲料"},
    "豆漿": {"gi": 34, "tier": "low", "category": "飲料"},
    "牛奶": {"gi": 27, "tier": "low", "category": "飲料"},
    "優格": {"gi": 36, "tier": "low", "category": "飲料"},
    # ── Snacks ──
    "洋芋片": {"gi": 56, "tier": "medium", "category": "零食"},
    "餅乾": {"gi": 62, "tier": "medium", "category": "零食"},
    "巧克力": {"gi": 40, "tier": "low", "category": "零食"},
    "冰淇淋": {"gi": 61, "tier": "medium", "category": "零食"},
    "爆米花": {"gi": 62, "tier": "medium", "category": "零食"},
    # ── Legumes (all naturally low-GI) ──
    "黃豆": {"gi": 18, "tier": "low", "category": "豆類"},
    "豆腐": {"gi": 15, "tier": "low", "category": "豆類"},
    "納豆": {"gi": 26, "tier": "low", "category": "豆類"},
    "紅豆": {"gi": 28, "tier": "low", "category": "豆類"},
    "綠豆": {"gi": 31, "tier": "low", "category": "豆類"},
    "毛豆": {"gi": 18, "tier": "low", "category": "豆類"},
    "鷹嘴豆": {"gi": 28, "tier": "low", "category": "豆類"},
    "扁豆": {"gi": 29, "tier": "low", "category": "豆類"},
    # ── Desserts ──
    "蛋糕": {"gi": 65, "tier": "medium", "category": "甜點"},
    "甜甜圈": {"gi": 76, "tier": "high", "category": "甜點"},
    "月餅": {"gi": 62, "tier": "medium", "category": "甜點"},
    "布丁": {"gi": 44, "tier": "low", "category": "甜點"},
    # ── Sugars ──
    "白糖": {"gi": 65, "tier": "medium", "category": "糖類"},
    "蜂蜜": {"gi": 55, "tier": "low", "category": "糖類"},
    "楓糖漿": {"gi": 54, "tier": "low", "category": "糖類"},
    "果糖": {"gi": 19, "tier": "low", "category": "糖類"},
}

# GI swap recommendations: high → low alternative
_GI_SWAPS: dict[str, str] = {
    "白米飯": "糙米飯（GI=50）或五穀飯（GI=55），纖維更多、飽足感更長",
    "白粥": "燕麥粥（GI=55），添加堅果增加蛋白質與健康脂肪",
    "白吐司": "全麥吐司（GI=50），或選酸種麵包（延緩血糖上升）",
    "白麵包": "全麥麵包（GI=53），搭配蛋白質（蛋/雞肉）降低整餐GI",
    "白麵條": "蕎麥麵（GI=50）或義大利麵（GI=45），口感Q彈且低GI",
    "即食燕麥": "傳統燕麥片（GI=55），雖然慢一點但血糖反應差很多",
    "饅頭": "全麥饅頭或雜糧饅頭，添加堅果增加纖維",
    "馬鈴薯": "地瓜（GI=44）或芋頭（GI=48），抗性澱粉含量更高",
    "烤馬鈴薯": "烤地瓜（GI=54），但放涼後抗性澱粉增加、GI更低",
    "西瓜": "芭樂（GI=12）或蘋果（GI=36），體積大熱量低又高纖",
    "鳳梨": "奇異果（GI=42）或藍莓，維生素C也豐富",
    "可樂": "無糖茶（GI=0）或氣泡水加檸檬片，零熱量零GI",
    "運動飲料": "椰子水或稀釋檸檬水 + 少許鹽，補充電解質不升糖",
    "蛋糕": "一小塊黑巧克力（GI=40）+ 希臘優格，滿足甜食又不升糖",
    "甜甜圈": "全麥吐司 + 天然花生醬，高蛋白質降低整體GI",
    "年糕": "蕎麥麵或冬粉，口感相似但GI不到一半",
    "糯米飯": "糙米飯（GI=50），糯米極高GI建議完全避開",
    "粽子": "若無法避免，選份量小的 + 搭配大量蔬菜一起吃",
}

# Phase-specific eating strategy
_PHASE_STRATEGIES: dict[str, str] = {
    "早餐": (
        "🌅 早餐低GI策略：\n"
        "1. 蛋白質優先：先吃蛋、豆腐或希臘優格（蛋白質抑制血糖峰值）\n"
        "2. 主食選擇：全麥吐司/燕麥片/蕎麥麵（GI<55）\n"
        "3. 飲料：無糖豆漿/牛奶/無糖拿鐵（遠離含糖飲料）\n"
        "4. 水果搭配：飯後吃蘋果/奇異果，不要空腹吃高GI水果"
    ),
    "午餐": (
        "☀️ 午餐低GI策略：\n"
        "1. 進食順序：蔬菜湯 → 蛋白質 → 蔬菜 → 主食（可降餐後血糖30–40%）\n"
        "2. 主食替換：白米飯→糙米飯/五穀飯，或減半白飯 + 增加青菜\n"
        "3. 外食技巧：便當選「少飯多菜」、湯麵選蕎麥麵\n"
        "4. 餐後散步：午餐後散步15分鐘，可顯著降低餐後血糖峰值"
    ),
    "晚餐": (
        "🌙 晚餐低GI策略：\n"
        "1. 碳水減量：晚餐碳水化合物攝取不超過整天40%\n"
        "2. 主食選擇：冬粉/蒟蒻麵（接近零GI），或半碗糙米飯\n"
        "3. 蛋白質充足：魚/雞胸/豆腐，幫助夜間修復\n"
        "4. 時間控制：睡前3小時不要進食（降低夜間血糖波動）\n"
        "5. 點心替代：嘴饞→小番茄/毛豆/無糖優格"
    ),
    "點心": (
        "🍪 點心低GI策略：\n"
        "1. 最佳選擇：堅果（GI≈0）、希臘優格（GI=36）、水煮蛋（GI=0）\n"
        "2. 中等選擇：一小塊黑巧克力（GI=40）、蘋果（GI=36）\n"
        "3. 避免：餅乾/蛋糕/含糖飲料（高GI + 空熱量）\n"
        "4. 份量控制：點心不超過150 kcal"
    ),
    "運動前": (
        "🏃 運動前GI策略（運動前1–2小時）：\n"
        "1. 中低GI碳水：燕麥片/地瓜/全麥吐司（穩定釋放能量）\n"
        "2. 避免高GI：不要吃白飯/白麵包（可能導致運動中低血糖）\n"
        "3. 份量：約100–200 kcal，不要吃太飽"
    ),
    "運動後": (
        "💪 運動後GI策略（運動後30分鐘內）：\n"
        "1. 中高GI碳水：白米飯/香蕉（快速補充肌肉肝醣）—此時高GI反而好！\n"
        "2. 蛋白質：雞胸肉/蛋/乳清蛋白（>20g蛋白質）\n"
        "3. 比例：碳水:蛋白質 ≈ 3:1\n"
        "4. 時機：運動後30分鐘是「代謝窗口期」，此時高GI碳水不會囤積脂肪"
    ),
}


# ─────────────────────────────────────────────────────────────
# Core functions
# ─────────────────────────────────────────────────────────────

def classify_food(food_name: str) -> dict:
    """Classify a food's GI tier. Returns dict with gi, tier, category, advice."""
    # Exact match
    info = _FOOD_GI_DB.get(food_name)
    if info:
        return {
            "food": food_name,
            "gi": info["gi"],
            "tier": info["tier"],
            "category": info["category"],
            "found": True,
            "advice": _tier_advice(info["tier"]),
        }

    # Fuzzy match: try substring
    for name, info in _FOOD_GI_DB.items():
        if food_name in name or name in food_name:
            return {
                "food": name,
                "gi": info["gi"],
                "tier": info["tier"],
                "category": info["category"],
                "found": True,
                "advice": _tier_advice(info["tier"]),
                "matched_by": "fuzzy",
            }

    return {
        "food": food_name,
        "found": False,
        "advice": _unknown_advice(food_name),
    }


def _tier_advice(tier: str) -> str:
    if tier == "low":
        return "✅ 低GI食物，適合日常食用。建議搭配蛋白質效果更佳。"
    elif tier == "medium":
        return "⚠️ 中GI食物，可適量攝取。建議搭配蛋白質或健康脂肪降低整餐GI。"
    else:
        return "🔴 高GI食物，建議減少頻率。若真的想吃，先吃蔬菜和蛋白質再吃主食、飯後散步15分鐘可降低血糖反應。"


def _unknown_advice(food_name: str) -> str:
    return (
        f"ℹ️ 資料庫中尚未收錄「{food_name}」的GI值。\n"
        "一般建議：\n"
        "• 天然食物比加工食品低GI\n"
        "• 含有纖維、蛋白質、脂肪的食物GI較低\n"
        "• 烹調時間越長GI越高（如煮爛的白粥 > 白飯）\n"
        "• 放涼後澱粉類食物GI會降低（抗性澱粉效應）"
    )


def recommend_swap(high_gi_food: str) -> str:
    """Recommend a low-GI alternative for a high-GI food."""
    swap = _GI_SWAPS.get(high_gi_food)

    if swap:
        return f"🔄 「{high_gi_food}」替換建議：\n{swap}"

    # Try classification
    info = classify_food(high_gi_food)
    if info["found"] and info["tier"] == "low":
        return f"✅ 「{high_gi_food}」已是低GI食物（GI={info['gi']}），不需替換。"

    # Generic swap advice
    return (
        f"🔄 「{high_gi_food}」尚未有精確替換建議。\n"
        "通用原則：\n"
        "• 選擇同類食物中的全穀/原型版本\n"
        "• 增加蔬菜和蛋白質比例來降低整餐GI\n"
        "• 改變進食順序：先蛋白質和蔬菜，最後吃主食"
    )


def get_meal_strategy(meal_type: str) -> str:
    """Get phase-specific low-GI eating strategy."""
    meal_type = meal_type.strip()
    for key in _PHASE_STRATEGIES:
        if key in meal_type or meal_type in key:
            return _PHASE_STRATEGIES[key]
    # Default strategy
    return (
        "🍽️ 通用低GI進食策略：\n"
        "1. 進食順序：蛋白質/蔬菜 → 主食（降餐後血糖30–40%）\n"
        "2. 選擇原型食物：全穀 > 精製、天然 > 加工\n"
        "3. 餐後活動：散步15分鐘顯著降血糖\n"
        "4. 每餐都要有蛋白質：降低整餐GI\n"
        "5. 避免含糖飲料：液體糖吸收最快\n"
    )


def get_food_list_by_tier(tier: str) -> list[dict]:
    """Get all foods of a specific GI tier."""
    result = []
    for name, info in _FOOD_GI_DB.items():
        if info["tier"] == tier:
            result.append({"food": name, "gi": info["gi"], "category": info["category"]})
    return sorted(result, key=lambda x: x["gi"])


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def cmd_classify(args: argparse.Namespace) -> None:
    result = classify_food(args.food)
    if result["found"]:
        tier_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}
        emoji = tier_emoji.get(result["tier"], "⚪")
        print(f"{emoji} {result['food']}")
        print(f"   GI 值：{result['gi']}（{result['tier'].upper()}）")
        print(f"   分類：{result['category']}")
        print(f"   {result['advice']}")
    else:
        print(result["advice"])

    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_swap(args: argparse.Namespace) -> None:
    print(recommend_swap(args.food))


def cmd_strategy(args: argparse.Namespace) -> None:
    print(get_meal_strategy(args.meal))


def cmd_list(args: argparse.Namespace) -> None:
    tier = args.tier or "all"
    if tier == "all":
        for t in ["high", "medium", "low"]:
            tier_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}
            foods = get_food_list_by_tier(t)
            print(f"\n{tier_emoji[t]} {t.upper()}（{len(foods)}項）")
            for f in foods[:20]:
                print(f"  GI={f['gi']:>3d}  {f['food']}（{f['category']}）")
            if len(foods) > 20:
                print(f"  ... 還有 {len(foods) - 20} 項")
    else:
        foods = get_food_list_by_tier(tier)
        for f in foods:
            print(f"GI={f['gi']:>3d}  {f['food']}（{f['category']}）")


def main() -> None:
    parser = argparse.ArgumentParser(prog="gi_guide.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_classify = sub.add_parser("classify", help="Classify food GI tier")
    p_classify.add_argument("--food", "-f", required=True, help="Food name")
    p_classify.add_argument("--json", action="store_true")

    p_swap = sub.add_parser("swap", help="Suggest a low-GI swap")
    p_swap.add_argument("--food", "-f", required=True, help="Food name")

    p_strat = sub.add_parser("strategy", help="Get meal-phase GI strategy")
    p_strat.add_argument("--meal", "-m", required=True,
                         help="Meal type: 早餐/午餐/晚餐/點心/運動前/運動後")

    p_list = sub.add_parser("list", help="List foods by GI tier")
    p_list.add_argument("--tier", choices=["low", "medium", "high"])

    args = parser.parse_args()

    if args.command == "classify":
        cmd_classify(args)
    elif args.command == "swap":
        cmd_swap(args)
    elif args.command == "strategy":
        cmd_strategy(args)
    elif args.command == "list":
        cmd_list(args)


if __name__ == "__main__":
    main()