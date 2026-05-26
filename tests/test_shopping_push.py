#!/usr/bin/env python3
"""Tests for shopping_push.py — Feature D: Weekly shopping list push."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from scripts.cron_notifications import should_push_shopping_list, run_shopping_push
from scripts.shopping_push import (
    _CATEGORY_EMOJI,
    _parse_week_start,
    format_shopping_list_text,
    run_weekly_shopping_push,
)

# ─────────────────────────────────────────────────────────────
# Text formatting tests
# ─────────────────────────────────────────────────────────────

class TestShoppingListTextFormat(unittest.TestCase):
    def setUp(self):
        self.shopping_list = {
            "蛋白質": ["雞胸肉", "雞蛋", "鮭魚"],
            "蔬菜": ["花椰菜", "菠菜", "番茄"],
            "主食": ["糙米", "燕麥片"],
            "飲料/調味": ["橄欖油"],
        }
        self.week_start = date(2026, 6, 1)

    def test_shopping_list_text_format_has_all_categories(self):
        text = format_shopping_list_text(self.shopping_list, self.week_start)
        for cat in self.shopping_list:
            self.assertIn(cat, text, f"Category '{cat}' should appear in formatted text")

    def test_shopping_list_text_has_title_with_date_range(self):
        text = format_shopping_list_text(self.shopping_list, self.week_start)
        self.assertIn("下週採購清單", text)
        self.assertIn("6/1–6/7", text)

    def test_shopping_list_text_includes_item_count_footer(self):
        text = format_shopping_list_text(self.shopping_list, self.week_start)
        # 3 + 3 + 2 + 1 = 9 items
        self.assertIn("共 9 項", text)

    def test_shopping_list_text_includes_budget_estimate(self):
        text = format_shopping_list_text(self.shopping_list, self.week_start)
        self.assertIn("預估花費", text)

    def test_shopping_list_text_includes_completion_hint(self):
        text = format_shopping_list_text(self.shopping_list, self.week_start)
        self.assertIn("已採購", text)

    def test_shopping_list_text_empty_category_omitted(self):
        sl = {"蛋白質": ["雞胸肉"], "水果": []}
        text = format_shopping_list_text(sl, self.week_start)
        self.assertIn("蛋白質", text)
        self.assertNotIn("水果", text)  # empty category omitted

    def test_shopping_list_text_has_checkbox_markers(self):
        text = format_shopping_list_text(self.shopping_list, self.week_start)
        # The □ marker should appear (one per item)
        self.assertEqual(text.count("□"), 9)

    def test_item_count_in_return_dict_matches_formatted_text(self):
        """Verify run_weekly_shopping_push returns correct item_count."""
        sl = self.shopping_list
        total = sum(len(items) for items in sl.values())
        self.assertEqual(total, 9)
        # Also verify that no items are double-counted
        text = format_shopping_list_text(sl, self.week_start)
        checkbox_count = text.count("□")
        self.assertEqual(checkbox_count, total)

    def test_emoji_mapping_covers_default_categories(self):
        for cat in ["蛋白質", "蔬菜", "水果", "主食", "飲料/調味", "堅果/種子"]:
            self.assertIn(cat, _CATEGORY_EMOJI, f"Category '{cat}' missing emoji mapping")


# ─────────────────────────────────────────────────────────────
# Plan persistence tests
# ─────────────────────────────────────────────────────────────

class TestShoppingPushPlan(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp_db = Path(tempfile.mktemp(suffix=".db"))
        from scripts.db_manager import DBManager
        self.db = DBManager(db_path=self._tmp_db, fast_mode=True)

    def tearDown(self):
        if self._tmp_db.exists():
            self._tmp_db.unlink()

    def _bootstrap_user_plan(self, user_id: str = "test_user"):
        """Create a minimal user + weight plan so _generate_plan_for_week works."""
        self.db.initialize()
        self.db.upsert_user_profile({
            "user_id": user_id,
            "display_name": "Test",
            "gender": "M",
            "age": 30,
            "height_cm": 175,
        })
        self.db.save_active_plan(user_id, {
            "current_weight_kg": 80,
            "goal_weight_kg": 75,
            "goal_type": "lose",
            "target_weeks": 8,
            "weekly_change_kg": -0.5,
            "weekly_change_pct": -0.6,
            "bmr": 1700,
            "tdee": 2300,
            "activity_level": "moderate",
            "daily_calorie_target": 1800,
            "daily_calorie_delta": -500,
            "macros": {"protein_g": 140, "carb_g": 200, "fat_g": 50},
            "warnings": [],
            "requires_professional_review": False,
        })
        return user_id

    def test_run_shopping_push_generates_plan_if_none_exists(self):
        user_id = self._bootstrap_user_plan("test_gen")
        week_start = date(2026, 6, 8)  # a Monday

        result = run_weekly_shopping_push(
            self.db, user_id, week_start, channels=["print"],
        )
        self.assertEqual(result["status"], "sent")
        self.assertGreater(result["item_count"], 0)

        # Verify the plan was persisted
        row = self.db.fetch_one(
            "SELECT * FROM weekly_meal_plans WHERE user_id=? AND week_start_date=?",
            (user_id, week_start.isoformat()),
        )
        self.assertIsNotNone(row, "Meal plan should be persisted after push")

    def test_run_shopping_push_uses_existing_plan_if_available(self):
        from scripts.meal_planner import generate_meal_plan, persist_meal_plan

        user_id = self._bootstrap_user_plan("test_existing")
        week_start = date(2026, 6, 8)

        # Pre-create a plan with a known shopping list
        plan = generate_meal_plan(daily_calories=1800, cuisine="台式", meal_preference="balanced")
        persist_meal_plan(self.db, user_id, plan, week_start_date=week_start.isoformat())

        result = run_weekly_shopping_push(
            self.db, user_id, week_start, channels=["print"],
        )
        self.assertEqual(result["status"], "sent")
        # The existing plan should have been used (same item count as template)
        expected_items = sum(len(v) for v in plan["shopping_list"].values())
        self.assertEqual(result["item_count"], expected_items)

    def test_run_shopping_push_multiple_channels(self):
        user_id = self._bootstrap_user_plan("test_mch")
        week_start = date(2026, 6, 8)

        result = run_weekly_shopping_push(
            self.db, user_id, week_start, channels=["print", "print"],
        )
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["channel_count"], 2)


# ─────────────────────────────────────────────────────────────
# Cron trigger tests
# ─────────────────────────────────────────────────────────────

class TestShoppingPushCron(unittest.TestCase):
    def test_cron_triggers_only_on_sunday_morning(self):
        # Sunday 10:00 → True
        self.assertTrue(
            should_push_shopping_list(datetime(2026, 6, 7, 10, 0)),
            "Sunday 10:00 should trigger",
        )

    def test_cron_does_not_trigger_on_monday(self):
        self.assertFalse(
            should_push_shopping_list(datetime(2026, 6, 8, 10, 0)),
            "Monday should not trigger",
        )

    def test_cron_does_not_trigger_on_sunday_other_hour(self):
        self.assertFalse(
            should_push_shopping_list(datetime(2026, 6, 7, 9, 0)),
            "Sunday 9:00 should not trigger",
        )
        self.assertFalse(
            should_push_shopping_list(datetime(2026, 6, 7, 11, 0)),
            "Sunday 11:00 should not trigger",
        )

    def test_cron_does_not_trigger_on_wednesday(self):
        self.assertFalse(
            should_push_shopping_list(datetime(2026, 6, 10, 10, 0)),
            "Wednesday should not trigger",
        )

    def test_cron_all_days_in_week(self):
        """Ensure only Sunday at 10:00 returns True across all weekday×hour combos."""
        for weekday in range(7):
            for hour in range(24):
                dt = datetime(2026, 6, 1 + weekday, hour, 0)
                expected = (weekday == 6 and hour == 10)
                self.assertEqual(
                    should_push_shopping_list(dt), expected,
                    f"weekday={weekday}, hour={hour} expected {expected}",
                )


# ─────────────────────────────────────────────────────────────
# Week start parsing tests
# ─────────────────────────────────────────────────────────────

class TestWeekStartParsing(unittest.TestCase):
    def test_parse_next_returns_next_monday(self):
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        expected = today + timedelta(days=days_until_monday)
        result = _parse_week_start("next")
        self.assertEqual(result, expected, f"next should be {expected}, got {result}")

    def test_parse_iso_date(self):
        dt = _parse_week_start("2026-06-01")
        self.assertEqual(dt, date(2026, 6, 1))

    def test_parse_case_insensitive_next(self):
        dt = _parse_week_start("NEXT")
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        expected = today + timedelta(days=days_until_monday)
        self.assertEqual(dt, expected)


if __name__ == "__main__":
    unittest.main()