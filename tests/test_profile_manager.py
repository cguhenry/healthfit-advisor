#!/usr/bin/env python3
"""Tests for profile_manager.py"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from profile_manager import DEFAULT_PROFILE_PATH, ProfileManager


class TestProfileManager(unittest.TestCase):
    def test_load_does_not_rewrite_profile_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "profile.json"
            manager = ProfileManager(profile_path)
            manager.bootstrap(
                display_name="Henry",
                gender="M",
                age=30,
                height_cm=170.0,
                current_weight_kg=80.0,
                activity_level="light",
            )

            original = profile_path.read_text(encoding="utf-8")
            profile = manager.load()
            reloaded = profile_path.read_text(encoding="utf-8")

            self.assertEqual(profile.display_name, "Henry")
            self.assertEqual(original, reloaded)

    def test_default_profile_path_constant_is_usable(self):
        manager = ProfileManager(DEFAULT_PROFILE_PATH)
        self.assertEqual(manager.profile_path, DEFAULT_PROFILE_PATH)


if __name__ == "__main__":
    unittest.main()
