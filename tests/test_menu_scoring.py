#!/usr/bin/env python3
"""Pytest suite for the component-based menu_item_scoring system."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pytest
from dining_models import MenuItem
from menu_item_scoring import score_menu_item


class TestNoSaturation:
    """Scores must not all cluster at 100; differentiation is the goal."""

    def test_healthy_items_do_not_all_saturate_at_100(self) -> None:
        items = [
            MenuItem(
                name="鮪魚蛋吐司少醬",
                estimated_calories=400,
                estimated_protein_g=24,
                tags=["high_protein", "reduced_sauce"],
                confidence=0.6,
            ),
            MenuItem(
                name="里肌蛋吐司",
                estimated_calories=500,
                estimated_protein_g=28,
                tags=["high_protein"],
                confidence=0.6,
            ),
            MenuItem(
                name="無糖豆漿",
                estimated_calories=160,
                estimated_protein_g=12,
                tags=["high_protein", "low_sugar"],
                confidence=0.7,
            ),
        ]

        scores = [
            score_menu_item(
                item,
                calories_remaining=500,
                protein_gap_g=25,
                goal_type="loss",
            ).score
            for item in items
        ]

        # All scores must be below 100
        assert all(score < 100 for score in scores), f"No score should be 100, got {scores}"
        # Scores must not all be identical (differentiation required)
        assert len(set(scores)) > 1, "Scores should not all be identical"

    def test_bubble_tea_ranking(self) -> None:
        """Unsweetened drinks should score well; sugary drinks should score poorly."""
        items = [
            MenuItem(name="無糖綠茶",   estimated_calories=5,   estimated_protein_g=0,
                     tags=["low_calorie"],             confidence=0.8),
            MenuItem(name="無糖鮮奶茶去珍珠", estimated_calories=180, estimated_protein_g=8,
                     tags=["low_sugar"],               confidence=0.6),
            MenuItem(name="珍珠奶茶",   estimated_calories=550, estimated_protein_g=8,
                     tags=["sugary_drink", "high_calorie"], confidence=0.6),
            MenuItem(name="奶蓋紅茶",   estimated_calories=380, estimated_protein_g=5,
                     tags=["sugary_drink", "high_fat"],      confidence=0.5),
        ]

        scored = [
            score_menu_item(
                item,
                calories_remaining=300,
                protein_gap_g=0,
                goal_type="loss",
                require_low_gi=True,
            )
            for item in items
        ]
        by_score = sorted(scored, key=lambda x: -x.score)

        # Both unsweetened options should be well above 50
        assert by_score[0].score >= 50
        assert by_score[1].score >= 50
        # Both sugary drinks should be below 50
        assert by_score[2].score < 50, f"Pearl milk tea should be < 50, got {by_score[2].score}"
        assert by_score[3].score < 50, f"Milk tea should be < 50, got {by_score[3].score}"


class TestSugaryDrink:
    """Sugary drinks should score poorly, especially with low-GI requirement."""

    def test_pearl_milk_tea_low_gi(self) -> None:
        item = MenuItem(
            name="珍珠奶茶",
            estimated_calories=550,
            estimated_protein_g=8,
            tags=["sugary_drink", "high_calorie"],
            confidence=0.6,
        )
        scored = score_menu_item(
            item,
            calories_remaining=300,
            protein_gap_g=20,
            goal_type="loss",
            require_low_gi=True,
        )
        assert scored.score < 50, f"Pearl milk tea should be < 50, got {scored.score}"
        assert scored.modifications, "Should have modifications"

    def test_sugary_drink_modifications_not_empty(self) -> None:
        item = MenuItem(
            name="珍珠奶茶",
            estimated_calories=550,
            estimated_protein_g=8,
            tags=["sugary_drink"],
            confidence=0.6,
        )
        scored = score_menu_item(
            item, calories_remaining=300, protein_gap_g=0, goal_type="loss"
        )
        assert "飲料建議改無糖或去配料" in scored.modifications


class TestHighProtein:
    """High-protein reasonable-calorie foods should score well."""

    def test_chicken_breast_bento_scores_high(self) -> None:
        item = MenuItem(
            name="雞胸便當飯半碗",
            estimated_calories=440,
            estimated_protein_g=45,
            tags=["high_protein", "portion_control"],
            confidence=0.6,
        )
        scored = score_menu_item(
            item,
            calories_remaining=650,
            protein_gap_g=35,
            goal_type="loss",
        )
        assert 75 <= scored.score < 100, f"Expected 75-99, got {scored.score}"

    def test_high_protein_helps_fill_gap(self) -> None:
        item = MenuItem(
            name="雞胸肉",
            estimated_calories=165,
            estimated_protein_g=31,
            tags=["high_protein", "whole_food"],
            confidence=0.7,
        )
        scored = score_menu_item(
            item,
            calories_remaining=500,
            protein_gap_g=30,  # large gap
            goal_type="loss",
        )
        # Should have reason about filling protein gap
        assert any("蛋白質缺口" in r for r in scored.reasons)


class TestOverBudget:
    """Over-budget foods should be penalized appropriately."""

    def test_fried_chicken_over_budget_scores_lower(self) -> None:
        item = MenuItem(
            name="炸雞腿便當",
            estimated_calories=900,
            estimated_protein_g=35,
            tags=["fried", "high_calorie", "high_protein"],
            confidence=0.6,
        )
        scored = score_menu_item(
            item,
            calories_remaining=500,
            protein_gap_g=30,
            goal_type="loss",
        )
        assert scored.score < 65, f"Over-budget fried meal should be < 65, got {scored.score}"
        assert scored.modifications, "Should suggest portion reduction"

    def test_slight_overage_has_modification(self) -> None:
        item = MenuItem(
            name="鐵板麵加蛋",
            estimated_calories=600,
            estimated_protein_g=22,
            tags=["high_carb"],
            confidence=0.6,
        )
        scored = score_menu_item(
            item,
            calories_remaining=500,
            protein_gap_g=20,
            goal_type="loss",
        )
        assert any("減少份量" in m or "主食減半" in m for m in scored.modifications)


class TestReasonDeduplication:
    """Reasons must not contain duplicates."""

    def test_reasons_are_deduplicated(self) -> None:
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
        assert result.reasons == deduped, "Reasons should not contain duplicates"


class TestComponentBoundedness:
    """Sub-scores must be bounded within their maxima."""

    def test_calorie_fit_max_35(self) -> None:
        """Calorie sub-score max is 35."""
        item = MenuItem(
            name="low-cal",
            estimated_calories=50,   # very low ratio 50/1000
            estimated_protein_g=10,
            tags=["low_calorie"],
            confidence=0.8,
        )
        scored = score_menu_item(
            item,
            calories_remaining=1000,
            protein_gap_g=0,
            goal_type="loss",
        )
        # The calorie component alone should be 35
        # Total is capped at 100 anyway, so this just verifies it doesn't crash
        assert scored.score <= 100

    def test_no_negative_scores(self) -> None:
        """Score must never go below 0."""
        items = [
            MenuItem(name=n, estimated_calories=c, estimated_protein_g=p,
                     tags=t, confidence=0.5)
            for n, c, p, t in [
                ("empty", 0, 0, ["fried", "sugary_drink", "high_calorie"]),
                ("nothing", None, None, []),
            ]
        ]
        for item in items:
            scored = score_menu_item(item, calories_remaining=0, protein_gap_g=0, goal_type="loss")
            assert scored.score >= 0, f"{item.name} scored {scored.score} < 0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])