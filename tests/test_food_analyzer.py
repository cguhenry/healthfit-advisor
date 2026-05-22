import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

MODULE_PATH = ROOT / "scripts" / "food_analyzer.py"
SPEC = importlib.util.spec_from_file_location("fa", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

build_llm_prompt = MODULE.build_llm_prompt
parse_llm_response = MODULE.parse_llm_response
format_analysis_result = MODULE.format_analysis_result
AnalysisScenario = MODULE.AnalysisScenario


# ---------------------------------------------------------------------------
# Fixtures (mock LLM responses)
# ---------------------------------------------------------------------------

MOCK_MENU_RESPONSE = {
    "readable_items": [
        {
            "name": "烤雞腿便當",
            "name_en": "Roasted chicken leg lunchbox",
            "portion_size": "大",
            "estimated_calories": 720,
            "protein_g": 35,
            "carb_g": 80,
            "fat_g": 22,
            "confidence": 0.88,
            "source_note": "烤雞腿油脂較少，優於炸排骨"
        },
        {
            "name": "麻辣牛肉麵",
            "name_en": "Spicy beef noodle soup",
            "portion_size": "大",
            "estimated_calories": 850,
            "protein_g": 28,
            "carb_g": 110,
            "fat_g": 25,
            "confidence": 0.72,
            "source_note": "勾芡湯底熱量較高"
        },
        {
            "name": "未知食物X",
            "name_en": None,
            "portion_size": "不明",
            "estimated_calories": 300,
            "protein_g": 5,
            "carb_g": 40,
            "fat_g": 10,
            "confidence": 0.45,  # low
            "source_note": "confidence 0.45，低信心"
        },
    ],
    "recommended": ["烤雞腿便當"],
    "avoid": ["麻辣牛肉麵"],
    "combo_suggestion": "烤雞腿便當 + 青菜，控制在 750 kcal 內",
    "overall_confidence": 0.78,
    "nutrition_advice": "今日建議選烤雞腿便當，飯量減半以控制在目標熱量內。"
}

MOCK_FOOD_RESPONSE = {
    "foods": [
        {
            "name": "白飯",
            "name_en": "steamed rice",
            "estimated_g": 200,
            "calories": 260,
            "protein_g": 4.5,
            "carb_g": 58,
            "fat_g": 0.6,
            "confidence": 0.92,
            "confidence_tier": "high",
            "size_reference": "直徑14cm碗約200g"
        },
        {
            "name": "烤鯖魚",
            "name_en": "grilled mackerel",
            "estimated_g": 120,
            "calories": 210,
            "protein_g": 18,
            "carb_g": 0,
            "fat_g": 15,
            "confidence": 0.85,
            "confidence_tier": "high",
            "size_reference": "手掌大小一片約120g"
        },
        {
            "name": "空心菜",
            "name_en": "water spinach",
            "estimated_g": 100,
            "calories": 30,
            "protein_g": 2,
            "carb_g": 5,
            "fat_g": 0.3,
            "confidence": 0.55,  # low
            "confidence_tier": "low",
            "size_reference": "約一碗青菜份量"
        },
    ],
    "total_calories": 500,
    "macros": {"protein_g": 25, "carb_g": 63, "fat_g": 16, "fiber_g": 4},
    "confidence": 0.80,
    "confidence_tier": "medium",
    "low_confidence_warnings": ["空心菜 confidence 55%，建議手動輸入"],
    "nutrition_advice": "蛋白質充足，建議晚餐補足蔬菜纖維。",
    "remaining_after_meal": 600 - 500
}

MOCK_BEFORE_AFTER_RESPONSE = {
    "consumed_foods": [
        {
            "name": "排骨便當",
            "original_g": 350,
            "consumed_pct": 85,
            "consumed_g": 298,
            "calories": 550,
            "protein_g": 32,
            "carb_g": 65,
            "fat_g": 18,
            "confidence": 0.78,
            "note": "飯有剩約15%"
        },
        {
            "name": "蛋花湯",
            "original_g": 150,
            "consumed_pct": 100,
            "consumed_g": 150,
            "calories": 60,
            "protein_g": 4,
            "carb_g": 3,
            "fat_g": 3,
            "confidence": 0.65,
            "note": None
        },
    ],
    "total_consumed": {"calories": 610, "protein_g": 36, "carb_g": 68, "fat_g": 21},
    "confidence": 0.72,
    "confidence_tier": "medium",
    "leftover_description": "飯約剩15%，青菜約30%",
    "calorie_estimate_range": {"min": 560, "max": 660},
    "nutrition_advice": "蛋白質達標，總熱量略超建議。",
    "low_confidence_warnings": []
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildLLMPrompt(unittest.TestCase):
    def test_menu_scenario_returns_system_and_user(self):
        sys_prompt, user_msg = build_llm_prompt(
            AnalysisScenario.MENU,
            daily_calorie_target=1800,
            remaining_calories=650,
            protein_target_g=140,
        )
        self.assertIn("營養諮詢", sys_prompt)
        self.assertIn("菜單照片", user_msg)
        self.assertIn("readable_items", user_msg)
        self.assertIn("650", user_msg)  # remaining_calories substituted

    def test_food_scenario_includes_context(self):
        _, user_msg = build_llm_prompt(
            AnalysisScenario.FOOD,
            remaining_calories=500,
            protein_gap=25,
            goal_type="loss",
        )
        self.assertIn("500", user_msg)
        self.assertIn("25", user_msg)
        self.assertIn("loss", user_msg)
        self.assertIn("foods", user_msg)
        self.assertIn("estimated_g", user_msg)

    def test_before_after_scenario_includes_context(self):
        _, user_msg = build_llm_prompt(
            AnalysisScenario.BEFORE_AFTER,
            remaining_calories=600,
            protein_gap=20,
        )
        self.assertIn("600", user_msg)
        self.assertIn("consumed_foods", user_msg)
        self.assertIn("consumed_pct", user_msg)


class TestParseLLMResponse(unittest.TestCase):
    def test_parse_menu_response(self):
        result = parse_llm_response(AnalysisScenario.MENU, MOCK_MENU_RESPONSE)

        self.assertEqual(result.scenario, "menu")
        self.assertGreater(result.confidence, 0.7)
        self.assertEqual(len(result.foods), 3)

        # Low-confidence item (未知食物X, confidence 0.45) should trigger a warning
        low_conf_foods = [f for f in result.foods if f.confidence < 0.6]
        self.assertEqual(len(low_conf_foods), 1)
        self.assertEqual(low_conf_foods[0].name, "未知食物X")

        self.assertTrue(
            any("未知食物X" in w for w in result.low_confidence_warnings),
            f"Expected warning about 未知食物X, got: {result.low_confidence_warnings}",
        )

        # raw_llm_response preserved
        self.assertEqual(result.raw_llm_response["recommended"], ["烤雞腿便當"])

    def test_parse_food_response(self):
        result = parse_llm_response(AnalysisScenario.FOOD, MOCK_FOOD_RESPONSE)

        self.assertEqual(result.scenario, "food")
        self.assertIsNotNone(result.total_nutrition)
        self.assertAlmostEqual(result.total_nutrition.calories, 500)
        self.assertGreater(result.total_nutrition.protein_g, 20)
        self.assertEqual(result.confidence_tier, "medium")

        # Low-confidence food is flagged
        low_conf = [f for f in result.foods if f.confidence_tier == "low"]
        self.assertEqual(len(low_conf), 1)

    def test_parse_before_after_response(self):
        result = parse_llm_response(AnalysisScenario.BEFORE_AFTER, MOCK_BEFORE_AFTER_RESPONSE)

        self.assertEqual(result.scenario, "before_after")
        self.assertIsNotNone(result.total_nutrition)
        self.assertGreater(result.total_nutrition.calories, 0)

        consumed_foods = [f for f in result.foods if f.estimated_g > 0]
        self.assertEqual(len(consumed_foods), 2)

    def test_confidence_tier_high_at_085(self):
        r = parse_llm_response(AnalysisScenario.FOOD, {
            "foods": [{"name": "a", "estimated_g": 100, "confidence": 0.91}],
            "total_calories": 300,
            "macros": {"protein_g": 10, "carb_g": 40, "fat_g": 8, "fiber_g": 2},
            "confidence": 0.91,
            "confidence_tier": "high",
            "low_confidence_warnings": [],
            "nutrition_advice": "good",
        })
        self.assertEqual(r.confidence_tier, "high")

    def test_confidence_tier_low_below_060(self):
        r = parse_llm_response(AnalysisScenario.FOOD, {
            "foods": [{"name": "a", "estimated_g": 100, "confidence": 0.4}],
            "total_calories": 300,
            "macros": {"protein_g": 10, "carb_g": 40, "fat_g": 8, "fiber_g": 2},
            "confidence": 0.4,
            "confidence_tier": "low",
            "low_confidence_warnings": ["a confidence 40%"],
            "nutrition_advice": "note",
        })
        self.assertEqual(r.confidence_tier, "low")


class TestFormatAnalysisResult(unittest.TestCase):
    def test_format_food_result_shows_nutrition(self):
        result = parse_llm_response(AnalysisScenario.FOOD, MOCK_FOOD_RESPONSE)
        output = format_analysis_result(result, remaining_calories=600)
        self.assertIn("500", output)  # total calories
        self.assertIn("蛋白質", output)
        self.assertIn("烤鯖魚", output)
        self.assertIn("低信心", output)  # warning present

    def test_format_menu_result_shows_recommended_and_avoid(self):
        result = parse_llm_response(AnalysisScenario.MENU, MOCK_MENU_RESPONSE)
        output = format_analysis_result(result)
        self.assertIn("✅ 推薦", output)
        self.assertIn("❌ 建議避免", output)
        self.assertIn("烤雞腿便當", output)
        self.assertIn("麻辣牛肉麵", output)


class TestIntegration(unittest.TestCase):
    """Full round-trip: build prompt → mock parse → format"""

    def test_full_roundtrip_food(self):
        sys_prompt, user_msg = build_llm_prompt(
            AnalysisScenario.FOOD,
            remaining_calories=600,
            protein_gap=30,
            goal_type="loss",
        )
        # Simulate what the agent's LLM would return given the prompt
        self.assertTrue(len(user_msg) > 500)  # substantial prompt
        result = parse_llm_response(AnalysisScenario.FOOD, MOCK_FOOD_RESPONSE)
        output = format_analysis_result(result, remaining_calories=600)
        self.assertIn("熱量", output)
        self.assertIn("剩餘", output)


if __name__ == "__main__":
    unittest.main()