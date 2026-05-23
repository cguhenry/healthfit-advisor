#!/usr/bin/env python3
"""Tests for Phase 6 meal_planner.py."""

import json
import sys
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))

from scripts.meal_planner import (
    generate_meal_plan,
    format_meal_plan,
    get_daily_calorie_distribution,
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


if __name__ == "__main__":
    unittest.main()