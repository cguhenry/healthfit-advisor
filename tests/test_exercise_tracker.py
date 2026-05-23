#!/usr/bin/env python3
"""Tests for Phase 6 exercise_tracker.py."""

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))

from scripts.db_manager import DBManager
from scripts.exercise_tracker import (
    normalize_activity,
    normalize_intensity,
    get_met,
    estimate_calories_burned,
    classify_exercise_type,
    log_exercise,
    get_daily_exercise,
    get_daily_exercise_total,
    adjust_daily_calorie_target,
    get_adjusted_target,
    format_exercise_summary,
    format_ledger_summary,
)


class TestNormalize(unittest.TestCase):
    """Tests for activity/intensity normalization."""

    def test_normalize_activity_unchanged(self):
        self.assertEqual(normalize_activity("慢跑"), "慢跑")

    def test_normalize_activity_strips_whitespace(self):
        self.assertEqual(normalize_activity("  慢跑 "), "慢跑")

    def test_normalize_intensity_chinese_light(self):
        self.assertEqual(normalize_intensity("輕度"), "light")

    def test_normalize_intensity_chinese_moderate(self):
        self.assertEqual(normalize_intensity("中等"), "moderate")

    def test_normalize_intensity_chinese_vigorous(self):
        self.assertEqual(normalize_intensity("高強度"), "vigorous")

    def test_normalize_intensity_english(self):
        self.assertEqual(normalize_intensity("moderate"), "moderate")

    def test_normalize_intensity_short_chinese(self):
        self.assertEqual(normalize_intensity("輕"), "light")
        self.assertEqual(normalize_intensity("中"), "moderate")
        self.assertEqual(normalize_intensity("強"), "vigorous")


class TestMETLookup(unittest.TestCase):
    """Tests for MET value retrieval."""

    def test_running_moderate_met(self):
        met = get_met("慢跑", "moderate")
        self.assertEqual(met, 8.0)

    def test_running_vigorous_met(self):
        met = get_met("跑步", "vigorous")
        self.assertEqual(met, 12.5)

    def test_walking_light_met(self):
        met = get_met("走路", "light")
        self.assertEqual(met, 2.5)

    def test_swimming_moderate_met(self):
        met = get_met("游泳", "moderate")
        self.assertEqual(met, 7.0)

    def test_yoga_light_met(self):
        met = get_met("瑜珈", "light")
        self.assertEqual(met, 2.5)

    def test_strength_training_vigorous_met(self):
        met = get_met("重訓", "vigorous")
        self.assertEqual(met, 6.0)

    def test_squat_moderate_met(self):
        met = get_met("深蹲", "moderate")
        self.assertEqual(met, 5.5)

    def test_hiit_vigorous_met(self):
        met = get_met("hiit", "vigorous")
        self.assertEqual(met, 12.0)

    def test_badminton_moderate_met(self):
        met = get_met("羽球", "moderate")
        self.assertEqual(met, 5.5)

    def test_unknown_activity_returns_none(self):
        met = get_met("未知活動", "moderate")
        self.assertIsNone(met)


class TestCalorieEstimation(unittest.TestCase):
    """Tests for calorie burn estimation."""

    def test_basic_calorie_estimation(self):
        # MET=8, weight=70kg, duration=30min
        # calories = 8 * 70 * (30/60) = 280
        cal = estimate_calories_burned(70.0, 8.0, 30)
        self.assertAlmostEqual(cal, 280.0, places=1)

    def test_zero_duration(self):
        cal = estimate_calories_burned(70.0, 8.0, 0)
        self.assertEqual(cal, 0.0)

    def test_heavy_person_more_calories(self):
        cal_light = estimate_calories_burned(50.0, 8.0, 30)
        cal_heavy = estimate_calories_burned(90.0, 8.0, 30)
        self.assertGreater(cal_heavy, cal_light)


class TestExerciseTypeClassification(unittest.TestCase):
    """Tests for exercise type classification."""

    def test_running_is_cardio(self):
        self.assertEqual(classify_exercise_type("慢跑"), "cardio")

    def test_cycling_is_cardio(self):
        self.assertEqual(classify_exercise_type("騎腳踏車"), "cardio")

    def test_swimming_is_cardio(self):
        self.assertEqual(classify_exercise_type("游泳"), "cardio")

    def test_strength_training_is_strength(self):
        self.assertEqual(classify_exercise_type("重訓"), "strength")

    def test_squat_is_strength(self):
        self.assertEqual(classify_exercise_type("深蹲"), "strength")

    def test_hiit_is_hiit(self):
        self.assertEqual(classify_exercise_type("hiit"), "hiit")

    def test_yoga_is_yoga(self):
        self.assertEqual(classify_exercise_type("瑜珈"), "yoga")

    def test_pilates_is_yoga(self):
        self.assertEqual(classify_exercise_type("皮拉提斯"), "yoga")

    def test_basketball_is_cardio(self):
        self.assertEqual(classify_exercise_type("籃球"), "cardio")

    def test_unknown_is_other(self):
        self.assertEqual(classify_exercise_type("冥想"), "other")


