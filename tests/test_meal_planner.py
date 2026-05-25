#!/usr/bin/env python3
"""Tests for Phase 6 meal_planner.py."""

import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))

from scripts.db_manager import DBManager
from scripts.meal_planner import (
    _configure_pdf_fonts,
    _sanitize_pdf_text,
    export_plan_pdf,
    generate_meal_plan,
    generate_optimized_meal_plan,
    format_meal_plan,
    get_daily_calorie_distribution,
    persist_meal_plan,
    _validate_day,
    _MEAL_TEMPLATES,
    _SHOPPING_CATEGORIES,
)


class TestCalorieDistribution(unittest.TestCase):
    """Tests for calorie distribution."""

    def test_balanced_distribution(self):
        dist = get_daily_calorie_distribution("balanced")
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=5)
        self.assertIn("breakfast", dist)
        self.assertIn("lunch", dist)
        self.assertIn("dinner", dist)

    def test_light_distribution(self):
        dist = get_daily_calorie_distribution("light")
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=5)

    def test_high_protein_distribution(self):
        dist = get_daily_calorie_distribution("high_protein")
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=5)

    def test_unknown_preference_falls_back(self):
        dist = get_daily_calorie_distribution("unknown")
        self.assertAlmostEqual(dist["breakfast"], 0.25)


class TestGenerateMealPlan(unittest.TestCase):
    """Tests for meal plan generation."""

    def test_default_plan_generates_7_days(self):
        plan = generate_meal_plan()
        self.assertEqual(len(plan["plan"]), 7)
        self.assertIn("summary", plan)
        self.assertIn("shopping_list", plan)

    def test_plan_has_all_weekdays(self):
        plan = generate_meal_plan()
        days = [d["day"] for d in plan["plan"]]
        self.assertEqual(days, ["週一", "週二", "週三", "週四", "週五", "週六", "週日"])

    def test_custom_calories(self):
        plan = generate_meal_plan(daily_calories=1500)
        self.assertEqual(plan["summary"]["daily_calorie_target"], 1500)

    def test_custom_cuisine(self):
        plan = generate_meal_plan(cuisine="日式")
        self.assertEqual(plan["summary"]["cuisine"], "日式")

        plan2 = generate_meal_plan(cuisine="西式")
        self.assertEqual(plan2["summary"]["cuisine"], "西式")

    def test_meals_have_calories_and_name(self):
        plan = generate_meal_plan()
        for day in plan["plan"]:
            for meal_type in ["breakfast", "lunch", "dinner"]:
                meal = day["meals"].get(meal_type)
                if meal:  # Some days may omit snack
                    self.assertIn("name", meal)
                    self.assertIn("calories", meal)
                    self.assertGreater(meal["calories"], 0)

    def test_high_protein_option(self):
        plan = generate_meal_plan(meal_preference="high_protein")
        self.assertEqual(plan["summary"]["meal_preference"], "high_protein")
        # High protein plans should have adequate protein per meal
        for day in plan["plan"]:
            self.assertGreaterEqual(day["total_protein_g"], 60)

    def test_light_option(self):
        plan = generate_meal_plan(daily_calories=1500, meal_preference="light")
        self.assertEqual(plan["summary"]["meal_preference"], "light")

    def test_shopping_list_not_empty(self):
        plan = generate_meal_plan()
        self.assertTrue(len(plan["shopping_list"]) > 0)

    def test_all_cuisines_have_data(self):
        for cuisine in ["台式", "日式", "西式"]:
            plan = generate_meal_plan(cuisine=cuisine)
            self.assertEqual(len(plan["plan"]), 7, f"{cuisine} should generate 7 days")


