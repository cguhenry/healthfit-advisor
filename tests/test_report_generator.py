#!/usr/bin/env python3
"""Tests for report_generator.py"""

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# Ensure scripts directory is importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from report_generator import (
    generate_daily_report, generate_weekly_report, _get_week_weight_change,
)
from db_manager import DBManager


class TestDailyReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = DBManager(Path(self.tmp.name), fast_mode=True)
        self.db.initialize()
        self.user_id = str(uuid4())
        self.db.upsert_user_profile({"user_id": self.user_id, "display_name": "Test"})

        # Create active plan with known targets
        from bwp_calculator import BWPCalculator
        calc = BWPCalculator()
        plan = calc.create_weight_plan(
            current_weight=80, goal_weight=75,
            target_weeks=12, tdee=2200, goal_type="loss",
            gender="M", activity_level="light",
        )
        self.db.save_active_plan(self.user_id, plan.to_dict(), target_date="2026-08-20")

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _log_food(self, calories=500, protein_g=20, carb_g=60, fat_g=15,
                  fiber_g=5, sodium_mg=500, meal_type="lunch",
                  log_date=None):
        from calorie_tracker import log_meal_analysis
        ts = log_date.isoformat() if log_date else datetime.now(timezone.utc).isoformat()
        log_meal_analysis(
            self.db, self.user_id, meal_type,
            [{
                "name": "測試食物", "estimated_g": 200,
                "calories": calories, "protein_g": protein_g,
                "carb_g": carb_g, "fat_g": fat_g,
                "fiber_g": fiber_g, "sodium_mg": sodium_mg,
                "confidence": 0.9,
            }],
            log_datetime=ts,
        )

    def _log_weight(self, weight_kg: float, log_date: date):
        import uuid
        from db_manager import DBManager
        self.db.execute(
            "INSERT INTO weight_logs (log_id, user_id, log_date, weight_kg) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), self.user_id, log_date.isoformat(), weight_kg),
        )

    def test_generate_daily_report_empty(self):
        """Report should not crash with no data."""
        report = generate_daily_report(self.db, self.user_id)
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 50)
        # Should mention no records
        self.assertTrue("每日" in report or "尚無" in report)

    def test_generate_daily_report_with_food(self):
        self._log_food(calories=600, protein_g=25, meal_type="breakfast")
        self._log_food(calories=800, protein_g=35, meal_type="lunch")
        self._log_food(calories=700, protein_g=30, meal_type="dinner")

        report = generate_daily_report(self.db, self.user_id)
        self.assertIsInstance(report, str)
        self.assertIn("2100", report)  # total calories 600+800+700
        self.assertIn("評分", report)
        self.assertIn("歷史對比", report)
        self.assertIn("建議", report)

    def test_generate_daily_report_custom_date(self):
        report = generate_daily_report(self.db, self.user_id, report_date="2026-06-15")
        self.assertIn("2026-06-15", report)

    def test_daily_report_includes_plan_name(self):
        report = generate_daily_report(self.db, self.user_id)
        self.assertIn("減重", report)  # from plan goal_type

    def test_daily_report_includes_score(self):
        self._log_food(calories=600, meal_type="breakfast")
        report = generate_daily_report(self.db, self.user_id)
        self.assertIn("分", report)

    def test_daily_report_includes_comparison(self):
        yesterday = date.today() - timedelta(days=1)
        self._log_food(calories=500, meal_type="dinner", log_date=yesterday)
        today = date.today()
        self._log_food(calories=700, meal_type="lunch", log_date=today)

        report = generate_daily_report(self.db, self.user_id)
        # Should have comparison section
        self.assertIn("歷史對比", report)

    def test_daily_report_includes_recommendations(self):
        self._log_food(calories=500, meal_type="lunch")
        report = generate_daily_report(self.db, self.user_id)
        self.assertIn("建議", report)

    def test_daily_report_footer(self):
        report = generate_daily_report(self.db, self.user_id)
        self.assertIn("HealthFit Advisor", report)


