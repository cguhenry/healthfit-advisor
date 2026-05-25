#!/usr/bin/env python3
"""Tests for Phase 6 health_alerts.py."""

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
from scripts.health_alerts import (
    check_low_calorie_streak,
    check_rapid_weight_loss,
    check_protein_deficiency,
    check_missing_logs,
    check_plateau,
    check_binge_day,
    check_excessive_exercise,
    run_all_checks,
    get_active_alerts,
    acknowledge_alert,
    format_alerts,
    HealthAlert,
    SAFE_CALORIE_FLOOR,
)


class TestHealthAlertsBase(unittest.TestCase):
    """Base class with DB setup."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="healthfit_alert_")
        self.db = DBManager(db_path=Path(self.tmp) / "test.db", fast_mode=True)
        self.db.initialize(schema_path=_SKILL_DIR / "scripts" / "db_schema.sql")
        self.user_id = "alert_test_001"
        self._setup_user()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _setup_user(self):
        self.db.execute(
            "INSERT INTO users (user_id, display_name, gender, age, height_cm) "
            "VALUES (?, 'Tester', 'M', 30, 175)",
            (self.user_id,),
        )
        self.db.execute(
            """INSERT INTO weight_plans (
               user_id, goal_type, daily_calorie_target, is_active,
               start_weight_kg, goal_weight_kg, target_weeks, bmr, tdee,
               activity_level, protein_target_g, carb_target_g, fat_target_g, target_date
            ) VALUES (?, 'loss', 1800, 1, 80.0, 72.0, 8, 1750, 2200, 'light', 140, 180, 55, '2026-07-15')""",
            (self.user_id,),
        )
        self.db.execute(
            """INSERT INTO weight_logs (user_id, log_date, weight_kg)
               VALUES (?, ?, 80.0)""",
            (self.user_id, str(date.today() - timedelta(days=10))),
        )

    def _add_summary(self, dt: str, calories: float, protein: float = 0.0,
                     target: int = 1800):
        self.db.execute(
            """INSERT OR REPLACE INTO daily_summaries
               (user_id, summary_date, total_calories, total_protein_g, calorie_target)
               VALUES (?, ?, ?, ?, ?)""",
            (self.user_id, dt, calories, protein, target),
        )

    def _add_weight(self, dt: str, weight: float):
        self.db.execute(
            "INSERT INTO weight_logs (user_id, log_date, weight_kg) VALUES (?, ?, ?)",
            (self.user_id, dt, weight),
        )

    def _add_exercise(self, dt: str, calories: float):
        self.db.execute(
            """INSERT INTO exercise_logs (user_id, log_date, exercise_type,
               activity_name, duration_min, intensity, calories_burned)
               VALUES (?, ?, 'cardio', 'run', 60, 'vigorous', ?)""",
            (self.user_id, dt, calories),
        )


class TestLowCalorieStreak(TestHealthAlertsBase):
    """Tests for low calorie streak detection."""

    def test_no_data_no_alert(self):
        alert = check_low_calorie_streak(self.db, self.user_id, "2026-05-23")
        self.assertIsNone(alert)

    def test_three_days_low_calorie(self):
        today = "2026-05-23"
        for i in range(3, 0, -1):
            dt = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
            self._add_summary(dt, 800)  # Below 1500

        alert = check_low_calorie_streak(self.db, self.user_id, today)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, "low_calorie_streak")
        self.assertEqual(alert.severity, "warning")

    def test_not_enough_days(self):
        today = "2026-05-23"
        self._add_summary(today, 800)
        alert = check_low_calorie_streak(self.db, self.user_id, today)
        self.assertIsNone(alert)

    def test_normal_calories_no_alert(self):
        today = "2026-05-23"
        for i in range(3, 0, -1):
            dt = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
            self._add_summary(dt, 1700)  # Within safe range

        alert = check_low_calorie_streak(self.db, self.user_id, today)
        self.assertIsNone(alert)

    def test_zero_calorie_skipped(self):
        """Zero-calorie days (no data) should not count as low."""
        today = "2026-05-23"
        for i in range(3, 0, -1):
            dt = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
            self._add_summary(dt, 0)

        alert = check_low_calorie_streak(self.db, self.user_id, today)
        self.assertIsNone(alert)


class TestRapidWeightLoss(TestHealthAlertsBase):
    """Tests for rapid weight loss detection."""

    def test_no_weight_data_no_alert(self):
        alert = check_rapid_weight_loss(self.db, self.user_id, "2026-05-23")
        self.assertIsNone(alert)

    def test_rapid_loss_detected(self):
        today = "2026-05-23"
        week_ago = "2026-05-16"
        self._add_weight(today, 78.0)
        self._add_weight(week_ago, 80.0)  # -2kg in a week

        alert = check_rapid_weight_loss(self.db, self.user_id, today)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, "rapid_weight_loss")
        self.assertEqual(alert.severity, "critical")

    def test_normal_loss_no_alert(self):
        today = "2026-05-23"
        week_ago = "2026-05-16"
        self._add_weight(today, 79.2)
        self._add_weight(week_ago, 80.0)  # -0.8kg in a week

        alert = check_rapid_weight_loss(self.db, self.user_id, today)
        self.assertIsNone(alert)

    def test_weight_gain_no_alert(self):
        today = "2026-05-23"
        week_ago = "2026-05-16"
        self._add_weight(today, 81.0)
        self._add_weight(week_ago, 80.0)

        alert = check_rapid_weight_loss(self.db, self.user_id, today)
        self.assertIsNone(alert)


class TestProteinDeficiency(TestHealthAlertsBase):
    """Tests for protein deficiency detection."""

    def test_no_data_no_alert(self):
        alert = check_protein_deficiency(self.db, self.user_id, "2026-05-23")
        self.assertIsNone(alert)

    def test_protein_deficiency_detected(self):
        today = "2026-05-23"
        # Need current weight for floor calc: 80kg × 0.8 = 64g
        self._add_weight(today, 80.0)

        for i in range(3, 0, -1):
            dt = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
            self._add_summary(dt, 1500, 30)  # Only 30g protein

        alert = check_protein_deficiency(self.db, self.user_id, today)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, "protein_deficiency")

    def test_adequate_protein_no_alert(self):
        today = "2026-05-23"
        self._add_weight(today, 80.0)

        for i in range(3, 0, -1):
            dt = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
            self._add_summary(dt, 1500, 70)  # Above 64g

        alert = check_protein_deficiency(self.db, self.user_id, today)
        self.assertIsNone(alert)


class TestMissingLogs(TestHealthAlertsBase):
    """Tests for missing log detection."""

    def test_recent_logs_no_alert(self):
        today = "2026-05-23"
        self._add_summary(today, 1800, 80)
        alert = check_missing_logs(self.db, self.user_id, today)
        self.assertIsNone(alert)

    def test_long_gap_detected(self):
        today = "2026-05-23"
        old_date = "2026-05-15"  # 8 days ago
        self._add_summary(old_date, 1800, 80)

        alert = check_missing_logs(self.db, self.user_id, today)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, "missing_logs")


class TestPlateau(TestHealthAlertsBase):
    """Tests for weight plateau detection."""

    def test_no_data_no_alert(self):
        alert = check_plateau(self.db, self.user_id, "2026-05-23")
        self.assertIsNone(alert)

    def test_plateau_detected(self):
        today = "2026-05-23"
        three_weeks = "2026-05-02"
        self._add_weight(three_weeks, 80.0)
        self._add_weight(today, 80.1)  # < 0.3kg change

        alert = check_plateau(self.db, self.user_id, today)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, "plateau")

    def test_progress_no_alert(self):
        today = "2026-05-23"
        three_weeks = "2026-05-02"
        self._add_weight(three_weeks, 80.0)
        self._add_weight(today, 78.5)  # > 0.3kg change

        alert = check_plateau(self.db, self.user_id, today)
        self.assertIsNone(alert)

    def test_gain_plan_no_plateau_check(self):
        self.db.execute(
            "UPDATE weight_plans SET goal_type = 'gain' WHERE user_id = ?",
            (self.user_id,),
        )
        today = "2026-05-23"
        self._add_weight("2026-05-02", 80.0)
        self._add_weight(today, 80.1)

        alert = check_plateau(self.db, self.user_id, today)
        self.assertIsNone(alert)


class TestBingeDay(TestHealthAlertsBase):
    """Tests for binge day detection."""

    def test_no_data_no_alert(self):
        alert = check_binge_day(self.db, self.user_id, "2026-05-23")
        self.assertIsNone(alert)

    def test_binge_detected(self):
        today = "2026-05-23"
        # 50% over 1800 = 2700; we log 3000 (>2700)
        self._add_summary(today, 3000, 100, 1800)

        alert = check_binge_day(self.db, self.user_id, today)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, "binge_day")

    def test_slight_over_no_alert(self):
        today = "2026-05-23"
        self._add_summary(today, 2000, 100, 1800)  # 11% over, under 50%

        alert = check_binge_day(self.db, self.user_id, today)
        self.assertIsNone(alert)


class TestExcessiveExercise(TestHealthAlertsBase):
    """Tests for excessive exercise detection."""

    def test_no_exercise_no_alert(self):
        alert = check_excessive_exercise(self.db, self.user_id, "2026-05-23")
        self.assertIsNone(alert)

    def test_excessive_exercise_detected(self):
        today = "2026-05-23"
        self._add_exercise(today, 900)  # > 800

        alert = check_excessive_exercise(self.db, self.user_id, today)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.alert_type, "excessive_exercise")

    def test_normal_exercise_no_alert(self):
        today = "2026-05-23"
        self._add_exercise(today, 500)

        alert = check_excessive_exercise(self.db, self.user_id, today)
        self.assertIsNone(alert)


class TestRunAllChecks(TestHealthAlertsBase):
    """Integration test for run_all_checks."""

    def test_empty_db_no_alerts(self):
        # Fresh DB with just user creation — no food/exercise/weight data
        alerts = run_all_checks(self.db, self.user_id, "2026-05-23")
        self.assertEqual(len(alerts), 0)

    def test_multiple_alerts_fired(self):
        today = "2026-05-23"

        # Set up low calorie streak (3 days < 1500)
        for i in range(3, 0, -1):
            dt = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
            self._add_summary(dt, 800, 30)

        # Set up rapid weight loss
        self._add_weight(today, 78.0)
        self._add_weight("2026-05-16", 80.0)

        # Set up binge day
        self._add_summary(today, 3000, 100, 1800)

        alerts = run_all_checks(self.db, self.user_id, today)
        # Should catch: low_calorie_streak, rapid_weight_loss, binge_day
        self.assertGreaterEqual(len(alerts), 2)

        alert_types = {a.alert_type for a in alerts}
        self.assertIn("low_calorie_streak", alert_types)
        self.assertIn("rapid_weight_loss", alert_types)
        self.assertIn("binge_day", alert_types)

    def test_plateau_triggers_auto_adjustment_and_new_active_plan(self):
        today = "2026-05-23"
        self.db.execute(
            """UPDATE weight_plans
               SET goal_weight_kg = 79.0, target_weeks = 8, target_date = '2026-07-18',
                   daily_calorie_target = 1800, activity_level = 'light'
               WHERE user_id = ? AND is_active = 1""",
            (self.user_id,),
        )
        self._add_weight("2026-05-09", 80.0)
        self._add_weight(today, 80.1)

        alerts = run_all_checks(self.db, self.user_id, today)
        plateau_alert = next((a for a in alerts if a.alert_type == "plateau"), None)
        self.assertIsNotNone(plateau_alert)
        self.assertIn("自動重算計劃", plateau_alert.message)
        self.assertIn("plan_adjustment", plateau_alert.details)

        active_plan = self.db.fetchone(
            """SELECT daily_calorie_target, warnings FROM weight_plans
               WHERE user_id = ? AND is_active = 1
               ORDER BY created_at DESC LIMIT 1""",
            (self.user_id,),
        )
        self.assertIsNotNone(active_plan)
        self.assertLess(int(active_plan["daily_calorie_target"]), 1800)
        self.assertIn("停滯期自動調整", str(active_plan["warnings"]))

    def test_plateau_auto_adjustment_uses_exercise_strategy_at_safe_floor(self):
        today = "2026-05-23"
        self.db.execute(
            """UPDATE weight_plans
               SET goal_weight_kg = 68.0, target_weeks = 2, target_date = '2026-06-06',
                   daily_calorie_target = 1500, activity_level = 'light'
               WHERE user_id = ? AND is_active = 1""",
            (self.user_id,),
        )
        self._add_weight("2026-05-09", 80.0)
        self._add_weight(today, 80.0)

        alerts = run_all_checks(self.db, self.user_id, today)
        plateau_alert = next((a for a in alerts if a.alert_type == "plateau"), None)
        self.assertIsNotNone(plateau_alert)
        adjustment = plateau_alert.details.get("plan_adjustment", {})
        self.assertEqual(adjustment.get("strategy"), "increase_exercise_day")
        self.assertEqual(adjustment.get("recommendation"), "增加 1 天運動")


class TestAlertDB(TestHealthAlertsBase):
    """Tests for alert persistence and queries."""

    def test_get_active_alerts_empty(self):
        alerts = get_active_alerts(self.db, self.user_id)
        self.assertEqual(alerts, [])

    def test_acknowledge_alert(self):
        # Manually insert an alert
        self.db.execute(
            """INSERT INTO health_alerts (user_id, alert_type, severity, message)
               VALUES (?, 'test_alert', 'info', 'Test message')""",
            (self.user_id,),
        )
        row = self.db.fetchone(
            "SELECT alert_id FROM health_alerts WHERE user_id = ?",
            (self.user_id,),
        )
        self.assertIsNotNone(row)

        ok = acknowledge_alert(self.db, row["alert_id"])
        self.assertTrue(ok)

        active = get_active_alerts(self.db, self.user_id)
        self.assertEqual(len(active), 0)

        all_alerts = get_active_alerts(self.db, self.user_id, include_acked=True)
        self.assertEqual(len(all_alerts), 1)
        self.assertTrue(all_alerts[0]["acknowledged"])

    def test_acknowledge_nonexistent(self):
        ok = acknowledge_alert(self.db, "nonexistent_id")
        self.assertFalse(ok)


class TestFormatAlerts(unittest.TestCase):
    """Tests for alert formatting."""

    def test_empty_alerts(self):
        result = format_alerts([])
        self.assertIn("無健康警示", result)

    def test_format_warning(self):
        alerts = [{
            "alert_type": "low_calorie_streak",
            "severity": "warning",
            "message": "連續 3 天熱量過低",
            "acknowledged": False,
        }]
        result = format_alerts(alerts)
        self.assertIn("⚠️", result)
        self.assertIn("low_calorie_streak", result)
        self.assertIn("連續 3 天熱量過低", result)

    def test_format_critical(self):
        alerts = [{
            "alert_type": "rapid_weight_loss",
            "severity": "critical",
            "message": "一週降 2kg",
            "acknowledged": False,
        }]
        result = format_alerts(alerts)
        self.assertIn("🚨", result)

    def test_format_acknowledged(self):
        alerts = [{
            "alert_type": "test",
            "severity": "info",
            "message": "test",
            "acknowledged": True,
        }]
        result = format_alerts(alerts)
        self.assertIn("已讀", result)


if __name__ == "__main__":
    unittest.main()
