#!/usr/bin/env python3
"""Tests for scoring_engine.py"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

# Ensure scripts directory is importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from scoring_engine import (
    DailyNutrition, DailyScore, WeeklyScore, ScoreEvent,
    score_daily, score_weekly,
    get_daily_nutrition, run_daily_scoring,
    persist_daily_score, persist_weekly_score,
    _classify_grade, _ensure_score_events_table,
    CALORIE_OVER_SEVERE_PCT, CALORIE_OVER_MODERATE_PCT, CALORIE_OVER_MILD_PCT,
    CALORIE_UNDER_SEVERE_PCT, CALORIE_UNDER_MODERATE_PCT,
    PROTEIN_LOW_PCT, PROTEIN_MAX_G_PER_KG,
    FIBER_MIN_G, SODIUM_MAX_MG,
)
from db_manager import DBManager


class TestGradeClassification(unittest.TestCase):
    def test_excellent(self):
        for s in [90, 95, 100]:
            self.assertIn("優秀", _classify_grade(s))

    def test_good(self):
        for s in [75, 80, 85]:
            self.assertIn("良好", _classify_grade(s))

    def test_passable(self):
        for s in [60, 65, 70]:
            self.assertIn("及格", _classify_grade(s))

    def test_improvement_needed(self):
        for s in [40, 45, 55, 59]:
            self.assertIn("加強", _classify_grade(s))

    def test_warning(self):
        for s in [0, 10, 25, 39]:
            self.assertIn("警示", _classify_grade(s))


class TestScoreDaily(unittest.TestCase):
    def test_perfect_day_no_data(self):
        """No data logged → missing meals deduction, no bonus."""
        nut = DailyNutrition(total_calories=0, meal_count=0)
        result = score_daily(nut, 2000, 80, body_weight_kg=70)
        self.assertLess(result.final_score, 100)
        # No food logged → missing meals (-15) + calorie_under_severe (-12) = max 73
        self.assertLess(result.final_score, 80)
        self.assertTrue(any(e.event_type == "missing_meals" for e in result.deductions))

    def test_perfect_day_on_target(self):
        """All meals logged and within range → bonus."""
        nut = DailyNutrition(
            total_calories=2000, total_protein_g=80, total_carb_g=250,
            total_fat_g=65, total_fiber_g=30, total_sodium_mg=1500,
            meal_count=3, item_count=9,
        )
        result = score_daily(nut, 2000, 80, body_weight_kg=70)
        self.assertEqual(result.final_score, 100)
        self.assertIsNotNone(result.bonus)

    def test_calorie_severe_over(self):
        nut = DailyNutrition(total_calories=2500, meal_count=3)
        result = score_daily(nut, 2000, 80)
        self.assertTrue(any(e.event_type == "calorie_over_severe" for e in result.deductions))

    def test_calorie_moderate_over(self):
        nut = DailyNutrition(total_calories=2300, meal_count=3)
        result = score_daily(nut, 2000, 80)
        self.assertTrue(any(e.event_type == "calorie_over_moderate" for e in result.deductions))

    def test_calorie_mild_over(self):
        nut = DailyNutrition(total_calories=2140, meal_count=3)
        result = score_daily(nut, 2000, 80)
        self.assertTrue(any(e.event_type == "calorie_over_mild" for e in result.deductions))

    def test_calorie_severe_under(self):
        nut = DailyNutrition(total_calories=1400, meal_count=3)
        result = score_daily(nut, 2000, 80)
        self.assertTrue(any(e.event_type == "calorie_under_severe" for e in result.deductions))

    def test_calorie_moderate_under(self):
        nut = DailyNutrition(total_calories=1600, meal_count=3)
        result = score_daily(nut, 2000, 80)
        self.assertTrue(any(e.event_type == "calorie_under_moderate" for e in result.deductions))

    def test_protein_low(self):
        nut = DailyNutrition(total_calories=2000, total_protein_g=50, meal_count=3)
        result = score_daily(nut, 2000, 80)
        self.assertTrue(any(e.event_type == "protein_low" for e in result.deductions))

    def test_protein_excess(self):
        nut = DailyNutrition(total_calories=2000, total_protein_g=200, meal_count=3)
        result = score_daily(nut, 2000, 80, body_weight_kg=70)
        self.assertTrue(any(e.event_type == "protein_excess" for e in result.deductions))

    def test_fiber_low(self):
        nut = DailyNutrition(total_calories=2000, total_fiber_g=10, meal_count=3)
        result = score_daily(nut, 2000, 80)
        self.assertTrue(any(e.event_type == "fiber_low" for e in result.deductions))

    def test_sodium_high(self):
        nut = DailyNutrition(total_calories=2000, total_sodium_mg=3000, meal_count=3)
        result = score_daily(nut, 2000, 80)
        self.assertTrue(any(e.event_type == "sodium_high" for e in result.deductions))

    def test_missing_one_meal(self):
        nut = DailyNutrition(total_calories=1800, meal_count=2)
        result = score_daily(nut, 2000, 80, expected_meals=3)
        self.assertTrue(any(e.event_type == "missing_meals" for e in result.deductions))

    def test_missing_two_meals(self):
        nut = DailyNutrition(total_calories=600, meal_count=1)
        result = score_daily(nut, 2000, 80, expected_meals=3)
        missing = [e for e in result.deductions if e.event_type == "missing_meals"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].points, -10)

    def test_score_clamped_low(self):
        """Massive deductions shouldn't go below 0."""
        nut = DailyNutrition(
            total_calories=3000, total_protein_g=30, total_fiber_g=5,
            total_sodium_mg=4000, meal_count=1,
        )
        result = score_daily(nut, 2000, 80)
        self.assertGreaterEqual(result.final_score, 0)

    def test_zero_target_no_crash(self):
        """Zero targets shouldn't cause division errors."""
        nut = DailyNutrition(total_calories=0, meal_count=0)
        result = score_daily(nut, 0, 0)
        self.assertGreaterEqual(result.final_score, 0)

    def test_breakdown_structure(self):
        nut = DailyNutrition(
            total_calories=2000, total_protein_g=80,
            total_carb_g=250, total_fat_g=65,
            total_fiber_g=30, total_sodium_mg=1500,
            meal_count=3, item_count=9,
        )
        result = score_daily(nut, 2000, 80)
        self.assertIn("calories", result.breakdown)
        self.assertIn("protein", result.breakdown)
        self.assertIn("deductions", result.breakdown)
        self.assertIsInstance(result.breakdown["deductions"], list)


