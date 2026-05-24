#!/usr/bin/env python3
"""Tests for calorie_tracker.py — Phase 4 calorie tracking and history comparison."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager
from calorie_tracker import (
    DailySummary,
    FoodLogEntry,
    PeriodComparison,
    format_comparison,
    format_progress,
    get_calorie_progress,
    get_daily_summary,
    get_history_comparison,
    get_recent_trend,
    log_meal_analysis,
    normalize_phase3_analysis_payload,
    upsert_daily_summary,
)
from food_analyzer import AnalysisScenario, parse_llm_response


class CalorieTrackerTestCase(unittest.TestCase):
    """Tests that require a real (but temporary) SQLite database."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        self.db = DBManager(self.db_path, fast_mode=True)
        self.db.initialize()

        # Seed a user
        self.user_id = "test-user-001"
        self.db.upsert_user_profile(
            {
                "user_id": self.user_id,
                "display_name": "Test",
                "gender": "M",
                "age": 30,
                "height_cm": 175,
                "ethnicity": "east_asian",
            }
        )

    def tearDown(self) -> None:
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    # ── Helpers ─────────────────────────────────────────────────────────

    def _sample_foods(self, extra: dict | None = None) -> list[dict]:
        base = [
            {
                "name": "白飯",
                "estimated_g": 200,
                "calories": 280,
                "protein_g": 5,
                "carb_g": 60,
                "fat_g": 0.5,
                "fiber_g": 1,
                "sodium_mg": 5,
                "confidence": 0.95,
            },
            {
                "name": "煎鮭魚",
                "estimated_g": 150,
                "calories": 310,
                "protein_g": 33,
                "carb_g": 0,
                "fat_g": 20,
                "fiber_g": 0,
                "sodium_mg": 120,
                "confidence": 0.88,
            },
            {
                "name": "炒青菜",
                "estimated_g": 120,
                "calories": 80,
                "protein_g": 3,
                "carb_g": 8,
                "fat_g": 4,
                "fiber_g": 3,
                "sodium_mg": 200,
                "confidence": 0.92,
            },
        ]
        if extra:
            base.append(extra)
        return base

    # ── log_meal_analysis ───────────────────────────────────────────────

    def test_log_meal_analysis_basic(self):
        ids = log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods())
        self.assertEqual(len(ids), 3)

    def test_log_meal_analysis_with_total_nutrition(self):
        total = {"calories": 670, "protein_g": 41, "carb_g": 68, "fat_g": 24.5}
        ids = log_meal_analysis(
            self.db, self.user_id, "dinner", self._sample_foods(), total_nutrition=total
        )
        # 3 food rows + 1 MEAL_TOTAL row
        self.assertEqual(len(ids), 4)

    def test_log_meal_analysis_with_note(self):
        ids = log_meal_analysis(
            self.db, self.user_id, "breakfast", self._sample_foods(), note="Phase 4 test meal"
        )
        self.assertEqual(len(ids), 3)

    def test_log_meal_analysis_empty_foods(self):
        ids = log_meal_analysis(self.db, self.user_id, "snack", [])
        self.assertEqual(len(ids), 0)

    def test_log_meal_analysis_sets_ai_confidence(self):
        ids = log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods())
        row = self.db.fetch_one(
            "SELECT ai_confidence FROM food_logs WHERE log_id = ?", (ids[0],)
        )
        self.assertAlmostEqual(row["ai_confidence"], 0.95, places=2)

    def test_normalize_phase3_native_payload(self):
        foods, total = normalize_phase3_analysis_payload(
            {
                "foods": self._sample_foods(),
                "total_calories": 670,
                "macros": {"protein_g": 41, "carb_g": 68, "fat_g": 24.5, "fiber_g": 4},
                "confidence": 0.91,
            }
        )
        self.assertEqual(len(foods), 3)
        self.assertEqual(total["calories"], 670.0)
        self.assertEqual(total["protein_g"], 41.0)

    def test_normalize_phase3_rejects_missing_food_name(self):
        with self.assertRaises(ValueError):
            normalize_phase3_analysis_payload({"foods": [{"calories": 100}]})

    def test_phase3_to_phase4_roundtrip_preserves_food_nutrition(self):
        analysis = parse_llm_response(
            AnalysisScenario.FOOD,
            {
                "foods": [
                    {
                        "name": "白飯",
                        "estimated_g": 200,
                        "calories": 260,
                        "protein_g": 4.5,
                        "carb_g": 58,
                        "fat_g": 0.6,
                        "confidence": 0.92,
                    },
                    {
                        "name": "雞胸肉",
                        "estimated_g": 120,
                        "calories": 198,
                        "protein_g": 36,
                        "carb_g": 0,
                        "fat_g": 4,
                        "confidence": 0.89,
                    },
                ],
                "total_calories": 458,
                "macros": {"protein_g": 40.5, "carb_g": 58, "fat_g": 4.6},
                "confidence": 0.88,
                "nutrition_advice": "ok",
            },
        )
        foods, total = normalize_phase3_analysis_payload(analysis.to_dict())
        log_meal_analysis(self.db, self.user_id, "lunch", foods, total_nutrition=total)

        summary = upsert_daily_summary(self.db, self.user_id, calorie_target=2000)
        self.assertAlmostEqual(summary.total_calories, 458.0, places=1)
        self.assertAlmostEqual(summary.total_protein_g, 40.5, places=1)

    # ── upsert_daily_summary ────────────────────────────────────────────

    def test_upsert_daily_summary_creates_new(self):
        log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods())
        summary = upsert_daily_summary(self.db, self.user_id, calorie_target=2000)
        self.assertAlmostEqual(summary.total_calories, 670.0, places=1)
        self.assertAlmostEqual(summary.total_protein_g, 41.0, places=1)
        self.assertEqual(summary.calorie_target, 2000)
        self.assertAlmostEqual(summary.calorie_balance, 670 - 2000, places=1)

    def test_upsert_daily_summary_excludes_meal_total(self):
        total = {"calories": 9999, "protein_g": 0, "carb_g": 0, "fat_g": 0}
        log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods(), total_nutrition=total)
        summary = upsert_daily_summary(self.db, self.user_id, calorie_target=2000)
        # Should NOT double-count; total = 280 + 310 + 80 = 670, not 670 + 9999
        self.assertAlmostEqual(summary.total_calories, 670.0, places=1)

    def test_upsert_daily_summary_updates_existing(self):
        log_meal_analysis(self.db, self.user_id, "breakfast", self._sample_foods())
        upsert_daily_summary(self.db, self.user_id, calorie_target=1800)

        # Add more food → re-upsert
        extra = [
            {"name": "茶葉蛋", "estimated_g": 55, "calories": 78, "protein_g": 7, "carb_g": 0.5, "fat_g": 5, "confidence": 0.95}
        ]
        log_meal_analysis(self.db, self.user_id, "snack", extra)
        summary = upsert_daily_summary(self.db, self.user_id, calorie_target=1800)
        self.assertAlmostEqual(summary.total_calories, 670 + 78, places=1)

    def test_upsert_daily_summary_empty_logs(self):
        summary = upsert_daily_summary(self.db, self.user_id, calorie_target=2000)
        self.assertEqual(summary.total_calories, 0.0)
        self.assertEqual(summary.total_protein_g, 0.0)

    # ── get_daily_summary ───────────────────────────────────────────────

    def test_get_daily_summary_none_when_no_data(self):
        result = get_daily_summary(self.db, self.user_id)
        self.assertIsNone(result)

    def test_get_daily_summary_returns_existing(self):
        log_meal_analysis(self.db, self.user_id, "dinner", self._sample_foods())
        upsert_daily_summary(self.db, self.user_id, calorie_target=2200)
        result = get_daily_summary(self.db, self.user_id)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.total_calories, 670.0, places=1)

    # ── get_history_comparison ──────────────────────────────────────────

    def test_get_history_comparison_basic(self):
        td = date.today()
        yday = td - timedelta(days=1)
        lw = td - timedelta(days=7)

        # Log today: 670 kcal
        ts_today = datetime(td.year, td.month, td.day, 12, 0, tzinfo=timezone.utc).isoformat()
        log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods(),
                           log_datetime=ts_today)

        # Log yesterday: 400 kcal
        ts_yday = datetime(yday.year, yday.month, yday.day, 12, 0, tzinfo=timezone.utc).isoformat()
        log_meal_analysis(
            self.db, self.user_id, "lunch",
            [{"name": "三明治", "estimated_g": 200, "calories": 400, "protein_g": 20, "carb_g": 45, "fat_g": 15, "confidence": 0.9}],
            log_datetime=ts_yday,
        )

        # Log last week: 500 kcal
        ts_lw = datetime(lw.year, lw.month, lw.day, 12, 0, tzinfo=timezone.utc).isoformat()
        log_meal_analysis(
            self.db, self.user_id, "lunch",
            [{"name": "便當", "estimated_g": 400, "calories": 500, "protein_g": 25, "carb_g": 55, "fat_g": 18, "confidence": 0.85}],
            log_datetime=ts_lw,
        )

        comparisons = get_history_comparison(self.db, self.user_id, today=td)

        self.assertGreaterEqual(len(comparisons), 3)

        # vs 昨日
        vs_yesterday = [c for c in comparisons if "昨日" in c.period_label]
        self.assertTrue(vs_yesterday, "Missing vs-yesterday comparison")
        yd = vs_yesterday[0]
        self.assertAlmostEqual(float(yd.current["calories"]), 670.0)
        self.assertAlmostEqual(float(yd.previous["calories"]), 400.0)
        self.assertEqual(yd.delta["calories"]["absolute"], 270.0)

        # vs 上週同一天
        vs_lw = [c for c in comparisons if "上週" in c.period_label]
        self.assertTrue(vs_lw, "Missing vs-last-week comparison")
        lwd = vs_lw[0]
        self.assertAlmostEqual(float(lwd.current["calories"]), 670.0)
        self.assertAlmostEqual(float(lwd.previous["calories"]), 500.0)

    def test_get_history_comparison_no_previous_data(self):
        td = date.today()
        ts_today = datetime(td.year, td.month, td.day, 12, 0, tzinfo=timezone.utc).isoformat()
        log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods(),
                           log_datetime=ts_today)

        comparisons = get_history_comparison(self.db, self.user_id, today=td)
        self.assertTrue(any("昨日" in c.period_label for c in comparisons))

    def test_get_history_comparison_handles_cross_month_yesterday(self):
        td = date(2026, 5, 1)
        yday = td - timedelta(days=1)

        ts_today = datetime(td.year, td.month, td.day, 12, 0, tzinfo=timezone.utc).isoformat()
        ts_yday = datetime(yday.year, yday.month, yday.day, 12, 0, tzinfo=timezone.utc).isoformat()

        log_meal_analysis(
            self.db, self.user_id, "lunch",
            [{"name": "today meal", "estimated_g": 200, "calories": 450, "protein_g": 25, "carb_g": 40, "fat_g": 12, "confidence": 0.9}],
            log_datetime=ts_today,
        )
        log_meal_analysis(
            self.db, self.user_id, "dinner",
            [{"name": "yesterday meal", "estimated_g": 180, "calories": 380, "protein_g": 18, "carb_g": 42, "fat_g": 10, "confidence": 0.9}],
            log_datetime=ts_yday,
        )

        comparisons = get_history_comparison(self.db, self.user_id, today=td)
        vs_yesterday = [c for c in comparisons if "昨日" in c.period_label][0]

        self.assertEqual(vs_yesterday.previous["date"], "2026-04-30")
        self.assertAlmostEqual(float(vs_yesterday.previous["calories"]), 380.0)

    # ── get_recent_trend ────────────────────────────────────────────────

    def test_get_recent_trend_fills_missing_days(self):
        td = date.today()
        d1 = td - timedelta(days=2)
        ts = datetime(d1.year, d1.month, d1.day, 12, 0, tzinfo=timezone.utc).isoformat()
        log_meal_analysis(
            self.db, self.user_id, "lunch",
            [{"name": "pasta", "estimated_g": 300, "calories": 500, "protein_g": 18, "carb_g": 70, "fat_g": 15, "confidence": 0.9}],
            log_datetime=ts,
        )
        trend = get_recent_trend(self.db, self.user_id, days=7, end_date=td)
        self.assertEqual(len(trend), 7)
        # Only one day should have calories
        nonzero = [d for d in trend if d["calories"] > 0]
        self.assertEqual(len(nonzero), 1)
        self.assertAlmostEqual(nonzero[0]["calories"], 500.0)

    def test_get_recent_trend_custom_days(self):
        trend = get_recent_trend(self.db, self.user_id, days=3)
        self.assertEqual(len(trend), 3)

    def test_get_recent_trend_handles_cross_month_range(self):
        end_date = date(2026, 5, 5)
        logged_day = date(2026, 4, 30)
        ts = datetime(logged_day.year, logged_day.month, logged_day.day, 12, 0, tzinfo=timezone.utc).isoformat()
        log_meal_analysis(
            self.db, self.user_id, "lunch",
            [{"name": "cross month meal", "estimated_g": 250, "calories": 520, "protein_g": 22, "carb_g": 68, "fat_g": 14, "confidence": 0.9}],
            log_datetime=ts,
        )

        trend = get_recent_trend(self.db, self.user_id, days=7, end_date=end_date)

        self.assertEqual(len(trend), 7)
        self.assertEqual(trend[0]["date"], "2026-04-29")
        self.assertEqual(trend[-1]["date"], "2026-05-05")
        nonzero = [d for d in trend if d["calories"] > 0]
        self.assertEqual(len(nonzero), 1)
        self.assertEqual(nonzero[0]["date"], "2026-04-30")
        self.assertAlmostEqual(nonzero[0]["calories"], 520.0)

    def test_get_recent_trend_handles_exact_day_boundary(self):
        end_date = date(2026, 5, 7)
        trend = get_recent_trend(self.db, self.user_id, days=7, end_date=end_date)
        self.assertEqual(len(trend), 7)
        self.assertEqual(trend[0]["date"], "2026-05-01")
        self.assertEqual(trend[-1]["date"], "2026-05-07")

    # ── get_calorie_progress ────────────────────────────────────────────

    def test_get_calorie_progress_no_plan(self):
        log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods())
        prog = get_calorie_progress(self.db, self.user_id)
        self.assertAlmostEqual(prog["calories_consumed"], 670.0, places=1)
        self.assertEqual(prog["calorie_target"], 0)  # No plan = no target

    def test_get_calorie_progress_with_active_plan(self):
        # Create an active plan
        self.db.save_active_plan(
            self.user_id,
            {
                "current_weight_kg": 80,
                "goal_weight_kg": 75,
                "target_weeks": 12,
                "weekly_change_kg": -0.42,
                "weekly_change_pct": -0.5,
                "bmr": 1650,
                "tdee": 2300,
                "activity_level": "moderate",
                "daily_calorie_target": 1800,
                "daily_calorie_delta": -500,
                "goal_type": "loss",
                "macros": {"protein_g": 135, "carb_g": 180, "fat_g": 50},
                "warnings": [],
                "requires_professional_review": False,
            },
        )

        prog = get_calorie_progress(self.db, self.user_id)
        self.assertEqual(prog["calorie_target"], 1800)
        self.assertEqual(prog["protein_target_g"], 135)

    def test_get_calorie_progress_meal_breakdown(self):
        log_meal_analysis(self.db, self.user_id, "breakfast",
            [{"name": "吐司", "calories": 150, "protein_g": 5, "estimated_g": 80, "confidence": 0.9}])
        log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods())
        log_meal_analysis(self.db, self.user_id, "dinner",
            [{"name": "沙拉", "calories": 120, "protein_g": 8, "estimated_g": 200, "confidence": 0.85}])

        prog = get_calorie_progress(self.db, self.user_id)
        breakdown = prog["meal_breakdown"]
        self.assertIn("breakfast", breakdown)
        self.assertIn("lunch", breakdown)
        self.assertIn("dinner", breakdown)
        self.assertAlmostEqual(breakdown["breakfast"]["calories"], 150.0)
        self.assertAlmostEqual(breakdown["lunch"]["calories"], 670.0)
        self.assertAlmostEqual(breakdown["dinner"]["calories"], 120.0)
        self.assertAlmostEqual(prog["calories_consumed"], 150 + 670 + 120, places=1)

    # ── format_progress ─────────────────────────────────────────────────

    def test_format_progress(self):
        prog = {
            "date": "2026-05-22",
            "calorie_target": 2000,
            "calories_consumed": 1450,
            "calories_remaining": 550,
            "progress_pct": 72.5,
            "protein_target_g": 140,
            "protein_consumed_g": 98,
            "protein_remaining_g": 42,
            "meal_breakdown": {
                "breakfast": {"calories": 350, "protein_g": 25},
                "lunch": {"calories": 800, "protein_g": 55},
            },
        }
        output = format_progress(prog)
        self.assertIn("1450 kcal", output)
        self.assertIn("72", output)
        self.assertIn("550", output)
        self.assertIn("98g", output)

    # ── format_comparison ───────────────────────────────────────────────

    def test_format_comparison(self):
        comparisons = [
            PeriodComparison(
                period_label="vs 昨日",
                current={"date": "2026-05-22", "calories": 670, "protein_g": 41},
                previous={"date": "2026-05-21", "calories": 500, "protein_g": 30},
                delta={
                    "calories": {"absolute": 170, "pct": 34.0},
                    "protein_g": {"absolute": 11, "pct": 36.7},
                },
            ),
        ]
        output = format_comparison(comparisons)
        self.assertIn("vs 昨日", output)
        self.assertIn("670 kcal", output)
        self.assertIn("↑", output)
        self.assertIn("170 kcal", output)

    # ── Edge: log_meal_analysis with missing optional fields ─────────────

    def test_log_meal_analysis_missing_fields_default_to_zero(self):
        ids = log_meal_analysis(
            self.db, self.user_id, "lunch",
            [{"name": "湯品"}],  # only name given
        )
        self.assertEqual(len(ids), 1)
        row = self.db.fetch_one("SELECT * FROM food_logs WHERE log_id = ?", (ids[0],))
        self.assertEqual(row["calories"], 0.0)
        self.assertEqual(row["protein_g"], 0.0)
        self.assertEqual(row["ai_confidence"], 0.0)

    # ── Edge: compare with no food_logs at all ──────────────────────────

    def test_get_calorie_progress_empty_logs(self):
        prog = get_calorie_progress(self.db, self.user_id)
        self.assertEqual(prog["calories_consumed"], 0.0)
        self.assertEqual(prog["progress_pct"], 0.0)

    def test_upsert_daily_summary_with_custom_date(self):
        custom_date = "2026-01-15"
        ts = "2026-01-15T12:00:00+00:00"
        log_meal_analysis(self.db, self.user_id, "lunch", self._sample_foods(), log_datetime=ts)
        summary = upsert_daily_summary(self.db, self.user_id, custom_date, calorie_target=2000)
        self.assertEqual(summary.summary_date, custom_date)
        self.assertAlmostEqual(summary.total_calories, 670.0, places=1)


if __name__ == "__main__":
    unittest.main()
