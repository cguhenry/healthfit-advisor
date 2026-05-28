#!/usr/bin/env python3
"""Tests for dining_advisor.py — P1-1: user-id + manual context without active plan."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DINING_ADVISOR = ROOT / "scripts" / "dining_advisor.py"


class TestDiningAdvisorManualContext(unittest.TestCase):
    """P1-1: --user-id + --remaining-calories must work without active plan."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.db_path.unlink(missing_ok=True)

    def test_user_id_manual_remaining_without_plan_succeeds(self):
        """--user-id u1 --remaining-calories 500 must not fail due to missing plan.

        Even if u1 has no active weight plan, providing --remaining-calories
        should let the CLI proceed using manual context.
        """
        # Set up minimal DB with user profile but NO weight plan
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        from db_manager import DBManager

        db = DBManager(self.db_path, fast_mode=True)
        db.initialize()
        db.upsert_user_profile({
            "user_id": "u1",
            "display_name": "Test User",
            "gender": "M",
            "age": 30,
            "height_cm": 175,
        })
        # Explicitly do NOT create a weight_plan — u1 has no active plan

        result = subprocess.run(
            [
                sys.executable, str(DINING_ADVISOR),
                "--user-id", "u1",
                "--scene", "bubble_tea",
                "--remaining-calories", "500",
                "--protein-gap", "25",
                "--goal-type", "loss",
            ],
            capture_output=True,
            text=True,
            env={
                **subprocess.os.environ,
                "HEALTHFIT_DB": str(self.db_path),
                "PYTHONPATH": str(ROOT / "scripts"),
            },
        )

        # Must not error out due to missing active plan
        self.assertNotIn("RuntimeError", result.stderr, "Should not raise RuntimeError for missing plan")
        self.assertNotIn("沒有 active weight plan", result.stderr,
                         "Should not fail when --remaining-calories provided")
        self.assertEqual(result.returncode, 0,
                         f"CLI should succeed. stderr: {result.stderr[:500]}")