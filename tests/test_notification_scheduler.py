#!/usr/bin/env python3
"""Tests for notification_scheduler.py check-in helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from scripts.notification_scheduler import build_checkin_payload


class TestNotificationScheduler(unittest.TestCase):
    def test_build_checkin_payload_for_lunch(self):
        payload = build_checkin_payload("u1", "lunch")
        self.assertEqual(payload["meal_type"], "lunch")
        self.assertEqual(payload["prompt_text"], "今天午餐吃了什麼？")
        self.assertEqual(
            payload["next_command"][:8],
            [
                "python3",
                "scripts/healthfit.py",
                "checkin",
                "answer",
                "--user-id",
                "u1",
                "--meal-type",
                "lunch",
            ],
        )


if __name__ == "__main__":
    unittest.main()
