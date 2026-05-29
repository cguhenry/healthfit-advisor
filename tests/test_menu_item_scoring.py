#!/usr/bin/env python3
"""Tests for menu_item_scoring.py — scoring logic and reason deduplication."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dining_models import MenuItem, GoalType
from menu_item_scoring import score_menu_item


class TestLossBonusDeduplication(unittest.TestCase):
    """P0-1: Verify the loss+500 bonus fires exactly once (no duplicate score/reason)."""

    def test_loss_500_bonus_scores_once(self) -> None:
        item = MenuItem(
            name="測試食物",
            estimated_calories=400,
            estimated_protein_g=20,
            estimated_carb_g=30,
            estimated_fat_g=10,
        )
        result = score_menu_item(
            item,
            calories_remaining=600,
            protein_gap_g=20,
            goal_type="loss",
        )
        # Base 50 + 20 (under calorie limit) + 15 (protein >= 20g) + 8 (loss+500) = 93
        self.assertAlmostEqual(result.score, 93.0, places=1)

    def test_loss_500_reason_not_duplicated(self) -> None:
        item = MenuItem(
            name="測試食物",
            estimated_calories=400,
            estimated_protein_g=20,
            estimated_carb_g=30,
            estimated_fat_g=10,
        )
        result = score_menu_item(
            item,
            calories_remaining=600,
            protein_gap_g=20,
            goal_type="loss",
        )
        # dict.fromkeys preserves order — count how many times reason appears
        deduped = list(dict.fromkeys(result.reasons))
        self.assertEqual(result.reasons, deduped, "Reasons should not contain duplicates")
        loss_reason_count = sum(1 for r in result.reasons if "減脂期熱量控制" in r)
        self.assertEqual(loss_reason_count, 1, "Loss bonus reason should appear exactly once")


if __name__ == "__main__":
    unittest.main()