class TestScoreWeekly(unittest.TestCase):
    def test_perfect_week(self):
        scores = [100] * 7
        cals = [2000] * 7
        ws = score_weekly(scores, cals, 2000, goal_adherence_pct=100,
                          weight_change_kg=-0.5, expected_weekly_change_kg=-0.5,
                          food_category_coverage=1.0, logged_days=7)
        self.assertGreaterEqual(ws.final_score, 85)

    def test_bad_week(self):
        scores = [0, 10, 20, 0, 30, 0, 40]
        cals = [0, 500, 800, 300, 1000, 0, 1200]
        ws = score_weekly(scores, cals, 2000, goal_adherence_pct=0,
                          weight_change_kg=2.0, expected_weekly_change_kg=-0.5,
                          food_category_coverage=0.2, logged_days=3)
        self.assertLess(ws.final_score, 50)

    def test_mixed_week(self):
        scores = [90, 85, 60, 95, 80, 70, 75]
        cals = [1900, 2000, 2500, 1800, 2100, 1500, 2000]
        ws = score_weekly(scores, cals, 2000, goal_adherence_pct=57,
                          weight_change_kg=-0.3, expected_weekly_change_kg=-0.5,
                          food_category_coverage=0.6, logged_days=7)
        self.assertGreaterEqual(ws.final_score, 40)
        self.assertLessEqual(ws.final_score, 90)

    def test_weekly_score_components(self):
        ws = score_weekly([80] * 7, [2000] * 7, 2000, logged_days=7)
        self.assertGreaterEqual(ws.avg_daily_score, 0)
        self.assertGreaterEqual(ws.weight_trend_score, 0)
        self.assertGreaterEqual(ws.diversity_score, 0)
        self.assertGreaterEqual(ws.completeness_score, 0)

    def test_all_zero_no_data(self):
        ws = score_weekly([0] * 7, [0] * 7, 0)
        self.assertGreaterEqual(ws.final_score, 0)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = DBManager(Path(self.tmp.name), fast_mode=True)
        self.db.initialize()
        self.user_id = str(uuid4())
        # Create a minimal user
        self.db.upsert_user_profile({"user_id": self.user_id, "display_name": "Test"})

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_persist_daily_score_creates_score_events(self):
        result = DailyScore(
            user_id=self.user_id, score_date="2026-05-22",
            base_score=100,
            deductions=[
                ScoreEvent("calorie_over_severe", -15, "熱量嚴重超標"),
            ],
            final_score=85,
            grade="良好",
            breakdown={"deductions": [{"type": "calorie_over_severe", "points": -15}]},
        )
        ids = persist_daily_score(self.db, self.user_id, result, "2026-05-22")
        self.assertGreater(len(ids), 0)

        # Verify score_events was created
        events = self.db.connect().execute(
            "SELECT * FROM score_events WHERE user_id = ?", (self.user_id,)
        ).fetchall()
        self.assertGreater(len(events), 0)

    def test_persist_daily_score_updates_summary(self):
        result = DailyScore(
            user_id=self.user_id, score_date="2026-05-22",
            base_score=100, final_score=92, grade="⭐ 優秀",
            breakdown={},
        )
        persist_daily_score(self.db, self.user_id, result, "2026-05-22")

        row = self.db.fetch_one(
            "SELECT daily_score FROM daily_summaries WHERE user_id = ? AND summary_date = ?",
            (self.user_id, "2026-05-22"),
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["daily_score"], 92)

    def test_persist_daily_score_with_bonus(self):
        result = DailyScore(
            user_id=self.user_id, score_date="2026-05-22",
            base_score=100,
            bonus=ScoreEvent("complete_on_target", 5, "記錄完整且達標"),
            final_score=100,
            grade="⭐ 優秀",
            breakdown={"bonus": {"points": 5}},
        )
        ids = persist_daily_score(self.db, self.user_id, result, "2026-05-22")
        self.assertEqual(len(ids), 1)

    def test_persist_weekly_score(self):
        ws = WeeklyScore(
            user_id=self.user_id, week_start="2026-05-18",
            daily_scores=[80, 85, 90, 70, 75, 88, 92],
            avg_daily_score=82.9,
            weight_trend_score=80,
            diversity_score=60,
            completeness_score=85,
            final_score=78,
            grade="良好",
            weekly_calories_avg=1950.0,
            goal_adherence_pct=71.4,
            weight_change_kg=-0.3,
        )
        persist_weekly_score(self.db, self.user_id, ws)

        row = self.db.fetch_one(
            "SELECT * FROM weekly_summaries WHERE user_id = ? AND week_start_date = ?",
            (self.user_id, "2026-05-18"),
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["weekly_score"], 78)

    def test_persist_weekly_score_upsert(self):
        ws = WeeklyScore(
            user_id=self.user_id, week_start="2026-05-18",
            daily_scores=[80] * 7, avg_daily_score=80,
            weight_trend_score=70, diversity_score=60,
            completeness_score=100, final_score=75,
            grade="良好", weekly_calories_avg=2000.0,
            goal_adherence_pct=50.0, weight_change_kg=0.0,
        )
        sid1 = persist_weekly_score(self.db, self.user_id, ws)

        ws.final_score = 82
        sid2 = persist_weekly_score(self.db, self.user_id, ws)

        # Same id (upsert, not duplicate)
        self.assertEqual(sid1, sid2)
        row = self.db.fetch_one(
            "SELECT weekly_score FROM weekly_summaries WHERE week_start_date = '2026-05-18'",
        )
        self.assertEqual(row["weekly_score"], 82)


