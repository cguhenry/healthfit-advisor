"""
tests/test_weight_chart.py

Unit + integration tests for weight_chart.py:
- _linear_trajectory
- _load_trajectory
- fetch_chart_data (no plan / no logs / mixed logs)
- render_ascii_chart
- _compute_progress_label
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# ── Load modules directly so we can test internal helpers ──────────────────
import weight_chart as wc_module

import db_manager as db_mod
importlib.reload(db_mod)
DBManager = db_mod.DBManager


# ═══════════════════════════════════════════════════════════════════════════
# _linear_trajectory
# ═══════════════════════════════════════════════════════════════════════════


class TestLinearTrajectory(unittest.TestCase):
    def test_start_to_goal(self):
        result = wc_module._linear_trajectory(
            start_weight=80.0, goal_weight=75.0, duration_days=5
        )
        self.assertEqual(len(result), 6)  # 0..5 inclusive
        self.assertEqual(result[0], 80.0)
        self.assertEqual(result[5], 75.0)
        # Should be linear
        step = (75.0 - 80.0) / 5
        for i, v in enumerate(result):
            self.assertAlmostEqual(v, 80.0 + step * i, places=3)

    def test_zero_duration(self):
        result = wc_module._linear_trajectory(
            start_weight=70.0, goal_weight=70.0, duration_days=0
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], 70.0)

    def test_one_day(self):
        result = wc_module._linear_trajectory(
            start_weight=80.0, goal_weight=79.0, duration_days=1
        )
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0], 80.0, places=3)
        self.assertAlmostEqual(result[1], 79.0, places=3)

    def test_rounding(self):
        result = wc_module._linear_trajectory(
            start_weight=80.0, goal_weight=75.6, duration_days=7
        )
        for v in result:
            self.assertEqual(v, round(v, 3))


# ═══════════════════════════════════════════════════════════════════════════
# _load_trajectory
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadTrajectory(unittest.TestCase):
    def test_valid_json_list(self):
        plan = {"trajectory_json": "[80.0, 79.0, 78.0]"}
        result = wc_module._load_trajectory(plan)
        self.assertEqual(result, [80.0, 79.0, 78.0])

    def test_none_returns_none(self):
        self.assertIsNone(wc_module._load_trajectory({}))
        self.assertIsNone(wc_module._load_trajectory({"trajectory_json": None}))

    def test_invalid_json_returns_none(self):
        self.assertIsNone(wc_module._load_trajectory({"trajectory_json": "not json"}))
        self.assertIsNone(wc_module._load_trajectory({"trajectory_json": "{}"}))
        self.assertIsNone(wc_module._load_trajectory({"trajectory_json": '{"a": 1}'}))

    def test_mixed_invalid_values_returns_nan_list(self):
        # Bad values are preserved as NaN (keeping positional alignment)
        result = wc_module._load_trajectory({"trajectory_json": "[80.0, null]"})
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 80.0)
        self.assertTrue(wc_module._is_nan(result[1]))  # null → NaN

        # Valid JSON string, but non-numeric value → NaN in position
        result2 = wc_module._load_trajectory({"trajectory_json": "[80.0, \"bad\"]"})
        self.assertIsInstance(result2, list)
        self.assertEqual(result2[0], 80.0)
        self.assertTrue(wc_module._is_nan(result2[1]))  # "bad" → NaN)

    def test_empty_list_returns_none(self):
        self.assertIsNone(wc_module._load_trajectory({"trajectory_json": "[]"}))


# ═══════════════════════════════════════════════════════════════════════════
# fetch_chart_data
# ═══════════════════════════════════════════════════════════════════════════


def _make_temp_db_with_plan(tmp_dir: Path, trajectory: list[float] | None = None) -> tuple[DBManager, str]:
    """Create a temp DB with a user and active weight plan. Returns (db, user_id)."""
    db = DBManager(tmp_dir / "test.db", fast_mode=True)
    db.initialize()

    user_id = "test_user_1"
    plan_start = "2026-05-01"

    # Upsert user
    db.upsert_user_profile({
        "user_id": user_id,
        "display_name": "Test User",
        "gender": "M",
        "age": 30,
        "height_cm": 170,
    })

    import json

    plan = {
        "current_weight_kg": 80.0,
        "goal_weight_kg": 75.0,
        "target_weeks": 2,
        "weekly_change_kg": -2.5,
        "weekly_change_pct": -3.125,
        "bmr": 1700,
        "tdee": 2200,
        "activity_level": "moderate",
        "daily_calorie_target": 1700,
        "daily_calorie_delta": -500,
        "macros": {"protein_g": 120, "carb_g": 150, "fat_g": 60},
        "goal_type": "loss",
        "warnings": [],
        "requires_professional_review": False,
        "dietary_restrictions": [],
        "plan_start_date": plan_start,
        "trajectory": trajectory,
    }

    db.save_active_plan(user_id, plan)
    return db, user_id


class TestFetchChartDataNoPlan(unittest.TestCase):
    def test_returns_none_when_no_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DBManager(Path(tmp) / "empty.db", fast_mode=True)
            db.initialize()
            db.upsert_user_profile({"user_id": "u1", "gender": "M", "age": 30, "height_cm": 170})
            result = wc_module.fetch_chart_data(db, "u1")
            self.assertIsNone(result)


class TestFetchChartDataNoLogs(unittest.TestCase):
    def test_builds_chart_with_no_weight_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, user_id = _make_temp_db_with_plan(Path(tmp))

            result = wc_module.fetch_chart_data(
                db, user_id,
                from_date=date(2026, 5, 1),
                to_date=date(2026, 5, 14),
            )

            self.assertIsNotNone(result)
            self.assertEqual(len(result.dates), 14)
            self.assertTrue(all(v is None for v in result.actual))
            self.assertTrue(all(isinstance(p, float) for p in result.predicted))
            self.assertEqual(result.plan_label, "減重計劃（2026-05-01 起）")
            self.assertEqual(result.goal_weight_kg, 75.0)


class TestFetchChartDataWithLogs(unittest.TestCase):
    def test_actual_weights_aligned_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, user_id = _make_temp_db_with_plan(Path(tmp), trajectory=[80.0, 75.0])

            # Insert weight log only on day 0 and day 1
            db.execute(
                """
                INSERT INTO weight_logs (user_id, log_date, weight_kg)
                VALUES (?, ?, ?)
                """,
                (user_id, "2026-05-01", 80.1),
            )
            db.execute(
                """
                INSERT INTO weight_logs (user_id, log_date, weight_kg)
                VALUES (?, ?, ?)
                """,
                (user_id, "2026-05-02", 78.0),
            )

            result = wc_module.fetch_chart_data(
                db, user_id,
                from_date=date(2026, 5, 1),
                to_date=date(2026, 5, 2),
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.actual[0], 80.1)
            self.assertEqual(result.actual[1], 78.0)


class TestFetchChartDataTrajectoryFromDB(unittest.TestCase):
    def test_loads_trajectory_from_json_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, user_id = _make_temp_db_with_plan(
                Path(tmp),
                trajectory=[80.0, 79.5, 79.0, 78.5, 78.0, 77.5, 77.0],
            )

            result = wc_module.fetch_chart_data(
                db, user_id,
                from_date=date(2026, 5, 1),
                to_date=date(2026, 5, 7),
            )

            self.assertIsNotNone(result)
            # Predicted values should match the stored trajectory
            self.assertAlmostEqual(result.predicted[0], 80.0, places=3)
            self.assertAlmostEqual(result.predicted[6], 77.0, places=3)


# ═══════════════════════════════════════════════════════════════════════════
# render_ascii_chart
# ═══════════════════════════════════════════════════════════════════════════


class TestRenderAsciiChartNoData(unittest.TestCase):
    def test_empty_chart_returns_no_data_message(self):
        import math

        data = wc_module.WeightChartData(
            plan_start_date=date(2026, 5, 1),
            dates=[],
            predicted=[],
            actual=[],
            goal_weight_kg=75.0,
            plan_daily_target_kcal=1700,
            plan_label="Test",
        )
        result = wc_module.render_ascii_chart(data)
        self.assertIn("沒有可視覺化的", result)


class TestRenderAsciiChartRenders(unittest.TestCase):
    def test_chart_contains_required_markers(self):
        d = [
            date(2026, 5, 1) + timedelta(days=i)
            for i in range(10)
        ]
        # Simulate a linear drop from 80 → 76
        pred = [80.0 - 0.4 * i for i in range(10)]
        act = [80.1, 79.5, None, None, 78.0, 77.5, None, None, None, 76.1]

        data = wc_module.WeightChartData(
            plan_start_date=date(2026, 5, 1),
            dates=d,
            predicted=pred,
            actual=act,
            goal_weight_kg=75.0,
            plan_daily_target_kcal=1700,
            plan_label="減重計劃（2026-05-01 起）",
        )
        result = wc_module.render_ascii_chart(data, width=40, height=10)

        self.assertIn("減重計劃", result)
        self.assertIn("預測曲線", result)
        self.assertIn("實際記錄", result)
        self.assertIn("目標體重", result)
        # Should contain at least one ● (actual)
        self.assertIn("●", result)
        # Should contain goal line character
        self.assertIn("━", result)


# ═══════════════════════════════════════════════════════════════════════════
# _compute_progress_label
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeProgressLabel(unittest.TestCase):
    def _make_data(
        self,
        predicted: list[float],
        actual: list[Optional[float]],
        goal_weight: float = 75.0,
    ) -> wc_module.WeightChartData:
        n = len(predicted)
        d = [date(2026, 5, 1) + timedelta(days=i) for i in range(n)]
        return wc_module.WeightChartData(
            plan_start_date=date(2026, 5, 1),
            dates=d,
            predicted=predicted,
            actual=actual,
            goal_weight_kg=goal_weight,
            plan_daily_target_kcal=1700,
            plan_label="Test",
        )

    def test_no_actual_points(self):
        data = self._make_data(
            predicted=[80.0, 79.0, 78.0],
            actual=[None, None, None],
        )
        result = wc_module._compute_progress_label(data)
        self.assertIn("尚無實際體重記錄", result)

    def test_on_track(self):
        data = self._make_data(
            predicted=[80.0, 79.0, 78.0],
            actual=[None, 79.0, None],  # actual == predicted at idx=1
        )
        result = wc_module._compute_progress_label(data)
        self.assertIn("如期進行", result)

    def test_ahead_for_weight_loss(self):
        data = self._make_data(
            predicted=[80.0, 79.0, 78.0],
            actual=[None, 78.0, None],  # actual < predicted → ahead
        )
        result = wc_module._compute_progress_label(data)
        self.assertIn("超前", result)
        self.assertIn("✅", result)

    def test_behind_for_weight_loss(self):
        data = self._make_data(
            predicted=[80.0, 79.0, 78.0],
            actual=[None, 80.0, None],  # actual > predicted → behind
        )
        result = wc_module._compute_progress_label(data)
        self.assertIn("落後", result)
        self.assertIn("⚠️", result)


if __name__ == "__main__":
    unittest.main()