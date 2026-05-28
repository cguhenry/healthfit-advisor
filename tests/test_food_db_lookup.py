#!/usr/bin/env python3
"""Tests for food_db_lookup.py — source priority, USDA searchability, alias expansion."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db_manager import DBManager
from food_db_lookup import FoodDBLookup


class TestUSDAIntegration(unittest.TestCase):
    """Verify USDA rows are searchable and macros are pivoted correctly."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        self.db = DBManager(self.db_path, fast_mode=True)
        self.db.initialize()

    def tearDown(self) -> None:
        self.db_path.unlink(missing_ok=True)

    def test_imported_usda_rows_are_searchable(self):
        """USDA source rows must be found by FoodDBLookup."""
        self.db.execute(
            """INSERT INTO food_nutrition_cache
               (source, food_id, food_name, calories_100g, protein_100g, carb_100g, fat_100g)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("USDA", "fdc_test_1", "Chicken breast", 165, 31, 0, 3.6),
        )
        self.db.execute(
            """INSERT INTO food_nutrition_cache
               (source, food_id, food_name, calories_100g, protein_100g, carb_100g, fat_100g)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("USDA", "fdc_test_2", "Chicken thigh", 209, 26, 0, 11),
        )

        lookup = FoodDBLookup(db=self.db)
        results = lookup.search("Chicken", top=5)

        self.assertTrue(results, "USDA Chicken search should return results")
        self.assertTrue(
            all(r.item.source == "USDA" for r in results),
            "All returned items should have source='USDA'",
        )

    def test_usda_pivot_imports_required_macros(self):
        """A USDA row must have calories, protein, carb, and fat all populated."""
        self.db.execute(
            """INSERT INTO food_nutrition_cache
               (source, food_id, food_name,
                calories_100g, protein_100g, carb_100g, fat_100g,
                fiber_100g, sodium_100g)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("USDA", "fdc_test_3", "Chicken breast",
             165, 31.0, 0.0, 3.6, 0.0, 75.0),
        )

        row = self.db.fetch_one(
            """SELECT * FROM food_nutrition_cache
               WHERE source = ? AND food_name = ?""",
            ("USDA", "Chicken breast"),
        )

        self.assertIsNotNone(row)
        self.assertIsNotNone(row["calories_100g"])
        self.assertIsNotNone(row["protein_100g"])
        self.assertIsNotNone(row["carb_100g"])
        self.assertIsNotNone(row["fat_100g"])

    def test_usda_foundation_name_not_used(self):
        """Imported source must be 'USDA', never 'USDA_FOUNDATION'."""
        self.db.execute(
            """INSERT INTO food_nutrition_cache
               (source, food_id, food_name, calories_100g, protein_100g, carb_100g, fat_100g)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("USDA", "fdc_99", "Test food", 100, 10, 5, 2),
        )
        bad = self.db.fetch_one(
            "SELECT source FROM food_nutrition_cache WHERE source = 'USDA_FOUNDATION'"
        )
        self.assertIsNone(bad, "No rows should have source='USDA_FOUNDATION'")


class TestSourcePriority(unittest.TestCase):
    """Source priority: TW_FDA first for Chinese queries, USDA first for English."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        self.db = DBManager(self.db_path, fast_mode=True)
        self.db.initialize()

        # Insert foods with same name from both sources (for Chinese tie test)
        for src, fid, cal, prot in [
            ("TW_FDA", "tw_1", 165, 31),
            ("USDA", "fdc_1", 120, 25),
        ]:
            self.db.execute(
                """INSERT INTO food_nutrition_cache
                   (source, food_id, food_name, calories_100g, protein_100g, carb_100g, fat_100g)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (src, fid, "雞胸肉", cal, prot, 0, 2),
            )

        # Insert English-named foods from both sources (for English tie test)
        for src, fid, cal, prot in [
            ("TW_FDA", "tw_en", 97, 20),
            ("USDA", "fdc_en", 104, 22),
        ]:
            self.db.execute(
                """INSERT INTO food_nutrition_cache
                   (source, food_id, food_name, calories_100g, protein_100g, carb_100g, fat_100g)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (src, fid, "Chicken breast", cal, prot, 0, 1),
            )

    def tearDown(self) -> None:
        self.db_path.unlink(missing_ok=True)

    def test_chinese_query_prefers_tw_fda_when_scores_tie(self):
        """Chinese query → first result should be TW_FDA."""
        lookup = FoodDBLookup(db=self.db)
        results = lookup.search("雞胸肉", top=2)

        self.assertTrue(results)
        self.assertEqual(
            results[0].item.source, "TW_FDA",
            "Chinese query should rank TW_FDA first",
        )

    def test_english_query_prefers_usda_when_scores_tie(self):
        """English-like query → first result should be USDA."""
        lookup = FoodDBLookup(db=self.db)
        results = lookup.search("chicken breast", top=2)

        self.assertTrue(results)
        self.assertEqual(
            results[0].item.source, "USDA",
            "English query should rank USDA first",
        )

    def test_alias_query_fetches_expanded_candidate(self):
        """Alias expansion must participate in SQL candidate fetch, not just scoring.

        If DB has '白飯' but user queries '白米飯', the alias '白米飯' → '白飯'
        must cause '白飯' to be fetched as a candidate before scoring.
        """
        self.db.execute(
            """INSERT INTO food_nutrition_cache
               (source, food_id, food_name, calories_100g, protein_100g, carb_100g, fat_100g)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("TW_FDA", "tw_rice", "白飯", 130, 2.4, 28, 0.3),
        )

        lookup = FoodDBLookup(db=self.db)
        results = lookup.search("白米飯")

        self.assertTrue(results, "Alias '白米飯' should find '白飯' via expansion")
        self.assertEqual(results[0].item.food_name, "白飯")


    def test_food_db_lookup_parses_raw_json(self) -> None:
        """raw_json column is parsed from JSON string to dict, not left as raw string."""
        self.db.execute(
            """INSERT INTO food_nutrition_cache
               (source, food_id, food_name, calories_100g, protein_100g,
                carb_100g, fat_100g, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("USDA", "fdc_raw", "Raw JSON Test Food", 100, 10, 5, 2,
             '{"fdc_id": 123, "extra": "value"}'),
        )

        lookup = FoodDBLookup(db=self.db)
        results = lookup.search("Raw JSON Test Food")

        self.assertTrue(results)
        self.assertEqual(results[0].item.raw_json, {"fdc_id": 123, "extra": "value"})


if __name__ == "__main__":
    unittest.main()