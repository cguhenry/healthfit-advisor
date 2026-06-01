#!/usr/bin/env python3
"""Tests for notification_scheduler.py check-in helpers."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from scripts import notification_scheduler
from scripts.notification_scheduler import (
    _deliver_discord,
    _deliver_line,
    build_checkin_payload,
    build_daily_payload,
    resolve_discord_delivery_config,
    resolve_line_delivery_config,
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
            with mock.patch("scripts.notification_scheduler.load_openclaw_config", return_value={}):
                with self.assertRaisesRegex(RuntimeError, "DISCORD_WEBHOOK_URL"):
                    _deliver_discord("hello")

    def test_line_delivery_requires_token_and_target(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            notification_scheduler.load_openclaw_config.cache_clear()
            with mock.patch("scripts.notification_scheduler.load_openclaw_config", return_value={}):
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

    def test_main_checkin_help_parses_cleanly(self):
        with mock.patch.object(sys, "argv", ["notification_scheduler.py", "checkin", "--help"]):
            with mock.patch("sys.stdout", new_callable=StringIO):
                with self.assertRaises(SystemExit) as exc:
                    notification_scheduler.main()

        self.assertEqual(exc.exception.code, 0)

    def test_resolve_line_delivery_config_falls_back_to_openclaw(self):
        notification_scheduler.load_openclaw_config.cache_clear()
        fake_cfg = {
            "channels": {
                "line": {
                    "channelAccessToken": "line-token",
                    "allowFrom": ["user-123"],
                }
            }
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("scripts.notification_scheduler.load_openclaw_config", return_value=fake_cfg):
                token, target = resolve_line_delivery_config()

        self.assertEqual(token, "line-token")
        self.assertEqual(target, "user-123")

    def test_resolve_discord_delivery_config_falls_back_to_openclaw(self):
        notification_scheduler.load_openclaw_config.cache_clear()
        fake_cfg = {
            "channels": {
                "discord": {
                    "token": "discord-bot-token",
                    "allowFrom": ["768728802070626334"],
                }
            }
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("scripts.notification_scheduler.load_openclaw_config", return_value=fake_cfg):
                webhook_url, bot_token, target = resolve_discord_delivery_config()

        self.assertIsNone(webhook_url)
        self.assertEqual(bot_token, "discord-bot-token")
        self.assertEqual(target, "768728802070626334")

    def test_discord_delivery_can_use_bot_dm_fallback(self):
        fake_cfg = {
            "channels": {
                "discord": {
                    "token": "discord-bot-token",
                    "allowFrom": ["768728802070626334"],
                }
            }
        }

        dm_response = mock.Mock()
        dm_response.raise_for_status.return_value = None
        dm_response.json.return_value = {"id": "dm-channel-id"}
        msg_response = mock.Mock()
        msg_response.raise_for_status.return_value = None

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("scripts.notification_scheduler.load_openclaw_config", return_value=fake_cfg):
                with mock.patch("requests.post", side_effect=[dm_response, msg_response]) as post_mock:
                    _deliver_discord("hello from healthfit")

        self.assertEqual(post_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
