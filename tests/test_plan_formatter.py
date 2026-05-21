import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

MODULE_PATH = SCRIPTS / "plan_formatter.py"
SPEC = importlib.util.spec_from_file_location("plan_formatter", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
format_plan_summary = MODULE.format_plan_summary


class TestPlanFormatter(unittest.TestCase):
    def test_summary_contains_core_targets_and_review_flag(self):
        summary = format_plan_summary(
            {
                "goal_type": "loss",
                "current_weight_kg": 85,
                "goal_weight_kg": 78,
                "target_weeks": 16,
                "bmr": 1600,
                "tdee": 2200,
                "daily_calorie_target": 1700,
                "daily_calorie_delta": -500,
                "macros": {"protein_g": 136, "carb_g": 170, "fat_g": 53},
                "methodology": "Phase 1 approximation",
                "warnings": ["example warning"],
                "requires_professional_review": True,
            }
        )
        self.assertIn("Daily target: 1700 kcal", summary)
        self.assertIn("Professional review: required", summary)


if __name__ == "__main__":
    unittest.main()
