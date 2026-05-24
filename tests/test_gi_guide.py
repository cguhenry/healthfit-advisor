#!/usr/bin/env python3
"""Tests for Phase 6 gi_guide.py."""

import io
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))

import scripts.gi_guide as GI_MODULE
from scripts.db_manager import DBManager
from scripts.gi_guide import (
    classify_food,
    recommend_swap,
    get_meal_strategy,
    get_food_list_by_tier,
    GI_LOW,
    GI_HIGH,
    _PHASE_STRATEGIES,
    _GI_SWAPS,
    _FOOD_GI_DB,
    _FOOD_GI_DB as FOOD_GI_DB,
)


class TestClassifyFood(unittest.TestCase):
    """Tests for food GI classification."""

    def test_high_gi_food(self):
        result = classify_food("白米飯")
        self.assertTrue(result["found"])
        self.assertEqual(result["gi"], 83)
        self.assertEqual(result["tier"], "high")
        self.assertIn("高GI", result["advice"])

    def test_medium_gi_food(self):
        result = classify_food("饅頭")
        self.assertTrue(result["found"])
        self.assertEqual(result["gi"], 68)
        self.assertEqual(result["tier"], "medium")

    def test_low_gi_food(self):
        result = classify_food("芭樂")
        self.assertTrue(result["found"])
        self.assertEqual(result["gi"], 12)
        self.assertEqual(result["tier"], "low")
        self.assertIn("低GI", result["advice"])

    def test_unknown_food(self):
        result = classify_food("火星食物")
        self.assertFalse(result["found"])
        self.assertIn("尚未收錄", result["advice"])

    def test_protein_foods_low_gi(self):
        """Protein-rich foods should be low-GI."""
        result = classify_food("豆腐")
        self.assertTrue(result["found"])
        self.assertEqual(result["tier"], "low")
        self.assertLess(result["gi"], 20)

    def test_legumes_low_gi(self):
        result = classify_food("黃豆")
        self.assertTrue(result["found"])
        self.assertEqual(result["tier"], "low")

    def test_desserts_medium_to_high(self):
        result = classify_food("甜甜圈")
        self.assertTrue(result["found"])
        self.assertEqual(result["tier"], "high")

    def test_uses_tw_fda_proxy_when_static_db_misses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DBManager(Path(tmpdir) / "healthfit.db", fast_mode=True)
            db.initialize()
            db.execute(
                """
                INSERT INTO food_nutrition_cache (
                    source, food_id, food_name, category,
                    calories_100g, protein_100g, carb_100g, fat_100g, fiber_100g
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("TW_FDA", "tw-fried-chicken", "炸雞排", "肉類", 290, 22, 3, 18, 0),
            )

            result = classify_food("炸雞排", db=db)

        self.assertTrue(result["found"])
        self.assertEqual(result["source"], "nutrition_proxy")
        self.assertEqual(result["tier"], "low")
        self.assertEqual(result["matched_food"], "炸雞排")
        self.assertGreaterEqual(result["confidence"], 0.55)

    def test_uses_llm_estimator_and_caches_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DBManager(Path(tmpdir) / "healthfit.db", fast_mode=True)
            db.initialize()
            calls: list[str] = []

            def estimator(food_name: str) -> dict:
                calls.append(food_name)
                return {
                    "gi": 62,
                    "tier": "medium",
                    "confidence": 0.72,
                    "rationale": "以主要澱粉來源判定為中 GI。",
                }

            first = classify_food("鹹水雞", db=db, llm_estimator=estimator)
            second = classify_food("鹹水雞", db=db, llm_estimator=estimator)

        self.assertTrue(first["found"])
        self.assertEqual(first["source"], "llm_estimate")
        self.assertEqual(first["tier"], "medium")
        self.assertEqual(second["source"], "llm_estimate")
        self.assertEqual(calls, ["鹹水雞"])

    def test_uses_env_llm_bridge_when_configured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DBManager(Path(tmpdir) / "healthfit.db", fast_mode=True)
            db.initialize()
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "gi": 64,
                                "tier": "medium",
                                "confidence": 0.68,
                                "rationale": "炒製且含甜醬，主體碳水偏中 GI。",
                            }, ensure_ascii=False)
                        }
                    }
                ]
            }

            class FakeHTTPResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

            with mock.patch.dict(
                GI_MODULE.os.environ,
                {
                    "HEALTHFIT_GI_MODEL": "gpt-4.1-mini",
                    "HEALTHFIT_GI_API_KEY": "test-key",
                    "HEALTHFIT_GI_API_URL": "https://example.test/v1/chat/completions",
                },
                clear=False,
            ), mock.patch.object(
                GI_MODULE.urllib_request,
                "urlopen",
                return_value=FakeHTTPResponse(),
            ) as mock_urlopen:
                first = classify_food("炒麵麵包", db=db)
                second = classify_food("炒麵麵包", db=db)

        self.assertTrue(first["found"])
        self.assertEqual(first["source"], "llm_estimate")
        self.assertEqual(first["tier"], "medium")
        self.assertEqual(second["source"], "llm_estimate")
        self.assertEqual(mock_urlopen.call_count, 1)

    def test_cli_no_llm_disables_env_bridge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DBManager(Path(tmpdir) / "healthfit.db", fast_mode=True)
            db.initialize()
            args = type("Args", (), {
                "food": "鹹水雞",
                "json": False,
                "db_path": str(Path(tmpdir) / "healthfit.db"),
                "use_db": True,
                "disable_llm": True,
            })()

            with mock.patch.dict(
                GI_MODULE.os.environ,
                {
                    "HEALTHFIT_GI_MODEL": "gpt-4.1-mini",
                    "HEALTHFIT_GI_API_KEY": "test-key",
                },
                clear=False,
            ), mock.patch.object(GI_MODULE.urllib_request, "urlopen") as mock_urlopen, mock.patch(
                "sys.stdout",
                new_callable=io.StringIO,
            ) as fake_stdout:
                GI_MODULE.cmd_classify(args)

        self.assertIn("尚未收錄", fake_stdout.getvalue())
        mock_urlopen.assert_not_called()


class TestRecommendSwap(unittest.TestCase):
    """Tests for GI swap recommendations."""

    def test_white_rice_swap(self):
        result = recommend_swap("白米飯")
        self.assertIn("糙米飯", result)

    def test_white_bread_swap(self):
        result = recommend_swap("白麵包")
        self.assertIn("全麥麵包", result)

    def test_already_low_gi(self):
        result = recommend_swap("豆腐")
        self.assertIn("已是低GI", result)

    def test_unknown_food_swap(self):
        result = recommend_swap("外星食物")
        self.assertIn("尚未有精確", result)


class TestMealStrategy(unittest.TestCase):
    """Tests for meal-phase GI strategies."""

    def test_breakfast_strategy(self):
        result = get_meal_strategy("早餐")
        self.assertIn("早餐低GI策略", result)
        self.assertIn("蛋白質優先", result)

    def test_lunch_strategy(self):
        result = get_meal_strategy("午餐")
        self.assertIn("進食順序", result)
        self.assertIn("糙米飯", result)

    def test_dinner_strategy(self):
        result = get_meal_strategy("晚餐")
        self.assertIn("碳水減量", result)

    def test_snack_strategy(self):
        result = get_meal_strategy("點心")
        self.assertIn("堅果", result)

    def test_pre_workout_strategy(self):
        result = get_meal_strategy("運動前")
        self.assertIn("中低GI碳水", result)

    def test_post_workout_strategy(self):
        result = get_meal_strategy("運動後")
        self.assertIn("代謝窗口期", result)
        self.assertIn("高GI碳水", result)

    def test_unknown_meal_gets_default(self):
        result = get_meal_strategy("下午茶")
        self.assertIn("通用低GI進食策略", result)


class TestGetFoodListByTier(unittest.TestCase):
    """Tests for tier-based food listing."""

    def test_high_gi_has_entries(self):
        foods = get_food_list_by_tier("high")
        self.assertGreater(len(foods), 0)
        for f in foods:
            self.assertGreaterEqual(f["gi"], GI_HIGH)

    def test_low_gi_has_entries(self):
        foods = get_food_list_by_tier("low")
        self.assertGreater(len(foods), 0)
        for f in foods:
            self.assertLessEqual(f["gi"], GI_LOW)

    def test_medium_gi_has_entries(self):
        foods = get_food_list_by_tier("medium")
        self.assertGreater(len(foods), 0)
        for f in foods:
            self.assertGreater(f["gi"], GI_LOW)
            self.assertLess(f["gi"], GI_HIGH)

    def test_all_tiers_have_foods(self):
        for tier in ["low", "medium", "high"]:
            foods = get_food_list_by_tier(tier)
            self.assertGreater(len(foods), 0, f"Tier {tier} should have foods")


class TestGIValuesConsistency(unittest.TestCase):
    """Validation tests for GI value consistency."""

    def test_all_tiers_are_valid(self):
        from scripts.gi_guide import _FOOD_GI_DB
        valid_tiers = {"low", "medium", "high"}
        for name, info in _FOOD_GI_DB.items():
            self.assertIn(info["tier"], valid_tiers,
                          f"{name} has invalid tier: {info['tier']}")

    def test_gi_thresholds_consistent(self):
        """Verify GI values match their tier thresholds."""
        from scripts.gi_guide import _FOOD_GI_DB
        for name, info in _FOOD_GI_DB.items():
            gi = info["gi"]
            tier = info["tier"]
            if tier == "low":
                self.assertLessEqual(gi, GI_LOW,
                                     f"{name}: GI={gi} but tier=low")
            elif tier == "medium":
                self.assertGreater(gi, GI_LOW, f"{name}: GI={gi} but tier=medium")
                self.assertLess(gi, GI_HIGH, f"{name}: GI={gi} but tier=medium")
            elif tier == "high":
                self.assertGreaterEqual(gi, GI_HIGH, f"{name}: GI={gi} but tier=high")

    def test_swap_foods_exist_in_db(self):
        """Verify that foods mentioned in swap suggestions exist in the GI DB."""
        for food in _GI_SWAPS:
            self.assertIn(food, _FOOD_GI_DB,
                          f"Swap source '{food}' not in GI database")

    def test_strategy_keys_are_valid(self):
        """Verify strategy keys cover common meal types."""
        expected_keys = {"早餐", "午餐", "晚餐", "點心", "運動前", "運動後"}
        self.assertTrue(expected_keys.issubset(set(_PHASE_STRATEGIES.keys())))


if __name__ == "__main__":
    unittest.main()
