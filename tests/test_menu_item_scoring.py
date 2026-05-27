from dining_models import MenuItem
from menu_item_scoring import score_menu_item


def test_score_rewards_high_protein_food():
    item = MenuItem(
        name="烤雞胸",
        estimated_calories=180,
        estimated_protein_g=30,
        tags=["high_protein", "low_fat"],
    )
    scored = score_menu_item(
        item,
        calories_remaining=500,
        protein_gap_g=30,
        goal_type="loss",
    )
    assert scored.score >= 80
    assert any("蛋白質" in reason for reason in scored.reasons)


def test_score_penalizes_sugary_drink_when_calories_low():
    item = MenuItem(
        name="珍珠奶茶",
        estimated_calories=550,
        estimated_protein_g=8,
        tags=["sugary_drink", "high_calorie"],
    )
    scored = score_menu_item(
        item,
        calories_remaining=300,
        protein_gap_g=30,
        goal_type="loss",
    )
    assert scored.score < 50
    assert scored.modifications


def test_low_gi_penalizes_sugary_drink():
    item = MenuItem(
        name="珍珠奶茶",
        estimated_calories=550,
        estimated_protein_g=8,
        tags=["sugary_drink", "high_calorie"],
    )
    scored = score_menu_item(
        item,
        calories_remaining=800,
        protein_gap_g=0,
        goal_type="maintain",
        require_low_gi=True,
    )
    assert scored.score < 60
    assert any("無糖" in m for m in scored.modifications)