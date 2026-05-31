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

    def test_loss_500_bonus_reason_once_under_component_scoring(self) -> None:
        """Under the component scoring system, loss bonus reason fires exactly once."""
        item = MenuItem(
            name="測試食物",
            estimated_calories=400,
            estimated_protein_g=20,
            estimated_carb_g=30,
            estimated_fat_g=10,
            confidence=0.6,
        )
        result = score_menu_item(
            item,
            calories_remaining=600,
            protein_gap_g=20,
            goal_type="loss",
        )
        loss_reason_count = sum(
            1 for r in result.reasons if "減脂期熱量控制" in r
        )
        self.assertEqual(loss_reason_count, 1)
        self.assertGreaterEqual(result.score, 50)
        self.assertLess(result.score, 100)
        # Deduplication is already guaranteed by list(dict.fromkeys(...)) in scorer
        deduped = list(dict.fromkeys(result.reasons))
        self.assertEqual(result.reasons, deduped)

    def test_loss_500_reason_not_duplicated(self) -> None:
        """Loss bonus reason should appear exactly once regardless of scoring model."""
        item = MenuItem(
            name="測試食物",
            estimated_calories=400,
            estimated_protein_g=20,
            estimated_carb_g=30,
            estimated_fat_g=10,
            confidence=0.6,
        )
        result = score_menu_item(
            item,
            calories_remaining=600,
            protein_gap_g=20,
            goal_type="loss",
        )
        deduped = list(dict.fromkeys(result.reasons))
        self.assertEqual(result.reasons, deduped, "Reasons should not contain duplicates")
        loss_reason_count = sum(1 for r in result.reasons if "減脂期熱量控制" in r)
        self.assertEqual(loss_reason_count, 1, "Loss bonus reason should appear exactly once")


if __name__ == "__main__":
    unittest.main()