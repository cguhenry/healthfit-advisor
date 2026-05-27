from dining_models import MenuItem
from menu_nutrition_estimator import estimate_menu_item_nutrition


def test_estimate_pearl_milk_tea():
    item = estimate_menu_item_nutrition(MenuItem(name="珍珠奶茶"), scene="bubble_tea")
    assert item.estimated_calories is not None
    assert item.estimated_calories >= 400
    assert "sugary_drink" in item.tags
    assert "high_calorie" in item.tags


def test_estimate_unsweetened_tea():
    item = estimate_menu_item_nutrition(MenuItem(name="無糖綠茶"), scene="bubble_tea")
    assert item.estimated_calories == 0
    assert "low_sugar" in item.tags


def test_estimate_chicken_breast():
    item = estimate_menu_item_nutrition(MenuItem(name="烤雞胸"), scene="convenience_store")
    assert item.estimated_protein_g is not None
    assert item.estimated_protein_g >= 25
    assert "high_protein" in item.tags


def test_unknown_food_gets_unknown_tag():
    item = estimate_menu_item_nutrition(MenuItem(name="某種不明食物"), scene="breakfast_shop")
    assert "unknown_nutrition" in item.tags
    assert item.confidence <= 0.45