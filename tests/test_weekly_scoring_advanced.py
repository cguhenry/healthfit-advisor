#!/usr/bin/env python3
"""
Tests for weekly_scoring_advanced.py — Phase 6 advanced weekly scoring.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager
from weekly_scoring_advanced import (
    calc_exercise_score,
    calc_gi_quality_score,
    calc_cycle_awareness_score,
    score_weekly_advanced,
    format_advanced_weekly_score,
    AdvancedWeeklyScore,
)


class TestExerciseScore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = DBManager(Path(os.path.join(self.tmp, "test.db")))
        self.db.initialize(schema_path=Path(_SCRIPT_DIR) / "db_schema.sql")
        self.uid = "test_ex_score_001"
        self.db.execute("INSERT OR IGNORE INTO users (user_id, gender) VALUES (?, ?)", (self.uid, "M"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_exercise(self, dates_with_types: list[tuple[str, list[str]]]):
        for d, types in dates_with_types:
            for t in types:
                self.db.execute(
                    "INSERT INTO exercise_logs (user_id, log_date, exercise_type, activity_name, "
                    "duration_min, intensity, calories_burned) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (self.uid, d, t, f"test_{t}", 30, "moderate", 200),
                )

    def test_no_exercise_zero_score(self):
        score, days, cal, types = calc_exercise_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(score, 0)
        self.assertEqual(days, 0)
        self.assertEqual(cal, 0)

    def test_one_day_low_score(self):
        self._seed_exercise([("2026-01-05", ["cardio"])])
        score, days, cal, types = calc_exercise_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(days, 1)
        self.assertLess(score, 60)

    def test_three_days_good_score(self):
        self._seed_exercise([
            ("2026-01-05", ["cardio"]),
            ("2026-01-07", ["strength"]),
            ("2026-01-09", ["cardio"]),
        ])
        score, days, cal, types = calc_exercise_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(days, 3)
        self.assertGreater(score, 70)

    def test_five_days_excellent(self):
        self._seed_exercise([
            ("2026-01-05", ["cardio"]),
            ("2026-01-06", ["strength"]),
            ("2026-01-07", ["hiit"]),
            ("2026-01-08", ["yoga"]),
            ("2026-01-09", ["cardio"]),
        ])
        score, days, cal, types = calc_exercise_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(days, 5)
        self.assertGreaterEqual(score, 85)

    def test_type_diversity_bonus(self):
        self._seed_exercise([
            ("2026-01-05", ["cardio"]),
            ("2026-01-06", ["strength"]),
            ("2026-01-07", ["yoga"]),
        ])
        score, days, cal, types = calc_exercise_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(types, 3)
        self.assertGreaterEqual(score, 80)

    def test_single_type_no_diversity_bonus(self):
        self._seed_exercise([
            ("2026-01-05", ["cardio"]),
            ("2026-01-07", ["cardio"]),
            ("2026-01-09", ["cardio"]),
        ])
        score, days, cal, types = calc_exercise_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(types, 1)


class TestGIQualityScore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = DBManager(Path(os.path.join(self.tmp, "test.db")))
        self.db.initialize(schema_path=Path(_SCRIPT_DIR) / "db_schema.sql")
        self.uid = "test_gi_001"
        self.db.execute("INSERT OR IGNORE INTO users (user_id, gender) VALUES (?, ?)", (self.uid, "M"))
        # Ensure gi_intake_logs table exists
        self.db.execute("""CREATE TABLE IF NOT EXISTS gi_intake_logs (
            log_id TEXT PRIMARY KEY,
            user_id TEXT,
            log_date TEXT,
            food_name TEXT,
            estimated_gi REAL
        )""")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_gi(self, dates_values: list[tuple[str, float]]):
        for d, v in dates_values:
            self.db.execute(
                "INSERT INTO gi_intake_logs (user_id, log_date, food_name, estimated_gi) "
                "VALUES (?, ?, ?, ?)",
                (self.uid, d, f"test_food_{d}", v),
            )

    def test_no_gi_data_zero(self):
        score, avg = calc_gi_quality_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(score, 0)
        self.assertEqual(avg, 0.0)

    def test_low_gi_perfect(self):
        self._seed_gi([("2026-01-05", 50), ("2026-01-06", 48), ("2026-01-07", 52)])
        score, avg = calc_gi_quality_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(score, 100)
        self.assertLess(avg, 55)

    def test_high_gi_poor(self):
        self._seed_gi([("2026-01-05", 75), ("2026-01-06", 72), ("2026-01-07", 78)])
        score, avg = calc_gi_quality_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(score, 50)
        self.assertGreater(avg, 70)

    def test_moderate_gi(self):
        self._seed_gi([("2026-01-05", 60), ("2026-01-06", 62), ("2026-01-07", 58)])
        score, avg = calc_gi_quality_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(score, 85)
        self.assertGreaterEqual(avg, 55)


class TestCycleAwarenessScore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = DBManager(Path(os.path.join(self.tmp, "test.db")))
        self.db.initialize(schema_path=Path(_SCRIPT_DIR) / "db_schema.sql")
        self.uid = "test_cycle_001"
        self.db.execute("INSERT OR IGNORE INTO users (user_id, gender) VALUES (?, ?)", (self.uid, "F"))
        # Ensure menstrual_cycles table exists
        self.db.execute("""CREATE TABLE IF NOT EXISTS menstrual_cycles (
            cycle_id TEXT PRIMARY KEY,
            user_id TEXT,
            period_start_date TEXT,
            cycle_length INTEGER DEFAULT 28
        )""")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_cycle_data(self):
        score, phase, day = calc_cycle_awareness_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(score, 0)
        self.assertEqual(phase, "")

    def test_follicular_phase(self):
        # Period started on 2026-01-01, cycle 28 days
        # Day 8 = follicular
        self.db.execute(
            "INSERT INTO menstrual_cycles (user_id, period_start_date, cycle_length) "
            "VALUES (?, ?, ?)",
            (self.uid, "2026-01-01", 28),
        )
        score, phase, day = calc_cycle_awareness_score(self.db, self.uid, "2026-01-05")
        self.assertEqual(phase, "濾泡期")
        self.assertGreater(score, 0)

    def test_menstrual_phase(self):
        self.db.execute(
            "INSERT INTO menstrual_cycles (user_id, period_start_date, cycle_length) "
            "VALUES (?, ?, ?)",
            (self.uid, "2026-01-01", 28),
        )
        score, phase, day = calc_cycle_awareness_score(self.db, self.uid, "2026-01-01")
        self.assertEqual(phase, "經期")

    def test_luteal_phase(self):
        self.db.execute(
            "INSERT INTO menstrual_cycles (user_id, period_start_date, cycle_length) "
            "VALUES (?, ?, ?)",
            (self.uid, "2026-01-01", 28),
        )
        score, phase, day = calc_cycle_awareness_score(self.db, self.uid, "2026-01-20")
        self.assertEqual(phase, "黃體期")


class TestAdvancedWeeklyScore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = DBManager(Path(os.path.join(self.tmp, "test.db")))
        self.db.initialize(schema_path=Path(_SCRIPT_DIR) / "db_schema.sql")
        self.uid = "test_aws_001"
        self.db.execute("INSERT OR IGNORE INTO users (user_id, gender) VALUES (?, ?)", (self.uid, "M"))

        # Ensure Phase 6 tables exist
        self.db.execute("""CREATE TABLE IF NOT EXISTS gi_intake_logs (
            log_id TEXT PRIMARY KEY, user_id TEXT, log_date TEXT,
            food_name TEXT, estimated_gi REAL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS menstrual_cycles (
            cycle_id TEXT PRIMARY KEY, user_id TEXT,
            period_start_date TEXT, cycle_length INTEGER DEFAULT 28
        )""")

        # Create a basic weight plan
        self.db.execute(
            """INSERT INTO weight_plans (plan_id, user_id, daily_calorie_target,
               protein_target_g, start_weight_kg, goal_weight_kg, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'))""",
            ("plan-001", self.uid, 1800, 120, 70, 65),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_food(self, dates_calories: list[tuple[str, float]]):
        for d, cal in dates_calories:
            self.db.execute(
                "INSERT INTO food_logs (user_id, log_datetime, food_name, meal_type, calories) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.uid, d, f"test_meal_{d}", "午餐", cal),
            )

    def _seed_exercise(self, dates_with_types: list[tuple[str, list[str]]]):
        for d, types in dates_with_types:
            for t in types:
                self.db.execute(
                    "INSERT INTO exercise_logs (user_id, log_date, exercise_type, activity_name, "
                    "duration_min, intensity, calories_burned) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (self.uid, d, t, f"test_{t}", 30, "moderate", 200),
                )

    def _seed_gi(self, dates_values: list[tuple[str, float]]):
        for d, v in dates_values:
            self.db.execute(
                "INSERT INTO gi_intake_logs (user_id, log_date, food_name, estimated_gi) "
                "VALUES (?, ?, ?, ?)",
                (self.uid, d, f"test_food_{d}", v),
            )

    def _seed_cycle(self):
        self.db.execute(
            "INSERT INTO menstrual_cycles (user_id, period_start_date, cycle_length) "
            "VALUES (?, ?, ?)",
            (self.uid, "2026-01-01", 28),
        )

    def test_empty_week_minimal_score(self):
        aws = score_weekly_advanced(self.db, self.uid, "2026-01-05")
        self.assertIsNotNone(aws)
        self.assertLess(aws.final_score, 30)
        self.assertEqual(aws.logged_days, 0)

    def test_full_week_basic(self):
        # Log food for all 7 days
        for i in range(7):
            d = (date(2026, 1, 5) + timedelta(days=i)).isoformat()
            self.db.execute(
                "INSERT INTO food_logs (user_id, log_datetime, food_name, meal_type, calories, protein_g) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.uid, d + " 12:00", f"meal_{i}", "午餐", 600, 30),
            )
        aws = score_weekly_advanced(self.db, self.uid, "2026-01-05")
        self.assertEqual(aws.logged_days, 7)
        self.assertGreater(aws.completeness_score, 80)

    def test_with_exercise_bonus(self):
        # Food + exercise
        for i in range(7):
            d = (date(2026, 1, 5) + timedelta(days=i)).isoformat()
            self.db.execute(
                "INSERT INTO food_logs (user_id, log_datetime, food_name, meal_type, calories) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.uid, d + " 12:00", f"meal_{i}", "午餐", 600),
            )
        self._seed_exercise([
            ("2026-01-05", ["cardio"]),
            ("2026-01-07", ["strength"]),
            ("2026-01-09", ["cardio"]),
        ])
        aws = score_weekly_advanced(self.db, self.uid, "2026-01-05")
        self.assertGreater(aws.exercise_score, 0)
        self.assertEqual(aws.exercise_days, 3)

    def test_with_gi_data(self):
        for i in range(7):
            d = (date(2026, 1, 5) + timedelta(days=i)).isoformat()
            self.db.execute(
                "INSERT INTO food_logs (user_id, log_datetime, food_name, meal_type, calories) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.uid, d + " 12:00", f"meal_{i}", "午餐", 600),
            )
        self._seed_gi([("2026-01-05", 50), ("2026-01-06", 48)])
        aws = score_weekly_advanced(self.db, self.uid, "2026-01-05")
        self.assertGreater(aws.gi_score, 0)

    def test_with_cycle_awareness(self):
        for i in range(7):
            d = (date(2026, 1, 5) + timedelta(days=i)).isoformat()
            self.db.execute(
                "INSERT INTO food_logs (user_id, log_datetime, food_name, meal_type, calories) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.uid, d + " 12:00", f"meal_{i}", "午餐", 600),
            )
        self._seed_cycle()
        aws = score_weekly_advanced(self.db, self.uid, "2026-01-05")
        self.assertGreater(aws.cycle_score, 0)
        self.assertIn(aws.cycle_phase, ("經期", "濾泡期"))

    def test_format_output(self):
        aws = AdvancedWeeklyScore(
            user_id=self.uid, week_start="2026-01-05",
            daily_scores=[85, 90, 78, 82, 95],
            avg_daily_score=86.0, exercise_score=80, exercise_days=3,
            total_exercise_cal=1500, exercise_types_used=2,
            gi_score=85, gi_avg_daily=58.0,
            weight_trend_score=90, weight_change_kg=-0.3,
            completeness_score=85, logged_days=5,
            cycle_score=80, cycle_phase="黃體期", cycle_day=22,
            final_score=84, grade="良好",
            breakdown={"scores": {"daily_component": 30.1, "exercise_component": 16.0,
                                  "weight_component": 13.5, "gi_component": 12.75,
                                  "completeness_component": 8.5, "cycle_component": 4.0}},
        )
        text = format_advanced_weekly_score(aws)
        self.assertIn("84", text)
        self.assertIn("良好", text)
        self.assertIn("黃體期", text)
        self.assertIn("運動表現", text)
        self.assertIn("GI", text)

    def test_exercise_target_integration(self):
        # Log food + exercise ledger
        for i in range(7):
            d = (date(2026, 1, 5) + timedelta(days=i)).isoformat()
            self.db.execute(
                "INSERT INTO food_logs (user_id, log_datetime, food_name, meal_type, calories) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.uid, d + " 12:00", f"meal_{i}", "午餐", 600),
            )
        # Set exercise adjusted target for one day
        self.db.execute(
            "INSERT INTO daily_calorie_ledger (user_id, ledger_date, base_target, exercise_cal, adjusted_target) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.uid, "2026-01-05", 1800, 300, 1950),
        )
        aws = score_weekly_advanced(self.db, self.uid, "2026-01-05")
        # Should not crash when encountering adjusted target
        self.assertEqual(aws.logged_days, 7)


if __name__ == "__main__":
    unittest.main()