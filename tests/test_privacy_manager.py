#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from calorie_tracker import log_meal_analysis, upsert_daily_summary
from db_manager import DBManager
from privacy_manager import delete_user_data, export_user_data, preview_user_data


class PrivacyManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "healthfit.db"
        self.export_dir = Path(self.tmp.name) / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.db = DBManager(self.db_path, fast_mode=True)
        self.db.initialize()
        self.user_id = "privacy-test-user"
        self.db.upsert_user_profile(
            {
                "user_id": self.user_id,
                "display_name": "Privacy Test",
                "gender": "F",
                "age": 28,
                "height_cm": 165,
                "ethnicity": "east_asian",
            }
        )
        self.db.execute(
            """INSERT INTO weight_plans (
                plan_id, user_id, start_weight_kg, goal_weight_kg, target_weeks,
                weekly_change_kg, weekly_change_pct, bmr, tdee, activity_level,
                daily_calorie_target, daily_calorie_delta, protein_target_g, carb_target_g, fat_target_g,
                goal_type, warnings, requires_professional_review, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                "plan-1", self.user_id, 70, 65, 12,
                -0.4, -0.6, 1400, 1900, "light",
                1600, -300, 110, 150, 50,
                "loss", "[]", 0,
            ),
        )
        log_meal_analysis(
            self.db,
            self.user_id,
            "lunch",
            [{"name": "白飯", "estimated_g": 180, "calories": 250, "protein_g": 4, "carb_g": 56, "fat_g": 0.5, "confidence": 0.9}],
        )
        upsert_daily_summary(self.db, self.user_id, calorie_target=1600)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_preview_counts_rows(self):
        counts = preview_user_data(self.db, self.user_id)
        self.assertGreaterEqual(counts["users"], 1)
        self.assertGreaterEqual(counts["food_logs"], 1)

    def test_export_user_data_creates_zip_and_manifest(self):
        result = export_user_data(self.db, self.user_id, output_dir=self.export_dir)
        self.assertTrue(Path(result["export_dir"]).exists())
        zip_path = Path(result["zip_path"])
        self.assertTrue(zip_path.exists())
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.endswith("manifest.json") for name in names))
        self.assertTrue(any(name.endswith("users.json") for name in names))

    def test_delete_requires_confirmation(self):
        with self.assertRaises(ValueError):
            delete_user_data(self.db, self.user_id, confirm=False)

    def test_delete_user_data_removes_all_rows(self):
        result = delete_user_data(self.db, self.user_id, confirm=True)
        self.assertGreater(result["total_deleted"], 0)
        counts = preview_user_data(self.db, self.user_id)
        self.assertTrue(all(value == 0 for value in counts.values()))


if __name__ == "__main__":
    unittest.main()
