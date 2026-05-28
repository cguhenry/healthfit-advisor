#!/usr/bin/env python3
"""Tests for can_i_eat.py — Feature F: 「今天能不能吃 X？」即時查詢."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db_manager import DBManager
from can_i_eat import (
    CanIEatResult,
    _determine_verdict,
    _build_alternatives,
    _build_adjusted_suggestion,
    _default_serving_for,
    check_can_i_eat,
    format_result,
)


class TestVerdictLogic(unittest.TestCase):
    """Unit tests for the verdict determination logic (no DB needed)."""

    def test_within_budget_returns_yes(self):
        verdict, advice = _determine_verdict(
            food_calories=400, remaining=500, daily_target=2000, goal_type="loss"
        )
        self.assertEqual(verdict, "yes")
        self.assertIn("可以吃", advice)

    def test_slight_overshoot_returns_yes_with_caveat(self):
        # overshoot = 100, daily_target = 2000 → 5%, should be yes_with_caveat for loss
        verdict, advice = _determine_verdict(
            food_calories=1100, remaining=1000, daily_target=2000, goal_type="loss"
        )
        self.assertEqual(verdict, "yes_with_caveat")
        self.assertIn("略超標", advice)

    def test_moderate_overshoot_returns_marginal(self):
        # overshoot = 260 → 13% of 2000, between 5-15%
        verdict, advice = _determine_verdict(
            food_calories=760, remaining=500, daily_target=2000, goal_type="loss"
        )
        self.assertEqual(verdict, "marginal")
        self.assertIn("需要其他餐減量", advice)

    def test_large_overshoot_returns_no(self):
        # overshoot = 700 → 35% of 2000
        verdict, advice = _determine_verdict(
            food_calories=1200, remaining=500, daily_target=2000, goal_type="loss"
        )
        self.assertEqual(verdict, "no")
        self.assertIn("超出今日剩餘", advice)

    def test_exact_boundary_returns_yes(self):
        # overshoot = 0
        verdict, advice = _determine_verdict(
            food_calories=500, remaining=500, daily_target=2000, goal_type="loss"
        )
        self.assertEqual(verdict, "yes")

    def test_gain_plan_threshold_is_more_lenient(self):
        # For loss: caveat=100 (5%), marginal=300 (15%)
        # For gain: caveat=200 (10%), marginal=500 (25%)
        # overshoot = 180 → 9% of 2000
        # loss: yes_with_caveat (180 <= 100? No → 180 <= 300? Yes → marginal)
        # gain: yes_with_caveat (180 <= 200? Yes)
        loss_v, _ = _determine_verdict(
            food_calories=680, remaining=500, daily_target=2000, goal_type="loss"
        )
        gain_v, _ = _determine_verdict(
            food_calories=680, remaining=500, daily_target=2000, goal_type="gain"
        )
        # Loss rates it "marginal", gain rates it "yes_with_caveat" (more lenient)
        self.assertEqual(loss_v, "marginal")
        self.assertEqual(gain_v, "yes_with_caveat")

    def test_gain_plan_large_overshoot_still_no(self):
        # overshoot = 800 → 40% of 2000 → above 35% threshold
        verdict, advice = _determine_verdict(
            food_calories=1300, remaining=500, daily_target=2000, goal_type="gain"
        )
        self.assertEqual(verdict, "no")


class TestHelpers(unittest.TestCase):
    """Tests for helper functions."""

    def test_default_serving_for_known_food(self):
        grams = _default_serving_for("拉麵")
        self.assertEqual(grams, 350.0)

    def test_default_serving_for_unknown_food(self):
        grams = _default_serving_for("奇怪的東西")
        self.assertEqual(grams, 200.0)

    def test_alternatives_for_ramen(self):
        alts = _build_alternatives("拉麵", remaining=400, protein_gap=18)
        self.assertGreater(len(alts), 0)
        self.assertTrue(any("蕎麥冷麵" in a for a in alts))
        self.assertTrue(any("在配額內" in a for a in alts))

    def test_alternatives_for_unknown_food(self):
        alts = _build_alternatives("隨便什麼", remaining=50, protein_gap=10)
        self.assertGreater(len(alts), 0)

    def test_adjusted_suggestion_includes_protein_hint(self):
        suggestion = _build_adjusted_suggestion(
            food_calories=400, remaining=500, protein_gap=18,
            food_name="一碗拉麵", meal_type=None, goal_type="loss"
        )
        self.assertIn("蛋白質", suggestion)


class TestCanIEatWithDB(unittest.TestCase):
    """Integration tests that require a temporary SQLite database."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        self.db = DBManager(self.db_path, fast_mode=True)
        self.db.initialize()

        self.user_id = "test-cie-user"
        self.today = date.today().isoformat()
        self.db.upsert_user_profile({
            "user_id": self.user_id,
            "display_name": "CIE Test",
            "gender": "M",
            "age": 30,
            "height_cm": 175,
        })

    def tearDown(self) -> None:
        self.db_path.unlink(missing_ok=True)

    def _setup_plan(self, goal_type: str = "loss", calorie_target: int = 2000,
                    protein_target: int = 120):
        """Insert a weight_plan and a starting weight record."""
        import uuid

        self.db.execute(
            """INSERT INTO weight_plans
               (plan_id, user_id, start_weight_kg, goal_weight_kg, target_weeks,
                daily_calorie_target, protein_target_g, carb_target_g, fat_target_g,
                goal_type, is_active)
               VALUES (?, ?, 80, 75, 12, ?, ?, 200, 60, ?, 1)""",
            (str(uuid.uuid4()), self.user_id, calorie_target, protein_target, goal_type),
        )

    def _log_food(self, food_name: str, calories: float, protein_g: float,
                  meal_type: str = "lunch"):
        """Insert a food_log row for today."""
        import uuid

        self.db.execute(
            """INSERT INTO food_logs
               (log_id, user_id, meal_type, log_datetime, food_name,
                quantity_g, calories, protein_g, carb_g, fat_g)
               VALUES (?, ?, ?, ?, ?, 200, ?, ?, 0, 0)""",
            (str(uuid.uuid4()), self.user_id, meal_type,
             f"{self.today}T12:00:00", food_name, calories, protein_g),
        )

    def test_within_budget_returns_yes(self):
        self._setup_plan(goal_type="loss", calorie_target=2000, protein_target=120)
        self._log_food("雞胸肉", 400, 35)

        result = check_can_i_eat(self.db, self.user_id, "蕎麥冷麵")
        self.assertEqual(result.verdict, "yes")
        self.assertEqual(result.protein_gap, 85.0)  # 120 - 35 = 85
        self.assertGreater(result.estimated_calories, 0)

    def test_large_overshoot_returns_no_with_alternatives(self):
        self._setup_plan(goal_type="loss", calorie_target=2000, protein_target=120)
        self._log_food("雞胸肉", 400, 35)
        self._log_food("白飯", 400, 5)
        self._log_food("滷排骨", 600, 30)
        # consumed = 1400, remaining = 600

        result = check_can_i_eat(self.db, self.user_id, "拉麵", quantity=2)  # ~1300+ kcal
        self.assertIn(result.verdict, ("marginal", "no"))
        self.assertGreater(len(result.alternatives), 0)

    def test_gain_plan_is_more_lenient(self):
        self._setup_plan(goal_type="gain", calorie_target=2000, protein_target=140)
        self._log_food("沙拉", 400, 20)
        # consumed = 400, remaining = 1600
        # Push remaining down so pearl milk tea (scene estimate ~550) overshoots
        self._log_food("牛排", 800, 60)
        self._log_food("米飯", 400, 5)
        # consumed = 1600, remaining = 400
        # Pearl milk tea ~550 → overshoot = 150
        # gain: caveat=200 (10%), marginal=500 (25%) → 150 <= 200 → yes_with_caveat
        # loss: caveat=100 (5%), marginal=300 (15%) → 150 <= 300 → marginal
        # So gain is indeed more lenient

        result = check_can_i_eat(self.db, self.user_id, "珍珠奶茶", quantity=1)
        self.assertEqual(result.verdict, "yes_with_caveat")
        self.assertEqual(result.goal_type, "gain")

    def test_unknown_food_returns_estimate_with_low_confidence(self):
        self._setup_plan(goal_type="loss", calorie_target=2000, protein_target=120)
        result = check_can_i_eat(self.db, self.user_id, "外星食物")
        self.assertTrue(result._is_estimate)
        self.assertIn("系統未找到精確資料", result.advice)

    def test_quantity_multiplier_scales_calories_correctly(self):
        self._setup_plan(goal_type="loss", calorie_target=2000, protein_target=120)

        result_1 = check_can_i_eat(self.db, self.user_id, "拉麵", quantity=1)
        result_2 = check_can_i_eat(self.db, self.user_id, "拉麵", quantity=2)

        # Quantity 2 should have roughly 2x the calories
        if result_1.estimated_calories > 0 and result_2.estimated_calories > 0:
            ratio = result_2.estimated_calories / result_1.estimated_calories
            self.assertAlmostEqual(ratio, 2.0, delta=0.5)

    def test_result_includes_protein_gap_hint(self):
        self._setup_plan(goal_type="loss", calorie_target=2000, protein_target=120)
        self._log_food("雞胸肉", 400, 40)
        # protein consumed = 40, target = 120, gap = 80

        result = check_can_i_eat(self.db, self.user_id, "蕎麥冷麵")
        self.assertGreater(result.protein_gap, 0)
        formatted = format_result(result)
        self.assertIn("蛋白質", formatted)

    def test_no_data_fallback_requires_active_plan(self):
        """When no weight plan exists, check_can_i_eat raises RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            check_can_i_eat(self.db, self.user_id, "蕎麥冷麵")
        err = str(ctx.exception)
        self.assertTrue("active" in err or "計畫" in err)

    def test_format_result_includes_all_sections(self):
        self._setup_plan(goal_type="loss", calorie_target=2000, protein_target=120)
        result = check_can_i_eat(self.db, self.user_id, "拉麵", quantity=3)
        formatted = format_result(result)
        self.assertIn("熱量估算", formatted)
        self.assertIn("今日剩餘", formatted)

    def test_can_i_eat_requires_active_plan(self):
        """Without an active weight plan, check_can_i_eat raises RuntimeError."""
        db2_path = Path(self.tmp.name + "_no_plan")
        try:
            db2 = DBManager(db2_path, fast_mode=True)
            db2.initialize()
            with self.assertRaises(RuntimeError) as ctx:
                check_can_i_eat(db2, "no-plan-user", "珍珠奶茶")
            err = str(ctx.exception)
            self.assertTrue("active" in err or "計畫" in err)
        finally:
            db2_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()