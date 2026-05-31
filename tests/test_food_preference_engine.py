#!/usr/bin/env python3
"""Tests for food_preference_engine.py — Food Fingerprint / Preference Learning."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db_manager import DBManager
from food_preference_engine import (
    get_food_fingerprint,
    get_preference_prompt_context,
    mark_food_preference,
    update_preference_after_log,
)


class FoodPreferenceTestCase(unittest.TestCase):
    """Tests that require a real (but temporary) SQLite database."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)
        self.db = DBManager(self.db_path, fast_mode=True)
        self.db.initialize()

        self.user_id = "test-fp-user"
        self.db.upsert_user_profile({
            "user_id": self.user_id,
            "display_name": "FP Test",
            "gender": "M",
            "age": 30,
            "height_cm": 175,
        })

    def tearDown(self) -> None:
        self.db_path.unlink(missing_ok=True)

    # ── helpers ───────────────────────────────────────────────────────────

    def _insert_log(self, food_name: str, log_date: str, score: int | None = None) -> None:
        """Insert a food_log row and a matching daily_summary row."""
        import uuid as _uuid

        log_id = str(_uuid.uuid4())
        self.db.execute(
            """INSERT INTO food_logs
               (log_id, user_id, meal_type, log_datetime, food_name,
                calories, protein_g, carb_g, fat_g)
               VALUES (?, ?, 'lunch', ?, ?, 0, 0, 0, 0)""",
            (log_id, self.user_id, f"{log_date}T12:00:00", food_name),
        )
        if score is not None:
            # upsert daily_summary with the given score
            existing = self.db.fetch_one(
                "SELECT summary_id FROM daily_summaries WHERE user_id=? AND summary_date=?",
                (self.user_id, log_date),
            )
            if existing:
                self.db.execute(
                    "UPDATE daily_summaries SET daily_score=? WHERE summary_id=?",
                    (score, existing["summary_id"]),
                )
            else:
                summary_id = str(_uuid.uuid4())
                self.db.execute(
                    """INSERT INTO daily_summaries
                       (summary_id, user_id, summary_date, total_calories,
                        daily_score)
                       VALUES (?, ?, ?, 0, ?)""",
                    (summary_id, self.user_id, log_date, score),
                )

    def _count_profile_rows(self) -> int:
        rows = self.db.fetchall(
            "SELECT COUNT(*) AS cnt FROM food_preference_profile WHERE user_id=?",
            (self.user_id,),
        )
        return int(rows[0]["cnt"]) if rows else 0

    def _get_profile_row(self, food_name: str) -> dict | None:
        rows = self.db.fetchall(
            "SELECT * FROM food_preference_profile WHERE user_id=? AND food_name=?",
            (self.user_id, food_name),
        )
        return rows[0] if rows else None

    # ── tests ─────────────────────────────────────────────────────────────

    def test_update_increments_total_count(self) -> None:
        """update_preference_after_log increments total_count on repeated calls."""
        today = date.today().isoformat()
        update_preference_after_log(self.db, self.user_id, "雞胸肉", today)
        row1 = self._get_profile_row("雞胸肉")
        self.assertIsNotNone(row1)
        self.assertEqual(row1["total_count"], 1)

        update_preference_after_log(self.db, self.user_id, "雞胸肉", today)
        row2 = self._get_profile_row("雞胸肉")
        self.assertEqual(row2["total_count"], 2)

    def test_high_score_day_raises_avg_score_when_eaten(self) -> None:
        """A high-scoring day raises the average score."""
        # Eat chicken on a 85-score day
        self._insert_log("雞胸肉", "2026-05-01", score=85)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-01")

        # Eat chicken again on a 90-score day
        self._insert_log("雞胸肉", "2026-05-02", score=90)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-02")

        row = self._get_profile_row("雞胸肉")
        self.assertIsNotNone(row)
        avg = row["avg_daily_score_when_eaten"]
        self.assertIsNotNone(avg)
        # Should be roughly (85 + 90) / 2 = 87.5
        self.assertAlmostEqual(avg, 87.5, delta=0.5)

    def test_low_score_day_lowers_avg_score_when_eaten(self) -> None:
        """A low-scoring day when the food is eaten lowers the average."""
        self._insert_log("炸雞", "2026-05-01", score=80)
        update_preference_after_log(self.db, self.user_id, "炸雞", "2026-05-01")
        self._insert_log("炸雞", "2026-05-02", score=40)
        update_preference_after_log(self.db, self.user_id, "炸雞", "2026-05-02")

        row = self._get_profile_row("炸雞")
        avg = row["avg_daily_score_when_eaten"]
        self.assertIsNotNone(avg)
        # (80 + 40) / 2 = 60
        self.assertAlmostEqual(avg, 60, delta=1)

    def test_fingerprint_classifies_favorites_correctly(self) -> None:
        """Foods with high count + high score appear in favorites."""
        self._insert_log("雞胸肉", "2026-05-01", score=85)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-01")
        self._insert_log("雞胸肉", "2026-05-02", score=90)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-02")
        self._insert_log("雞胸肉", "2026-05-03", score=88)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-03")

        fp = get_food_fingerprint(self.db, self.user_id)
        self.assertIn("雞胸肉", fp["favorites"])

    def test_fingerprint_classifies_problematic_correctly(self) -> None:
        """Foods with high count + low score appear in problematic."""
        # Need >=3 records for problematic classification
        for day in range(1, 5):
            d = f"2026-05-{day:02d}"
            self._insert_log("珍珠奶茶", d, score=35)
            update_preference_after_log(self.db, self.user_id, "珍珠奶茶", d)

        fp = get_food_fingerprint(self.db, self.user_id)
        self.assertIn("珍珠奶茶", fp["problematic"])

    def test_mark_avoid_excludes_from_favorites(self) -> None:
        """Setting never_suggest removes the food from favorites."""
        self._insert_log("雞胸肉", "2026-05-01", score=85)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-01")
        self._insert_log("雞胸肉", "2026-05-02", score=90)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-02")
        self._insert_log("雞胸肉", "2026-05-03", score=88)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-03")

        mark_food_preference(self.db, self.user_id, "雞胸肉", "avoid")

        fp = get_food_fingerprint(self.db, self.user_id)
        self.assertNotIn("雞胸肉", fp.get("favorites", []))
        self.assertIn("雞胸肉", fp.get("avoid", []))

    def test_mark_always_adds_to_preferred(self) -> None:
        """Setting always_suggest adds the food to preferred."""
        self._insert_log("雞胸肉", "2026-05-01", score=85)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-01")

        mark_food_preference(self.db, self.user_id, "雞胸肉", "always")

        fp = get_food_fingerprint(self.db, self.user_id)
        self.assertIn("雞胸肉", fp.get("preferred", []))

    def test_preference_prompt_context_contains_avoid(self) -> None:
        """get_preference_prompt_context includes avoid foods in its output."""
        # Insert chicken as a normal food
        self._insert_log("雞胸肉", "2026-05-01", score=85)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-01")
        self._insert_log("雞胸肉", "2026-05-02", score=90)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-02")
        self._insert_log("雞胸肉", "2026-05-03", score=88)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-03")

        mark_food_preference(self.db, self.user_id, "珍珠奶茶", "avoid")

        ctx = get_preference_prompt_context(self.db, self.user_id)
        # Should include favorites section
        self.assertIn("雞胸肉", ctx)
        # Should include avoid section
        self.assertIn("不要推薦", ctx)
        self.assertIn("珍珠奶茶", ctx)

    def test_update_after_log_is_silent_on_empty_db(self) -> None:
        """Calling update_preference_after_log on empty DB must not crash."""
        # No rows exist yet — should silently succeed
        try:
            update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-01")
        except Exception as exc:
            self.fail(f"update_preference_after_log raised {exc} on empty DB")

    def test_get_fingerprint_returns_all_quadrant_keys(self) -> None:
        """get_food_fingerprint returns all 6 expected keys."""
        fp = get_food_fingerprint(self.db, self.user_id)
        expected_keys = {"favorites", "problematic", "exploratory", "avoid", "preferred", "recent_14d"}
        self.assertEqual(set(fp.keys()), expected_keys)

    def test_mark_reset_clears_both_flags(self) -> None:
        """mark_food_preference reset clears never_suggest and always_suggest."""
        self._insert_log("雞胸肉", "2026-05-01", score=85)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-01")

        mark_food_preference(self.db, self.user_id, "雞胸肉", "avoid")
        mark_food_preference(self.db, self.user_id, "雞胸肉", "reset")

        fp = get_food_fingerprint(self.db, self.user_id)
        self.assertNotIn("雞胸肉", fp.get("avoid", []))
        self.assertNotIn("雞胸肉", fp.get("preferred", []))

    def test_prompt_context_returns_empty_string_for_no_data(self) -> None:
        """get_preference_prompt_context returns empty string when no data."""
        ctx = get_preference_prompt_context(self.db, self.user_id)
        self.assertEqual(ctx, "")

    def test_recent_14d_includes_logged_foods(self) -> None:
        """Recent 14d list includes foods logged in the last 14 days."""
        recent_date = (date.today() - timedelta(days=2)).isoformat()
        self._insert_log("豆漿", recent_date, score=75)
        update_preference_after_log(self.db, self.user_id, "豆漿", recent_date)

        fp = get_food_fingerprint(self.db, self.user_id)
        self.assertIn("豆漿", fp["recent_14d"])

    def test_food_quality_rolling_average_not_diluted(self) -> None:
        """avg_food_quality_score must not be diluted by repeated same-quality logs."""
        # Pre-seed nutrition so update_preference_after_log has a food_quality to work with
        self.db.execute(
            """INSERT INTO food_nutrition_cache
               (source, food_id, food_name, calories_100g, protein_100g,
                carb_100g, fat_100g, fiber_100g, sodium_100g)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("TW_FDA", "tw_chicken", "雞胸肉", 165, 31, 0, 3.6, 0, 74),
        )

        # First log — establishes baseline
        self._insert_log("雞胸肉", "2026-05-01", score=80)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-01")
        first = self.db.fetch_one(
            '''SELECT avg_food_quality_score FROM food_preference_profile WHERE user_id=? AND food_name=?''',
            (self.user_id, "雞胸肉"),
        )
        self.assertIsNotNone(first["avg_food_quality_score"])
        first_score = first["avg_food_quality_score"]

        # Second log — same food_quality, count goes 1→2
        self._insert_log("雞胸肉", "2026-05-02", score=80)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-02")
        second = self.db.fetch_one(
            '''SELECT avg_food_quality_score FROM food_preference_profile WHERE user_id=? AND food_name=?''',
            (self.user_id, "雞胸肉"),
        )
        self.assertIsNotNone(second["avg_food_quality_score"])
        second_score = second["avg_food_quality_score"]

        # Third log — count goes 2→3
        self._insert_log("雞胸肉", "2026-05-03", score=80)
        update_preference_after_log(self.db, self.user_id, "雞胸肉", "2026-05-03")
        third = self.db.fetch_one(
            '''SELECT avg_food_quality_score FROM food_preference_profile WHERE user_id=? AND food_name=?''',
            (self.user_id, "雞胸肉"),
        )
        third_score = third["avg_food_quality_score"]

        # Same quality score repeated → average must not be diluted toward 0
        self.assertAlmostEqual(second_score, first_score, delta=0.1,
            msg="avg should stay stable when same food_quality is logged repeatedly")
        self.assertAlmostEqual(third_score, first_score, delta=0.1,
            msg="avg should still be stable after 3rd log")


if __name__ == "__main__":
    unittest.main()