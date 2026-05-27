from restaurant_scenarios import get_scenario_template, list_supported_scenes


def test_get_breakfast_shop_template():
    template = get_scenario_template("breakfast_shop")
    assert template.display_name == "早餐店"
    assert "蛋餅" in template.common_items
    assert template.customization_rules


def test_supported_scenes_contains_basic_scenes():
    scenes = list_supported_scenes()
    assert "breakfast_shop" in scenes
    assert "bento_shop" in scenes
    assert "bubble_tea" in scenes