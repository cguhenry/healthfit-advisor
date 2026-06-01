#!/usr/bin/env python3
"""Tests for notification_scheduler.py check-in helpers."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from scripts.notification_scheduler import (
    _deliver_discord,
    _deliver_line,
    build_checkin_payload,
    build_daily_payload,
)


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

    def test_discord_delivery_requires_webhook(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DISCORD_WEBHOOK_URL"):
                _deliver_discord("hello")

    def test_line_delivery_requires_token_and_target(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "LINE_CHANNEL_ACCESS_TOKEN"):
                _deliver_line("hello")

    def test_build_daily_payload_uses_configured_timezone_for_default_date(self):
        fake_today = date(2026, 6, 2)

        with mock.patch("scripts.notification_scheduler.today_local", return_value=fake_today):
            with mock.patch("scripts.notification_scheduler.run_daily_scoring") as scoring_mock:
                with mock.patch("scripts.notification_scheduler.generate_daily_report", return_value="ok"):
                    payload = build_daily_payload("u1", mock.Mock())

        self.assertEqual(payload["date"], "2026-06-02")
        scoring_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