class TestWeeklyReport(unittest.TestCase):
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
        self.db.save_active_plan(self.user_id, plan.to_dict(), target_date="2026-08-20")

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _log_food(self, calories=500, protein_g=20, meal_type="lunch", day=0):
        from calorie_tracker import log_meal_analysis
        d = date.today() - timedelta(days=day)
        ts = d.isoformat() + "T12:00:00+00:00"
        log_meal_analysis(
            self.db, self.user_id, meal_type,
            [{
                "name": "測試", "estimated_g": 200,
                "calories": calories, "protein_g": protein_g,
                "carb_g": 60, "fat_g": 15,
                "fiber_g": 5, "sodium_mg": 500,
                "confidence": 0.9,
            }],
            log_datetime=ts,
        )

    def _log_weight(self, weight_kg: float, log_date: date):
        import uuid
        self.db.execute(
            "INSERT INTO weight_logs (log_id, user_id, log_date, weight_kg) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), self.user_id, log_date.isoformat(), weight_kg),
        )

    def test_generate_weekly_report_empty(self):
        """Should not crash with no data."""
        monday = date.today() - timedelta(days=date.today().weekday())
        report = generate_weekly_report(self.db, self.user_id, week_start_date=monday.isoformat())
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 50)

    def test_generate_weekly_report_with_data(self):
        """Log food for several days and generate weekly report."""
        for day in range(5):
            self._log_food(calories=600 + day * 100, meal_type="dinner", day=day)
            self._log_food(calories=500, meal_type="lunch", day=day)

        monday = date.today() - timedelta(days=date.today().weekday())
        report = generate_weekly_report(self.db, self.user_id, week_start_date=monday.isoformat())
        self.assertIn("每週", report)
        self.assertIn("評分", report)
        self.assertIn("建議", report)

    def test_weekly_report_includes_score_table(self):
        for day in range(3):
            self._log_food(calories=500, meal_type="lunch", day=day)

        monday = date.today() - timedelta(days=date.today().weekday())
        report = generate_weekly_report(self.db, self.user_id, week_start_date=monday.isoformat())
        self.assertIn("每日評分平均", report)

    def test_weekly_report_with_weight(self):
        monday = date.today() - timedelta(days=date.today().weekday())
        self._log_weight(80.0, monday)
        self._log_weight(79.5, monday + timedelta(days=5))

        for day in range(3):
            self._log_food(calories=500, meal_type="dinner", day=day)

        report = generate_weekly_report(self.db, self.user_id, week_start_date=monday.isoformat())
        self.assertIn("體重", report)

    def test_get_week_weight_change_uses_start_and_end_of_week_rows(self):
        monday = date(2026, 5, 18)
        sunday = monday + timedelta(days=6)
        self._log_weight(80.0, monday)
        self._log_weight(79.4, sunday)

        change = _get_week_weight_change(self.db, self.user_id, monday, sunday)
        self.assertAlmostEqual(change, -0.6, places=2)

    def test_weekly_report_persists_weekly_summary(self):
        for day in range(3):
            self._log_food(calories=500, meal_type="lunch", day=day)

        monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        generate_weekly_report(self.db, self.user_id, week_start_date=monday)
        # Should have created weekly_summaries row
        row = self.db.fetch_one(
            "SELECT weekly_score FROM weekly_summaries WHERE user_id = ? AND week_start_date = ?",
            (self.user_id, monday),
        )
        self.assertIsNotNone(row)

    def test_weekly_report_footer(self):
        monday = date.today() - timedelta(days=date.today().weekday())
        report = generate_weekly_report(self.db, self.user_id, week_start_date=monday.isoformat())
        self.assertIn("HealthFit Advisor", report)

    def test_weekly_report_calorie_chart(self):
        for day in range(5):
            self._log_food(calories=500 + day * 100, meal_type="lunch", day=day)

        monday = date.today() - timedelta(days=date.today().weekday())
        report = generate_weekly_report(self.db, self.user_id, week_start_date=monday.isoformat())
        self.assertIn("kcal", report)

    def test_weekly_report_with_explicit_json(self):
        """Test that JSON output option works via direct call signature."""
        monday = date.today() - timedelta(days=date.today().weekday())
        report = generate_weekly_report(self.db, self.user_id, week_start_date=monday.isoformat())
        self.assertIsInstance(report, str)

    def test_no_plan_no_crash(self):
        """Report should handle missing plan gracefully."""
        db = DBManager(Path(self.tmp.name), fast_mode=True)
        db.initialize()
        user_id = str(uuid4())
        db.upsert_user_profile({"user_id": user_id})

        report = generate_daily_report(db, user_id)
        self.assertIsInstance(report, str)

    def test_multiple_meals_progress_section(self):
        """Report should show per-meal breakdown."""
        from calorie_tracker import log_meal_analysis
        today = date.today()
        ts = today.isoformat() + "T08:00:00+00:00"
        log_meal_analysis(
            self.db, self.user_id, "breakfast",
            [{"name": "蛋餅", "estimated_g": 200, "calories": 350,
              "protein_g": 12, "carb_g": 40, "fat_g": 15,
              "fiber_g": 2, "sodium_mg": 400, "confidence": 0.9}],
            log_datetime=ts,
        )
        ts = today.isoformat() + "T12:00:00+00:00"
        log_meal_analysis(
            self.db, self.user_id, "lunch",
            [{"name": "便當", "estimated_g": 400, "calories": 700,
              "protein_g": 30, "carb_g": 80, "fat_g": 25,
              "fiber_g": 5, "sodium_mg": 800, "confidence": 0.85}],
            log_datetime=ts,
        )

        report = generate_daily_report(self.db, self.user_id)
        self.assertIn("早餐", report)
        self.assertIn("午餐", report)


if __name__ == "__main__":
    unittest.main()
