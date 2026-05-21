import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

MODULE_PATH = SCRIPTS / "menu_advisor.py"
SPEC = importlib.util.spec_from_file_location("menu_advisor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
MenuAdvisor = MODULE.MenuAdvisor
recommend_from_payload = MODULE.recommend_from_payload


class TestMenuAdvisor(unittest.TestCase):
    def test_recommends_convenience_store_lunch_near_target(self):
        recommendation = MenuAdvisor().recommend_meal(
            cuisine_type="any",
            eating_location="convenience_store",
            meal_type="lunch",
            remaining_daily_calories=600,
            protein_target_g=146,
            protein_consumed_g=95,
        )
        self.assertEqual(recommendation.primary.eating_location, "convenience_store")
        self.assertLessEqual(abs(recommendation.primary.calories - 600), 120)
        self.assertGreaterEqual(recommendation.primary.protein_g, 30)

    def test_falls_back_when_location_has_no_exact_cuisine_match(self):
        recommendation = MenuAdvisor().recommend_meal(
            cuisine_type="korean",
            eating_location="convenience_store",
            meal_type="dinner",
            remaining_daily_calories=700,
            protein_target_g=120,
            protein_consumed_g=70,
        )
        self.assertEqual(recommendation.primary.cuisine_type, "korean")

    def test_rejects_unknown_location(self):
        with self.assertRaisesRegex(ValueError, "eating_location"):
            MenuAdvisor().recommend_meal(
                cuisine_type="any",
                eating_location="night_market",
                meal_type="lunch",
                remaining_daily_calories=600,
            )

    def test_payload_helper_returns_serializable_dict(self):
        result = recommend_from_payload(
            {
                "cuisine_type": "taiwanese",
                "eating_location": "buffet",
                "meal_type": "lunch",
                "daily_calorie_target": 1800,
                "protein_target_g": 140,
            }
        )
        self.assertIn("primary", result)
        self.assertIn("rationale", result)


if __name__ == "__main__":
    unittest.main()
