import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "bwp_calculator.py"
SPEC = importlib.util.spec_from_file_location("bwp_calculator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
BWPCalculator = MODULE.BWPCalculator

class TestBWPCalculator(unittest.TestCase):
    def test_loss_plan_adds_safety_warning_when_target_too_aggressive(self):
        calculator = BWPCalculator()
        plan = calculator.build_plan_from_profile(
            age=30,
            height_cm=170,
            current_weight_kg=85,
            goal_weight_kg=75,
            target_weeks=12,
            gender="M",
            activity_level="light",
        )
        self.assertEqual(plan.goal_type, "loss")
        self.assertGreaterEqual(plan.daily_calorie_target, 1500)
        self.assertTrue(any("1%" in warning or "750" in warning for warning in plan.warnings))

    def test_gain_plan_meets_minimum_protein_target(self):
        calculator = BWPCalculator()
        plan = calculator.build_plan_from_profile(
            age=28,
            height_cm=162,
            current_weight_kg=55,
            goal_weight_kg=60,
            target_weeks=20,
            gender="F",
            activity_level="sedentary",
        )
        self.assertEqual(plan.goal_type, "gain")
        self.assertGreaterEqual(plan.macros.protein_g, round(55 * 1.8))
        self.assertGreater(plan.daily_calorie_target, plan.tdee)

    def test_high_risk_flags_require_professional_review(self):
        calculator = BWPCalculator()
        plan = calculator.build_plan_from_profile(
            age=17,
            height_cm=168,
            current_weight_kg=70,
            goal_weight_kg=65,
            target_weeks=12,
            gender="M",
            activity_level="moderate",
            risk_flags=["chronic_disease"],
        )
        self.assertTrue(plan.requires_professional_review)
        self.assertTrue(any("未成年" in warning for warning in plan.warnings))
        self.assertTrue(any("慢性病" in warning for warning in plan.warnings))

if __name__ == "__main__":
    unittest.main()