class TestExerciseDB(unittest.TestCase):
    """Tests for exercise database persistence."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="healthfit_test_")
        self.db_path_obj = Path(self.tmp) / "test.db"
        self.db = DBManager(db_path=self.db_path_obj, fast_mode=True)
        self.db.initialize(schema_path=_SKILL_DIR / "scripts" / "db_schema.sql")
        self._setup_user_and_plan()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _schema_path(self):
        return str(_SKILL_DIR / "scripts" / "db_schema.sql")

    def _setup_user_and_plan(self):
        self.user_id = "test_user_001"
        self.db.execute(
            """INSERT INTO users (user_id, display_name, gender, age, height_cm)
               VALUES (?, 'Test', 'M', 30, 175)""",
            (self.user_id,),
        )
        self.db.execute(
            """INSERT INTO weight_plans (user_id, goal_type, daily_calorie_target,
               is_active, bmr, tdee)
               VALUES (?, 'loss', 1800, 1, 1700, 2100)""",
            (self.user_id,),
        )

    def test_log_exercise_single(self):
        entry = log_exercise(
            db=self.db, user_id=self.user_id, log_date="2026-05-23",
            exercise_type="cardio", activity_name="慢跑", duration_min=30,
            intensity="moderate", weight_kg=70.0,
        )
        self.assertEqual(entry.activity_name, "慢跑")
        self.assertEqual(entry.duration_min, 30)
        self.assertEqual(entry.intensity, "moderate")
        self.assertAlmostEqual(entry.calories_burned, 280.0, places=1)

    def test_log_exercise_strength(self):
        entry = log_exercise(
            db=self.db, user_id=self.user_id, log_date="2026-05-23",
            exercise_type="strength", activity_name="深蹲", duration_min=45,
            intensity="vigorous", weight_kg=70.0,
        )
        # MET=8.0, weight=70, duration=45
        # calories = 8 * 70 * 45/60 = 420
        self.assertAlmostEqual(entry.calories_burned, 420.0, places=1)

    def test_log_exercise_unknown_activity_raises(self):
        with self.assertRaises(ValueError):
            log_exercise(
                db=self.db, user_id=self.user_id, log_date="2026-05-23",
                exercise_type="other", activity_name="未知運動", duration_min=30,
                intensity="moderate", weight_kg=70.0,
            )

    def test_log_duplicate_accumulates(self):
        # First log
        log_exercise(
            db=self.db, user_id=self.user_id, log_date="2026-05-23",
            exercise_type="cardio", activity_name="慢跑", duration_min=30,
            intensity="moderate", weight_kg=70.0,
        )
        # Second log (same activity) — should accumulate
        log_exercise(
            db=self.db, user_id=self.user_id, log_date="2026-05-23",
            exercise_type="cardio", activity_name="慢跑", duration_min=20,
            intensity="moderate", weight_kg=70.0,
        )

        total = get_daily_exercise_total(self.db, self.user_id, "2026-05-23")
        expected = estimate_calories_burned(70.0, 8.0, 50)  # 30+20 min
        self.assertAlmostEqual(total, expected, places=1)

    def test_get_daily_exercise_empty(self):
        exercises = get_daily_exercise(self.db, self.user_id, "2026-05-23")
        self.assertEqual(exercises, [])

    def test_get_daily_exercise_with_data(self):
        log_exercise(
            db=self.db, user_id=self.user_id, log_date="2026-05-23",
            exercise_type="cardio", activity_name="慢跑", duration_min=30,
            intensity="moderate", weight_kg=70.0,
        )
        exercises = get_daily_exercise(self.db, self.user_id, "2026-05-23")
        self.assertEqual(len(exercises), 1)
        self.assertEqual(exercises[0]["activity_name"], "慢跑")

    def test_get_daily_total_zero_without_exercise(self):
        total = get_daily_exercise_total(self.db, self.user_id, "2026-05-23")
        self.assertEqual(total, 0.0)

    def test_get_daily_total_with_exercise(self):
        log_exercise(
            db=self.db, user_id=self.user_id,
            log_date="2026-05-23", exercise_type="cardio",
            activity_name="慢跑", duration_min=30,
            intensity="moderate", weight_kg=70.0,
        )
        total = get_daily_exercise_total(self.db, self.user_id, "2026-05-23")
        self.assertAlmostEqual(total, 280.0, places=1)


class TestCalorieAdjustment(unittest.TestCase):
    """Tests for dynamic calorie quota adjustment."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="healthfit_test_")
        self.db = DBManager(db_path=Path(self.tmp) / "test.db", fast_mode=True)
        self.db.initialize(schema_path=_SKILL_DIR / "scripts" / "db_schema.sql")
        self.user_id = "test_user_002"
        self.db.execute(
            "INSERT INTO users (user_id, display_name, gender, age, height_cm) "
            "VALUES (?, 'Test', 'F', 28, 165)",
            (self.user_id,),
        )
        self.db.execute(
            """INSERT INTO weight_plans (user_id, goal_type, daily_calorie_target,
               is_active, bmr, tdee)
               VALUES (?, 'loss', 1500, 1, 1400, 1800)""",
            (self.user_id,),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_adjust_loss_mode(self):
        # Loss mode: eat back 50%
        ledger = adjust_daily_calorie_target(
            self.db, self.user_id, "2026-05-23", 1500, exercise_cal=300
        )
        self.assertEqual(ledger["base_target"], 1500)
        self.assertEqual(ledger["exercise_cal"], 300)
        self.assertEqual(ledger["added_cal"], 150)  # 300 * 0.5
        self.assertEqual(ledger["adjusted_target"], 1650)
        self.assertEqual(ledger["eat_back_ratio"], 0.5)

    def test_adjust_gain_mode(self):
        # Switch plan to gain
        self.db.execute(
            "UPDATE weight_plans SET goal_type = 'gain' WHERE user_id = ?",
            (self.user_id,),
        )
        ledger = adjust_daily_calorie_target(
            self.db, self.user_id, "2026-05-23", 2500, exercise_cal=400
        )
        self.assertEqual(ledger["eat_back_ratio"], 1.0)
        self.assertEqual(ledger["added_cal"], 400)
        self.assertEqual(ledger["adjusted_target"], 2900)

    def test_adjust_maintain_mode(self):
        self.db.execute(
            "UPDATE weight_plans SET goal_type = 'maintain' WHERE user_id = ?",
            (self.user_id,),
        )
        ledger = adjust_daily_calorie_target(
            self.db, self.user_id, "2026-05-23", 2000, exercise_cal=200
        )
        self.assertEqual(ledger["eat_back_ratio"], 0.75)
        self.assertEqual(ledger["added_cal"], 150)
        self.assertEqual(ledger["adjusted_target"], 2150)

    def test_adjust_no_exercise(self):
        ledger = adjust_daily_calorie_target(
            self.db, self.user_id, "2026-05-23", 1500, exercise_cal=0
        )
        self.assertEqual(ledger["added_cal"], 0)
        self.assertEqual(ledger["adjusted_target"], 1500)

    def test_get_adjusted_target_exists(self):
        adjust_daily_calorie_target(
            self.db, self.user_id, "2026-05-23", 1500, exercise_cal=300
        )
        target = get_adjusted_target(self.db, self.user_id, "2026-05-23")
        self.assertEqual(target, 1650)

    def test_get_adjusted_target_missing(self):
        target = get_adjusted_target(self.db, self.user_id, "2026-05-23")
        self.assertIsNone(target)


class TestFormatHelpers(unittest.TestCase):
    """Tests for formatting functions."""

    def test_format_empty_exercise_summary(self):
        result = format_exercise_summary([], 0.0)
        self.assertIn("尚無運動記錄", result)

    def test_format_exercise_summary_has_data(self):
        exercises = [{
            "exercise_type": "cardio",
            "activity_name": "慢跑",
            "intensity": "moderate",
            "duration_min": 30,
            "calories_burned": 280.0,
            "note": None,
        }]
        result = format_exercise_summary(exercises, 280.0)
        self.assertIn("慢跑", result)
        self.assertIn("280", result)

    def test_format_ledger_summary(self):
        ledger = {
            "base_target": 1500,
            "exercise_cal": 300,
            "added_cal": 150,
            "goal_type": "loss",
            "eat_back_ratio": 0.5,
            "adjusted_target": 1650,
        }
        result = format_ledger_summary(ledger)
        self.assertIn("1500 kcal", result)
        self.assertIn("300 kcal", result)
        self.assertIn("+150", result)
        self.assertIn("1650", result)


if __name__ == "__main__":
    unittest.main()