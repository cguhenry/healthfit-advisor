import importlib.util
import os
import sys
import tempfile
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
extract_foods_from_text = MODULE.extract_foods_from_text
process_checkin_response = MODULE.process_checkin_response
DBManager = MODULE.DBManager


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

    def test_extract_foods_from_text_splits_items_and_keeps_grams(self):
        foods = extract_foods_from_text("今天午餐吃了雞胸肉150g、茶葉蛋和無糖豆漿")
        self.assertEqual([food["name"] for food in foods], ["雞胸肉", "茶葉蛋", "無糖豆漿"])
        self.assertEqual(foods[0]["estimated_g"], 150.0)
        self.assertEqual(foods[1]["food_db_source"], "MANUAL")

    def test_process_checkin_response_logs_manual_meal(self):
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        try:
            db = DBManager(Path(tmp_db.name), fast_mode=True)
            db.initialize()
            db.upsert_user_profile(
                {
                    "user_id": "u1",
                    "display_name": "Test",
                    "gender": "M",
                    "age": 30,
                    "height_cm": 175,
                }
            )

            result = process_checkin_response(
                "今天午餐吃了雞胸肉150g、茶葉蛋和無糖豆漿",
                user_id="u1",
                meal_type="lunch",
                db_path=tmp_db.name,
            )

            self.assertEqual(result["status"], "logged")
            self.assertEqual(result["meal_type"], "lunch")
            self.assertEqual(result["logged_rows"], 3)
            row = db.fetch_one(
                "SELECT COUNT(*) AS count FROM food_logs WHERE user_id = ? AND food_db_source = ?",
                ("u1", "MANUAL"),
            )
            self.assertEqual(row["count"], 3)
        finally:
            os.unlink(tmp_db.name)

    def test_process_checkin_response_requests_foods_when_missing(self):
        """When no foods are parseable AND the reply is not a deliberate skip, ask for clarification."""
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        try:
            db = DBManager(Path(tmp_db.name), fast_mode=True)
            db.initialize()
            db.upsert_user_profile(
                {
                    "user_id": "u1",
                    "display_name": "Test",
                    "gender": "M",
                    "age": 30,
                    "height_cm": 175,
                }
            )

            result = process_checkin_response(
                "吃了",
                user_id="u1",
                meal_type="lunch",
                db_path=tmp_db.name,
            )
            self.assertEqual(result["status"], "clarification_needed")
            self.assertEqual(result["field"], "foods")
        finally:
            os.unlink(tmp_db.name)

    def test_checkin_records_skipped_meal(self):
        """B2: '沒吃' replies must write a ___SKIPPED___ placeholder row."""
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        try:
            db = DBManager(Path(tmp_db.name), fast_mode=True)
            db.initialize()
            db.upsert_user_profile(
                {
                    "user_id": "u1",
                    "display_name": "Test",
                    "gender": "M",
                    "age": 30,
                    "height_cm": 175,
                }
            )

            result = process_checkin_response(
                "我沒吃晚餐",
                user_id="u1",
                meal_type="dinner",
                db_path=tmp_db.name,
            )

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["meal_type"], "dinner")
            row = db.fetch_one(
                "SELECT food_name, calories, food_db_source FROM food_logs WHERE user_id = ?",
                ("u1",),
            )
            self.assertEqual(row["food_name"], "___SKIPPED___")
            self.assertEqual(row["calories"], 0)
            self.assertEqual(row["food_db_source"], "SKIP")
        finally:
            os.unlink(tmp_db.name)

    def test_checkin_enriches_calories_from_db(self):
        """B1: process_checkin_response must look up calories from DB; total_calories must be > 0."""
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        try:
            db = DBManager(Path(tmp_db.name), fast_mode=True)
            db.initialize()
            db.upsert_user_profile(
                {
                    "user_id": "u1",
                    "display_name": "Test",
                    "gender": "M",
                    "age": 30,
                    "height_cm": 175,
                }
            )

            # Pre-populate food_db_cache so lookup succeeds
            db.execute(
                """INSERT OR REPLACE INTO food_nutrition_cache
                   (food_id, source, food_name, calories_100g, protein_100g,
                    carb_100g, fat_100g, category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "tw_test_egg",
                    "TW_FDA",
                    "雞蛋",
                    144.0,
                    12.6,
                    0.7,
                    9.5,
                    "蛋類",
                ),
            )

            result = process_checkin_response(
                "雞蛋兩顆",
                user_id="u1",
                meal_type="breakfast",
                db_path=tmp_db.name,
            )

            self.assertEqual(result["status"], "logged")
            self.assertGreater(result["summary"]["total_calories"], 0,
                               "total_calories should be enriched from DB, not 0")
        finally:
            os.unlink(tmp_db.name)


if __name__ == "__main__":
    unittest.main()
