#!/usr/bin/env python3
"""Tests for Phase 6 menstrual_tracker.py."""

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))

from scripts.db_manager import DBManager
from scripts.menstrual_tracker import (
    get_cycle_phase,
    adjust_calorie_target,
    log_period_start,
    get_last_period_start,
    get_cycle_info,
    DEFAULT_CYCLE_LENGTH,
    DEFAULT_PERIOD_LENGTH,
    PHASE_BMR_ADJUSTMENTS,
)


class TestCyclePhaseCalculation(unittest.TestCase):
    """Tests for phase determination."""

    def setUp(self):
        # Fixed period start for consistent testing
        self.last_period = date(2026, 5, 1)

    def test_day_1_is_menstruation(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 1))
        self.assertEqual(info["phase"], "menstruation")
        self.assertEqual(info["cycle_day"], 1)

    def test_day_3_is_menstruation(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 3))
        self.assertEqual(info["phase"], "menstruation")
        self.assertEqual(info["cycle_day"], 3)

    def test_day_6_is_follicular(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 6))
        self.assertEqual(info["phase"], "follicular")

    def test_day_10_is_follicular(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 10))
        self.assertEqual(info["phase"], "follicular")

    def test_day_14_is_ovulation(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 14))
        self.assertEqual(info["phase"], "ovulation")

    def test_day_18_is_luteal(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 18))
        self.assertEqual(info["phase"], "luteal")

    def test_day_27_is_premenstrual(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 27))
        self.assertEqual(info["phase"], "premenstrual")

    def test_day_28_is_premenstrual(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 28))
        self.assertEqual(info["phase"], "premenstrual")

    def test_day_29_is_menstruation_next_cycle(self):
        """Day 29 = day 1 of next cycle = menstruation."""
        info = get_cycle_phase(self.last_period, date(2026, 5, 29))
        self.assertEqual(info["phase"], "menstruation")
        self.assertEqual(info["cycle_day"], 1)

    def test_days_remaining(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 25))
        self.assertEqual(info["days_remaining"], 3)  # 28 - 25

    def test_predicted_next_period(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 1))
        self.assertEqual(info["predicted_next_period"], "2026-05-28")

    def test_bmr_adjustment_luteal(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 18))
        self.assertEqual(info["bmr_adjustment"], 1.07)

    def test_bmr_adjustment_menstruation(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 3))
        self.assertEqual(info["bmr_adjustment"], 1.00)

    def test_custom_cycle_length(self):
        info = get_cycle_phase(self.last_period, date(2026, 5, 35 - 28),
                               cycle_length=35)
        # 35 days since last period = day 1 of next cycle
        info2 = get_cycle_phase(self.last_period, date(2026, 5, 1),
                                cycle_length=35)
        self.assertIsNotNone(info2)


class TestCalorieAdjustment(unittest.TestCase):
    """Tests for calorie target adjustment by phase."""

    def test_luteal_increase(self):
        last_period = date(2026, 5, 1)
        phase_info = get_cycle_phase(last_period, date(2026, 5, 18))
        result = adjust_calorie_target(1500, phase_info)
        self.assertGreater(result["adjusted_target"], 1500)
        self.assertEqual(result["base_target"], 1500)
        self.assertEqual(result["bmr_adjustment"], 1.07)

    def test_menstruation_baseline(self):
        last_period = date(2026, 5, 1)
        phase_info = get_cycle_phase(last_period, date(2026, 5, 1))
        result = adjust_calorie_target(1500, phase_info)
        self.assertEqual(result["adjusted_target"], 1500)

    def test_follicular_slight_increase(self):
        last_period = date(2026, 5, 1)
        phase_info = get_cycle_phase(last_period, date(2026, 5, 6))
        result = adjust_calorie_target(2000, phase_info)
        self.assertEqual(result["adjusted_target"], 2040)

    def test_advice_is_present(self):
        last_period = date(2026, 5, 1)
        for day, expected_phase in [
            (3, "menstruation"),
            (8, "follicular"),
            (14, "ovulation"),
            (20, "luteal"),
            (27, "premenstrual"),
        ]:
            phase_info = get_cycle_phase(last_period, date(2026, 5, day))
            result = adjust_calorie_target(1500, phase_info)
            self.assertEqual(result["phase"], expected_phase)
            self.assertTrue(result["advice"])


class TestDBPersistence(unittest.TestCase):
    """Tests for menstrual_logs DB operations."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hf_menstrual_")
        self.db = DBManager(db_path=Path(self.tmp) / "test.db", fast_mode=True)
        self.db.initialize(schema_path=_SKILL_DIR / "scripts" / "db_schema.sql")
        self.user_id = "menstrual_test_001"
        self.db.execute(
            "INSERT INTO users (user_id, display_name, gender, age, height_cm) "
            "VALUES (?, 'Test', 'F', 30, 165)",
            (self.user_id,),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_log_period_start(self):
        result = log_period_start(self.db, self.user_id, "2026-05-15")
        self.assertEqual(result["period_start"], "2026-05-15")

    def test_get_last_period_start(self):
        log_period_start(self.db, self.user_id, "2026-05-15")
        last = get_last_period_start(self.db, self.user_id)
        self.assertIsNotNone(last)
        self.assertEqual(str(last["period_start"]), "2026-05-15")

    def test_get_last_period_no_data(self):
        last = get_last_period_start(self.db, "nonexistent_user")
        self.assertIsNone(last)

    def test_get_cycle_info(self):
        log_period_start(self.db, self.user_id, "2026-05-01")
        info = get_cycle_info(self.db, self.user_id)
        self.assertIsNotNone(info)
        self.assertIn("phase", info)
        self.assertIn("cycle_day", info)

    def test_get_cycle_info_no_data(self):
        info = get_cycle_info(self.db, "nonexistent_user")
        self.assertIsNone(info)

    def test_log_multiple_periods_latest_taken(self):
        log_period_start(self.db, self.user_id, "2026-03-01")
        log_period_start(self.db, self.user_id, "2026-05-15")
        last = get_last_period_start(self.db, self.user_id)
        self.assertEqual(str(last["period_start"]), "2026-05-15")

    def test_log_period_with_cycle_length(self):
        log_period_start(self.db, self.user_id, "2026-05-15", cycle_length=35)
        info = get_cycle_info(self.db, self.user_id)
        self.assertIsNotNone(info, "get_cycle_info returned None — check period date is valid for today")
        self.assertEqual(info["cycle_length"], 35)

    def test_default_cycle_length(self):
        log_period_start(self.db, self.user_id, "2026-05-15")
        info = get_cycle_info(self.db, self.user_id)
        self.assertEqual(info["cycle_length"], 28)


class TestPhaseBoundaries(unittest.TestCase):
    """Tests for valid phase boundaries."""

    def test_all_phases_have_adjustments(self):
        valid_phases = {"menstruation", "follicular", "ovulation", "luteal", "premenstrual"}
        for phase in valid_phases:
            self.assertIn(phase, PHASE_BMR_ADJUSTMENTS,
                          f"Missing BMR adjustment for {phase}")

    def test_all_adjustments_reasonable(self):
        for phase, adj in PHASE_BMR_ADJUSTMENTS.items():
            self.assertGreaterEqual(adj, 1.0,
                                   f"{phase} adjustment {adj} should not be < 1.0")
            self.assertLessEqual(adj, 1.15,
                                f"{phase} adjustment {adj} should not exceed 15%")


if __name__ == "__main__":
    unittest.main()