class TestDailyNutrition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = DBManager(Path(self.tmp.name), fast_mode=True)
        self.db.initialize()
        self.user_id = str(uuid4())
        self.db.upsert_user_profile({"user_id": self.user_id})

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _log_food(self, calories=500, protein_g=20, carb_g=60, fat_g=15,
                  fiber_g=5, sodium_mg=500, meal_type="lunch"):
        from calorie_tracker import log_meal_analysis
        log_meal_analysis(
            self.db, self.user_id, meal_type,
            [{
                "name": "測試食物", "estimated_g": 200,
                "calories": calories, "protein_g": protein_g,
                "carb_g": carb_g, "fat_g": fat_g,
                "fiber_g": fiber_g, "sodium_mg": sodium_mg,
                "confidence": 0.9,
            }],
            log_datetime=datetime.now(timezone.utc).isoformat(),
        )

    def test_get_daily_nutrition_empty(self):
        nut = get_daily_nutrition(self.db, self.user_id, "2026-05-22")
        self.assertEqual(nut.total_calories, 0)
        self.assertEqual(nut.meal_count, 0)
        self.assertEqual(nut.item_count, 0)

    def test_get_daily_nutrition_with_data(self):
        self._log_food(calories=600, protein_g=30, meal_type="lunch")
        self._log_food(calories=400, carb_g=50, meal_type="dinner")

        today = date.today().isoformat()
        nut = get_daily_nutrition(self.db, self.user_id, today)
        self.assertAlmostEqual(nut.total_calories, 1000, delta=1)
        # 30g from lunch + 20g (default) from dinner = 50g
        self.assertAlmostEqual(nut.total_protein_g, 50, delta=1)
        self.assertEqual(nut.meal_count, 2)
        self.assertEqual(nut.item_count, 2)

    def test_get_daily_nutrition_excludes_meal_total(self):
        self._log_food(calories=500, meal_type="lunch")
        self._log_food(calories=400, meal_type="dinner")

        # Insert a ___MEAL_TOTAL___ row manually
        from uuid import uuid4
        self.db.execute(
            "INSERT INTO food_logs (log_id, user_id, meal_type, log_datetime, food_name, calories) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid4()), self.user_id, "lunch", datetime.now(timezone.utc).isoformat(), "___MEAL_TOTAL___", 900),
        )

        today = date.today().isoformat()
        nut = get_daily_nutrition(self.db, self.user_id, today)
        self.assertAlmostEqual(nut.total_calories, 900, delta=1)
        self.assertEqual(nut.item_count, 2)


