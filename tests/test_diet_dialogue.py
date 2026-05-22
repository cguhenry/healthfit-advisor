import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SPEC = importlib.util.spec_from_file_location("diet_dialogue", ROOT / "scripts" / "diet_dialogue.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
build_recommendation = MODULE.build_recommendation
DialogueState = MODULE.DialogueState


class TestDialogueFlow(unittest.TestCase):
    def test_complete_inputs_returns_ready(self):
        result = build_recommendation(
            cuisine_input="台式",
            location_input="自助餐",
            meal_input="午餐",
            user_context={"daily_calorie_target": 1800, "remaining_daily_calories": 700},
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["cuisine_type"], "taiwanese")
        self.assertEqual(result["eating_location"], "buffet")
        self.assertEqual(result["meal_type"], "lunch")
        self.assertIn("recommendation", result)
        self.assertIn("formatted", result)

    def test_no_preference_normalises_to_any(self):
        result = build_recommendation(
            cuisine_input="沒有偏好",
            location_input="超商",
            meal_input="晚餐",
            user_context={"remaining_daily_calories": 600},
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["cuisine_type"], "any")

    def test_partial_inputs_returns_clarification(self):
        # only cuisine provided — should ask for location and meal
        result = build_recommendation(cuisine_input="日式")
        self.assertEqual(result["status"], "clarification_needed")
        self.assertIn("prompt", result)
        # state should record what we know
        self.assertEqual(result["state"]["cuisine_type"], "japanese")

    def test_no_preference_location_prompts_for_location(self):
        # no_preference for location should gracefully default to convenience_store
        # and still return ready (not raise) when calories are provided
        result = build_recommendation(
            cuisine_input="台式",
            location_input="沒有特別偏好",
            meal_input="午餐",
            user_context={"remaining_daily_calories": 600},
        )
        # no_preference is resolved to convenience_store
        self.assertEqual(result["status"], "ready")

    def test_unknown_cuisine_prompts_clarification(self):
        result = build_recommendation(
            cuisine_input="外星料理",
            location_input="超商",
            meal_input="午餐",
        )
        self.assertEqual(result["status"], "clarification_needed")
        self.assertEqual(result["field"], "cuisine_type")
        self.assertIn("prompt", result)

    def test_state_continues_across_turns(self):
        # Simulate multi-turn: first only cuisine, then location, then meal
        state = DialogueState()
        state.cuisine_type = "korean"

        result = build_recommendation(
            location_input="餐廳",
            meal_input="晚餐",
            user_context={"remaining_daily_calories": 650},
            state=state,
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["cuisine_type"], "korean")
        self.assertEqual(result["eating_location"], "restaurant")
        self.assertEqual(result["meal_type"], "dinner")

    def test_english_keywords_work(self):
        result = build_recommendation(
            cuisine_input="japanese",
            location_input="convenience_store",
            meal_input="lunch",
            user_context={"remaining_daily_calories": 500},
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["cuisine_type"], "japanese")

    def test_english_no_preference(self):
        result = build_recommendation(
            cuisine_input="no_preference",
            location_input="no_preference",
            meal_input="snack",
            user_context={"remaining_daily_calories": 200},
        )
        self.assertEqual(result["status"], "ready")

    def test_snack_meal_type(self):
        result = build_recommendation(
            cuisine_input="any",
            location_input="超商",
            meal_input="點心",
            user_context={"remaining_daily_calories": 250},
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["meal_type"], "snack")


if __name__ == "__main__":
    unittest.main()