class TestShoppingList(unittest.TestCase):
    """Tests for shopping list generation."""

    def test_shopping_list_categories(self):
        plan = generate_meal_plan()
        for cat in plan["shopping_list"]:
            self.assertIn(cat, _SHOPPING_CATEGORIES, f"Unknown category: {cat}")

    def test_protein_category_present(self):
        plan = generate_meal_plan()
        proteins = plan["shopping_list"].get("蛋白質", [])
        self.assertTrue(len(proteins) > 0)

    def test_japanese_cuisine_adds_natto(self):
        plan = generate_meal_plan(cuisine="日式")
        proteins = plan["shopping_list"].get("蛋白質", [])
        self.assertTrue(
            any("納豆" in p or "鮭魚" in p for p in proteins),
            "Japanese cuisine should include 納豆 or 鮭魚"
        )


class TestFormatMealPlan(unittest.TestCase):
    """Tests for plan formatting."""

    def test_format_contains_cuisine(self):
        plan = generate_meal_plan(cuisine="日式")
        text = format_meal_plan(plan)
        self.assertIn("日式", text)

    def test_format_contains_days(self):
        plan = generate_meal_plan()
        text = format_meal_plan(plan)
        for day in ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]:
            self.assertIn(day, text)

    def test_format_contains_shopping_list(self):
        plan = generate_meal_plan()
        text = format_meal_plan(plan)
        self.assertIn("採購清單", text)

    def test_format_contains_calorie_info(self):
        plan = generate_meal_plan()
        text = format_meal_plan(plan)
        self.assertIn("kcal", text)


class _FakePDF:
    def __init__(self):
        self.font_calls = []
        self.cells = []
        self.multi_cells = []
        self.output_path = None

    def set_auto_page_break(self, *args, **kwargs):
        return None

    def add_font(self, family, style="", fname=None, **kwargs):
        self.font_calls.append((family, style, fname, kwargs))

    def add_page(self, *args, **kwargs):
        return None

    def set_fill_color(self, *args, **kwargs):
        return None

    def rect(self, *args, **kwargs):
        return None

    def set_font(self, *args, **kwargs):
        return None

    def set_text_color(self, *args, **kwargs):
        return None

    def set_y(self, *args, **kwargs):
        return None

    def set_xy(self, *args, **kwargs):
        return None

    def set_x(self, *args, **kwargs):
        return None

    def cell(self, *args, **kwargs):
        if len(args) >= 3:
            self.cells.append(args[2])
        elif "text" in kwargs:
            self.cells.append(kwargs["text"])

    def multi_cell(self, *args, **kwargs):
        if len(args) >= 3:
            self.multi_cells.append(args[2])
        elif "text" in kwargs:
            self.multi_cells.append(kwargs["text"])

    def ln(self, *args, **kwargs):
        return None

    def get_y(self):
        return 20

    def output(self, path):
        self.output_path = path


class TestPdfExport(unittest.TestCase):
    def test_sanitize_pdf_text_strips_emoji_and_replaces_bullet(self):
        cleaned = _sanitize_pdf_text("🔥 蛋白質•補充️")
        self.assertNotIn("🔥", cleaned)
        self.assertNotIn("️", cleaned)
        self.assertIn("-", cleaned)

    def test_configure_pdf_fonts_uses_env_font_without_uni_flag(self):
        pdf = _FakePDF()
        with tempfile.NamedTemporaryFile(suffix=".ttf") as font_file:
            with mock.patch.dict("os.environ", {"HEALTHFIT_PDF_FONT": font_file.name}, clear=False):
                family, bold_family = _configure_pdf_fonts(pdf)
        self.assertEqual((family, bold_family), ("CJK", "CJK"))
        self.assertEqual(len(pdf.font_calls), 2)
        self.assertTrue(all("uni" not in kwargs for _, _, _, kwargs in pdf.font_calls))

    def test_export_plan_pdf_reports_missing_font_clearly(self):
        plan = generate_meal_plan()
        stderr = io.StringIO()
        with mock.patch("pathlib.Path.exists", return_value=False):
            with mock.patch.dict("os.environ", {}, clear=True):
                with mock.patch("sys.stderr", stderr):
                    export_plan_pdf(plan, "ignored.pdf")
        self.assertIn("PDF export requires a CJK font", stderr.getvalue())

    def test_export_plan_pdf_sanitizes_rendered_text(self):
        plan = generate_meal_plan()
        fake_pdf = _FakePDF()
        with mock.patch("fpdf.FPDF", return_value=fake_pdf):
            with tempfile.NamedTemporaryFile(suffix=".ttf") as font_file:
                with mock.patch.dict("os.environ", {"HEALTHFIT_PDF_FONT": font_file.name}, clear=False):
                    export_plan_pdf(plan, "meal-plan.pdf")
        rendered = "".join(fake_pdf.cells + fake_pdf.multi_cells)
        self.assertNotIn("🔥", rendered)
        self.assertNotIn("💪", rendered)
        self.assertNotIn("💡", rendered)
        self.assertNotIn("🛒", rendered)
        self.assertNotIn("📦", rendered)