class TestRunDailyScoring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = DBManager(Path(self.tmp.name), fast_mode=True)
        self.db.initialize()
        self.user_id = str(uuid4())
        self.db.upsert_user_profile({"user_id": self.user_id})
        # Create active plan
        from bwp_calculator import BWPCalculator
        calc = BWPCalculator()
        plan = calc.create_weight_plan(
            current_weight=80, goal_weight=75,
            target_weeks=12, tdee=2200, goal_type="loss",
            gender="M", activity_level="light",
        )
        self.db.save_active_plan(self.user_id, plan.to_dict(),
                                 target_date="2026-08-20")
        self.plan = self.db.get_active_plan(self.user_id)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _log_food(self, calories=500, protein_g=20, meal_type="lunch"):
        from calorie_tracker import log_meal_analysis
        log_meal_analysis(
            self.db, self.user_id, meal_type,
            [{"name": "測試", "estimated_g": 200, "calories": calories,
              "protein_g": protein_g, "carb_g": 60, "fat_g": 15,
              "fiber_g": 5, "sodium_mg": 500, "confidence": 0.9}],
            log_datetime=datetime.now(timezone.utc).isoformat(),
        )

    def test_run_daily_scoring_empty(self):
        result = run_daily_scoring(self.db, self.user_id)
        self.assertIsNotNone(result)
        self.assertEqual(result.user_id, self.user_id)
        self.assertGreaterEqual(result.final_score, 0)

    def test_run_daily_scoring_with_food(self):
        self._log_food(calories=600, protein_g=30, meal_type="breakfast")
        self._log_food(calories=800, protein_g=40, meal_type="lunch")
        self._log_food(calories=600, protein_g=25, meal_type="dinner")

        result = run_daily_scoring(self.db, self.user_id)
        self.assertEqual(result.user_id, self.user_id)
        self.assertIsNotNone(result.score_date)

    def test_run_daily_scoring_persists_score(self):
        self._log_food(calories=600, meal_type="lunch")
        run_daily_scoring(self.db, self.user_id)
        # Score should be persisted
        today = date.today().isoformat()
        row = self.db.fetch_one(
            "SELECT daily_score FROM daily_summaries WHERE user_id = ? AND summary_date = ?",
            (self.user_id, today),
        )
        self.assertIsNotNone(row)

    def test_run_daily_scoring_with_custom_date(self):
        result = run_daily_scoring(self.db, self.user_id, log_date="2026-06-01")
        self.assertEqual(result.score_date, "2026-06-01")


if __name__ == "__main__":
    unittest.main()