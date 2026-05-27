from dining_context_engine import (
    recommend_without_menu,
    recommend_from_menu_items,
)
from dining_models import MenuItem


def test_recommend_without_menu_returns_items():
    result = recommend_without_menu(
        scene="breakfast_shop",
        calories_remaining=500,
        protein_gap_g=25,
    )

    assert result.source_mode == "scenario_template"
    assert result.recommended
    assert result.avoid
    assert result.general_modifications
    assert "推估" in result.summary


def test_bubble_tea_recommends_unsweetened_drinks():
    result = recommend_without_menu(
        scene="bubble_tea",
        calories_remaining=300,
        protein_gap_g=0,
        require_low_gi=True,
    )

    names = [x.item.name for x in result.recommended]
    assert any("無糖" in name for name in names)


def test_recommend_from_menu_items_uses_actual_items():
    items = [
        MenuItem(name="珍珠奶茶", source="menu_image"),
        MenuItem(name="無糖綠茶", source="menu_image"),
        MenuItem(name="鮪魚蛋吐司", source="menu_image"),
    ]

    result = recommend_from_menu_items(
        items=items,
        scene="breakfast_shop",
        calories_remaining=500,
        protein_gap_g=20,
    )

    assert result.source_mode == "menu_image"
    assert result.recommended
    recommended_names = [x.item.name for x in result.recommended]
    assert "無糖綠茶" in recommended_names or "鮪魚蛋吐司" in recommended_names