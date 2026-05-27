#!/usr/bin/env python3
"""Tests for menu_image_analyzer.py — Feature F-2: 菜單照片 → MenuItem list."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pytest

from menu_image_analyzer import parse_menu_items_from_llm_json


class TestParseMenuItemsFromLlmJson:
    def test_basic(self):
        raw = """
        {
            "restaurant_type": "breakfast_shop",
            "items": [
                {"name": "鮪魚蛋吐司", "price": 55, "category": "吐司"},
                {"name": "奶茶", "price": 25, "category": "飲料"}
            ]
        }
        """
        scene, items = parse_menu_items_from_llm_json(raw)

        assert scene == "breakfast_shop"
        assert len(items) == 2
        assert items[0].name == "鮪魚蛋吐司"
        assert items[0].price == 55
        assert items[0].category == "吐司"
        assert items[0].source == "menu_image"
        assert items[0].confidence == 0.65
        assert items[1].name == "奶茶"
        assert items[1].price == 25

    def test_null_restaurant_type(self):
        raw = '{"restaurant_type": null, "items": [{"name": "鍋貼", "price": 8}]}'
        scene, items = parse_menu_items_from_llm_json(raw)

        assert scene is None
        assert len(items) == 1
        assert items[0].name == "鍋貼"

    def test_missing_items_key(self):
        raw = '{"restaurant_type": "noodle_shop"}'
        scene, items = parse_menu_items_from_llm_json(raw)

        assert scene == "noodle_shop"
        assert items == []

    def test_skips_items_without_name(self):
        raw = """
        {
            "restaurant_type": "bento_shop",
            "items": [
                {"name": "排骨便當", "price": 90, "category": "便當"},
                {"name": "", "price": 10},
                {"category": "湯品"},
                {"name": "味噌湯", "price": 20, "category": "湯"}
            ]
        }
        """
        scene, items = parse_menu_items_from_llm_json(raw)

        assert len(items) == 2
        assert items[0].name == "排骨便當"
        assert items[1].name == "味噌湯"

    def test_price_coercion(self):
        raw = """
        {
            "items": [
                {"name": "a", "price": "55"},
                {"name": "b", "price": null},
                {"name": "c"}
            ]
        }
        """
        _, items = parse_menu_items_from_llm_json(raw)

        assert items[0].price == 55
        assert items[1].price is None
        assert items[2].price is None

    def test_description_field(self):
        raw = '''
        {
            "items": [
                {"name": "牛肉麵", "description": "紅燒口味，含牛肉片"}
            ]
        }
        '''
        _, items = parse_menu_items_from_llm_json(raw)

        assert items[0].description == "紅燒口味，含牛肉片"