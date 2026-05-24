#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from food_db_cache import COLD_TTL_SECONDS, HOT_TTL_SECONDS, FoodDBCache, TTLMemoryCache


@dataclass
class DummyItem:
    food_name: str
    source: str = "TW_FDA"
    food_id: str = "demo-1"


@dataclass
class DummyResult:
    item: DummyItem
    match_score: float
    matched_on: str = "name"


class FakeLookup:
    def __init__(self) -> None:
        self.search_calls = 0
        self.lookup_calls = 0

    def search(self, query, *, top=5, sources=None, category=None, min_score=0.30):
        self.search_calls += 1
        if query == "白飯":
            return [DummyResult(DummyItem("白飯"), 0.95)]
        return []

    def lookup(self, source, food_id):
        self.lookup_calls += 1
        if food_id == "known":
            return DummyItem("雞胸肉", source=source, food_id=food_id)
        return None


class FoodDBCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_000_000.0
        self.lookup = FakeLookup()
        self.cache = TTLMemoryCache(time_fn=lambda: self.now)
        self.service = FoodDBCache(lookup_engine=self.lookup, cache=self.cache)

    def test_search_uses_cache(self):
        first = self.service.search("白飯")
        second = self.service.search("白飯")
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(self.lookup.search_calls, 1)
        self.assertEqual(self.service.stats()["hits"], 1)

    def test_hot_search_expires_after_one_hour(self):
        self.service.search("白飯")
        key = next(iter(self.cache._entries))
        self.assertEqual(self.cache._entries[key].ttl_seconds, HOT_TTL_SECONDS)
        self.now += HOT_TTL_SECONDS + 1
        self.service.search("白飯")
        self.assertEqual(self.lookup.search_calls, 2)

    def test_empty_search_uses_cold_ttl(self):
        self.service.search("不存在")
        key = next(iter(self.cache._entries))
        self.assertEqual(self.cache._entries[key].ttl_seconds, COLD_TTL_SECONDS)

    def test_lookup_by_id_uses_cold_ttl(self):
        item = self.service.lookup_by_id("TW_FDA", "known")
        self.assertIsNotNone(item)
        key = next(iter(self.cache._entries))
        self.assertEqual(self.cache._entries[key].ttl_seconds, COLD_TTL_SECONDS)
        self.service.lookup_by_id("TW_FDA", "known")
        self.assertEqual(self.lookup.lookup_calls, 1)

    def test_invalidate_search_removes_entry(self):
        self.service.search("白飯")
        removed = self.service.invalidate_search("白飯")
        self.assertTrue(removed)
        self.assertEqual(self.service.stats()["size"], 0)


if __name__ == "__main__":
    unittest.main()