class TestVarietyAndRotation(unittest.TestCase):
    """Tests for meal variety across days."""

    def test_not_all_days_identical(self):
        plan = generate_meal_plan()
        # Collect lunch names
        lunch_names = {day["meals"]["lunch"]["name"] for day in plan["plan"]
                       if "lunch" in day["meals"]}
        self.assertGreater(len(lunch_names), 1,
                           "Should have variety across 7 days")


class TestTemplateIntegrity(unittest.TestCase):
    """Validates the meal template data."""

    def test_all_cuisines_have_all_preferences(self):
        for cuisine, prefs in _MEAL_TEMPLATES.items():
            for pref in ["balanced", "light", "high_protein"]:
                self.assertIn(pref, prefs,
                              f"{cuisine} missing {pref} preference")
                data = prefs[pref]
                self.assertIn("breakfast", data,
                              f"{cuisine}/{pref} missing breakfast")
                self.assertIn("lunch", data,
                              f"{cuisine}/{pref} missing lunch")
                self.assertIn("dinner", data,
                              f"{cuisine}/{pref} missing dinner")

    def test_all_meals_have_tuple_format(self):
        for cuisine, prefs in _MEAL_TEMPLATES.items():
            for pref, meals in prefs.items():
                for meal_type, options in meals.items():
                    for opt in options:
                        self.assertEqual(len(opt), 4,
                                         f"{cuisine}/{pref}/{meal_type}: "
                                         f"expected (name, cal, protein, note), got {opt}")
                        name, cal, protein, note = opt
                        self.assertIsInstance(name, str)
                        self.assertIsInstance(cal, (int, float))
                        self.assertIsInstance(protein, (int, float))


def _mock_optimized_days(days: int = 7) -> dict:
    result_days = []
    meal_names = [
        ("燕麥蛋白杯", "雞胸便當", "鮭魚飯", "希臘優格"),
        ("地瓜炒蛋", "牛肉藜麥碗", "豆腐雞湯", "毛豆"),
        ("全麥蛋餅", "鮪魚沙拉", "味噌鯖魚", "無糖豆漿"),
        ("優格莓果杯", "雞腿糙米餐", "牛腱蔬菜盤", "茶葉蛋"),
        ("豆漿燕麥", "豬里肌便當", "蝦仁義大利麵", "堅果"),
        ("鮭魚飯糰", "雞胸蕎麥麵", "豆腐火鍋", "毛豆"),
        ("香蕉乳清杯", "牛肉烏龍麵", "雞腿沙拉", "優格"),
    ]
    for idx in range(days):
        breakfast, lunch, dinner, snack = meal_names[idx]
        result_days.append({
            "day": idx + 1,
            "meals": {
                "breakfast": {"name": breakfast, "estimated_calories": 360, "protein_g": 28, "carb_g": 38, "fat_g": 10, "prep_note": "前晚可先備料", "gi_tier": "low"},
                "lunch": {"name": lunch, "estimated_calories": 620, "protein_g": 42, "carb_g": 58, "fat_g": 18, "prep_note": "外食優先選烤/滷", "gi_tier": "medium"},
                "dinner": {"name": dinner, "estimated_calories": 640, "protein_g": 40, "carb_g": 55, "fat_g": 20, "prep_note": "晚餐蔬菜至少兩份", "gi_tier": "low"},
                "snack": {"name": snack, "estimated_calories": 120, "protein_g": 12, "carb_g": 10, "fat_g": 4, "prep_note": "下午補蛋白", "gi_tier": "low"},
            },
            "daily_total_calories": 1740,
            "shopping_items": ["雞胸肉", "燕麥", "青菜"],
        })
    return {"days": result_days}


class TestOptimizedMealPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DBManager(Path(self.tmp.name) / "healthfit.db", fast_mode=True)
        self.db.initialize()
        self.user_id = "user_test_001"
        self.db.execute(
            "INSERT INTO users (user_id, display_name) VALUES (?, ?)",
            (self.user_id, "Tester"),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_optimized_plan_calorie_within_tolerance(self):
        plan = generate_optimized_meal_plan(
            db=self.db,
            user_id=self.user_id,
            daily_calories=1800,
            macro_targets={"protein_g": 120, "carb_g": 180, "fat_g": 50},
            llm_estimator=lambda _prompt: _mock_optimized_days(),
        )
        for day in plan["plan"]:
            self.assertLessEqual(abs(day["total_calories"] - 1800) / 1800, 0.05)
        self.assertEqual(plan["summary"]["source"], "optimized_llm")

    def test_optimized_plan_no_duplicate_meals(self):
        plan = generate_optimized_meal_plan(
            db=self.db,
            user_id=self.user_id,
            daily_calories=1800,
            macro_targets={"protein_g": 120, "carb_g": 180, "fat_g": 50},
            llm_estimator=lambda _prompt: _mock_optimized_days(),
        )
        counts = {}
        for day in plan["plan"]:
            for meal in day["meals"].values():
                counts[meal["name"]] = counts.get(meal["name"], 0) + 1
        self.assertTrue(all(count <= 2 for count in counts.values()))

    def test_falls_back_to_template_on_llm_failure(self):
        plan = generate_optimized_meal_plan(
            db=self.db,
            user_id=self.user_id,
            daily_calories=1800,
            macro_targets={"protein_g": 120, "carb_g": 180, "fat_g": 50},
            llm_estimator=lambda _prompt: None,
        )
        self.assertEqual(plan["summary"]["source"], "template_fallback")
        self.assertEqual(len(plan["plan"]), 7)

    def test_validation_catches_low_protein(self):
        violations = _validate_day(
            {
                "day": 1,
                "meals": {
                    "breakfast": {"estimated_calories": 500, "protein_g": 10},
                    "lunch": {"estimated_calories": 600, "protein_g": 20},
                    "dinner": {"estimated_calories": 600, "protein_g": 20},
                },
            },
            1800,
            {"protein_g": 120, "carb_g": 180, "fat_g": 50},
        )
        self.assertTrue(any("蛋白質" in item for item in violations))

    def test_persist_meal_plan_writes_weekly_meal_plans(self):
        plan = generate_optimized_meal_plan(
            db=self.db,
            user_id=self.user_id,
            daily_calories=1800,
            macro_targets={"protein_g": 120, "carb_g": 180, "fat_g": 50},
            llm_estimator=lambda _prompt: _mock_optimized_days(),
            persist=True,
        )
        row = self.db.fetch_one(
            "SELECT source, plan_json FROM weekly_meal_plans WHERE user_id = ?",
            (self.user_id,),
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["source"], "optimized_llm")
        self.assertIn("燕麥蛋白杯", row["plan_json"])


if __name__ == "__main__":
    unittest.main()
