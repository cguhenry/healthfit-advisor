#!/usr/bin/env python3
"""Smoke tests for the new component-based menu_item_scoring system."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is on the path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from dining_models import MenuItem
from menu_item_scoring import score_menu_item


def test_healthy_items_do_not_all_saturate_at_100():
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

    print(f"Scores: {dict(zip([i.name for i in items], scores))}")
    assert len(set(scores)) > 1,   "Items should not all score identically"
    assert all(score < 100 for score in scores), f"No score should be 100, got {scores}"
    print("PASS: test_healthy_items_do_not_all_saturate_at_100")


def test_sugary_drink_scores_low_for_low_gi_loss():
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

    print(f"Pearl milk tea score: {scored.score}, mods: {scored.modifications}")
    assert scored.score < 50, f"Score should be < 50, got {scored.score}"
    assert scored.modifications, "Should have modifications"
    print("PASS: test_sugary_drink_scores_low_for_low_gi_loss")


def test_high_protein_reasonable_calorie_food_scores_high():
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

    print(f"Chicken breast bento score: {scored.score}")
    assert 75 <= scored.score < 100, f"Score should be 75–99, got {scored.score}"
    print("PASS: test_high_protein_reasonable_calorie_food_scores_high")


def test_high_calorie_food_over_budget_scores_lower():
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

    print(f"Fried chicken bento score: {scored.score}, mods: {scored.modifications}")
    assert scored.score < 65, f"Score should be < 65, got {scored.score}"
    assert any("減少份量" in m or "改選" in m or "改小" in m or "不建議" in m for m in scored.modifications), \
        f"Should suggest smaller portion, got {scored.modifications}"
    print("PASS: test_high_calorie_food_over_budget_scores_lower")


def test_bubble_tea_scenario():
    """Verify bubble tea scene ranking with new scoring."""
    items = [
        MenuItem(name="無糖綠茶", estimated_calories=5, estimated_protein_g=0,
                 tags=["low_calorie"], confidence=0.8),
        MenuItem(name="無糖鮮奶茶去珍珠", estimated_calories=120,
                 estimated_protein_g=6, tags=["low_sugar"], confidence=0.6),
        MenuItem(name="珍珠奶茶", estimated_calories=550, estimated_protein_g=8,
                 tags=["sugary_drink", "high_calorie"], confidence=0.6),
        MenuItem(name="奶蓋紅茶", estimated_calories=380, estimated_protein_g=5,
                 tags=["sugary_drink", "high_fat"], confidence=0.5),
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

    sorted_scored = sorted(scored, key=lambda x: -x.score)
    for s in sorted_scored:
        print(f"  {s.item.name}: {s.score}  reasons={s.reasons[:2]}")

    assert sorted_scored[0].item.name == "無糖綠茶", "Unsweetened tea should rank first"
    assert sorted_scored[2].score < 50, "Pearl milk tea should score < 50"
    assert sorted_scored[3].score < 50, "Milk tea should score < 50"
    print("PASS: test_bubble_tea_scenario")


if __name__ == "__main__":
    test_healthy_items_do_not_all_saturate_at_100()
    test_sugary_drink_scores_low_for_low_gi_loss()
    test_high_protein_reasonable_calorie_food_scores_high()
    test_high_calorie_food_over_budget_scores_lower()
    test_bubble_tea_scenario()
    print("\n✅ All tests passed.")