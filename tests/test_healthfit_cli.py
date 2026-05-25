#!/usr/bin/env python3
"""Tests for unified healthfit.py CLI dispatch."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from scripts import healthfit
from db_manager import DBManager


class TestHealthFitCli(unittest.TestCase):
    def test_intake_dispatches_to_intake_flow(self):
        with mock.patch("scripts.healthfit.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            rc = healthfit.dispatch(["intake", "payload.json", "--no-persist"])

        self.assertEqual(rc, 0)
        cmd = run_mock.call_args.args[0]
        self.assertEqual(Path(cmd[1]).name, "intake_flow.py")
        self.assertEqual(cmd[2:], ["payload.json", "--no-persist"])

    def test_log_meal_dispatches_to_calorie_tracker_log(self):
        with mock.patch("scripts.healthfit.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            rc = healthfit.dispatch(["log", "meal", "meal.json", "--user-id", "u1"])

        self.assertEqual(rc, 0)
        cmd = run_mock.call_args.args[0]
        self.assertEqual(Path(cmd[1]).name, "calorie_tracker.py")
        self.assertEqual(cmd[2:], ["log", "meal.json", "--user-id", "u1"])

    def test_report_weekly_dispatches(self):
        with mock.patch("scripts.healthfit.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            rc = healthfit.dispatch(["report", "weekly", "--user-id", "u1"])

        self.assertEqual(rc, 0)
        cmd = run_mock.call_args.args[0]
        self.assertEqual(Path(cmd[1]).name, "report_generator.py")
        self.assertEqual(cmd[2:], ["weekly", "--user-id", "u1"])

    def test_log_from_image_parses_and_persists(self):
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        tmp_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
        json.dump(
            {
                "foods": [
                    {
                        "name": "雞胸肉",
                        "estimated_g": 120,
                        "calories": 198,
                        "protein_g": 36,
                        "carb_g": 0,
                        "fat_g": 4,
                        "confidence": 0.91,
                    }
                ],
                "total_calories": 198,
                "macros": {"protein_g": 36, "carb_g": 0, "fat_g": 4},
                "confidence": 0.91,
                "nutrition_advice": "ok",
            },
            tmp_json,
            ensure_ascii=False,
        )
        tmp_json.close()

        try:
            db = DBManager(Path(tmp_db.name), fast_mode=True)
            db.initialize()
            db.upsert_user_profile(
                {
                    "user_id": "u1",
                    "display_name": "Test",
                    "gender": "M",
                    "age": 30,
                    "height_cm": 175,
                }
            )

            with mock.patch("builtins.print") as print_mock:
                rc = healthfit.dispatch(
                    ["log", "from-image", tmp_json.name, "--user-id", "u1", "--db-path", tmp_db.name]
                )

            self.assertEqual(rc, 0)
            row = db.fetch_one(
                "SELECT COUNT(*) AS count FROM food_logs WHERE user_id = ?",
                ("u1",),
            )
            self.assertEqual(row["count"], 2)
            summary = db.fetch_one(
                "SELECT total_calories FROM daily_summaries WHERE user_id = ?",
                ("u1",),
            )
            self.assertAlmostEqual(summary["total_calories"], 198.0, places=1)
            self.assertTrue(print_mock.called)
        finally:
            os.unlink(tmp_db.name)
            os.unlink(tmp_json.name)

    def test_log_from_image_can_read_stdin_and_save_raw_response(self):
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        tmp_dir = tempfile.mkdtemp()
        raw_path = Path(tmp_dir) / "phase3_response.json"
        raw_payload = {
            "foods": [
                {
                    "name": "地瓜",
                    "estimated_g": 150,
                    "calories": 135,
                    "protein_g": 2,
                    "carb_g": 31,
                    "fat_g": 0.2,
                    "confidence": 0.87,
                }
            ],
            "total_calories": 135,
            "macros": {"protein_g": 2, "carb_g": 31, "fat_g": 0.2},
            "confidence": 0.87,
        }

        try:
            db = DBManager(Path(tmp_db.name), fast_mode=True)
            db.initialize()
            db.upsert_user_profile(
                {
                    "user_id": "u1",
                    "display_name": "Test",
                    "gender": "M",
                    "age": 30,
                    "height_cm": 175,
                }
            )

            with mock.patch("sys.stdin", StringIO(json.dumps(raw_payload, ensure_ascii=False))):
                with mock.patch("builtins.print") as print_mock:
                    rc = healthfit.dispatch(
                        [
                            "log",
                            "from-image",
                            "-",
                            "--user-id",
                            "u1",
                            "--db-path",
                            tmp_db.name,
                            "--save-raw-response",
                            str(raw_path),
                        ]
                    )

            self.assertEqual(rc, 0)
            self.assertTrue(raw_path.exists())
            self.assertEqual(json.loads(raw_path.read_text(encoding="utf-8")), raw_payload)
            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(Path(printed["saved_raw_response"]), raw_path)
        finally:
            os.unlink(tmp_db.name)
            if raw_path.exists():
                raw_path.unlink()
            os.rmdir(tmp_dir)

    def test_image_prompt_builds_next_command(self):
        with mock.patch("builtins.print") as print_mock:
            rc = healthfit.dispatch(
                [
                    "image",
                    "prompt",
                    "--user-id",
                    "u1",
                    "--meal-type",
                    "dinner",
                    "--scenario",
                    "food",
                    "--remaining-calories",
                    "800",
                    "--protein-gap",
                    "30",
                ]
            )

        self.assertEqual(rc, 0)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["scenario"], "food")
        self.assertEqual(payload["meal_type"], "dinner")
        self.assertEqual(payload["phase3_output_file"], str(Path("phase3_response.json").expanduser()))
        self.assertIn("system_prompt", payload)
        self.assertIn("user_prompt", payload)
        self.assertEqual(payload["next_command"][:5], ["python3", "scripts/healthfit.py", "log", "from-image", "phase3_response.json"])

    def test_checkin_prompt_builds_question(self):
        with mock.patch("builtins.print") as print_mock:
            rc = healthfit.dispatch(["checkin", "prompt", "--meal-type", "lunch", "--user-id", "u1"])

        self.assertEqual(rc, 0)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["meal_type"], "lunch")
        self.assertEqual(payload["question"], "今天午餐吃了什麼？")
        self.assertEqual(payload["next_command"][:6], ["python3", "scripts/healthfit.py", "checkin", "answer", "--user-id", "u1"])

    def test_checkin_answer_parses_and_persists_manual_meal(self):
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        try:
            db = DBManager(Path(tmp_db.name), fast_mode=True)
            db.initialize()
            db.upsert_user_profile(
                {
                    "user_id": "u1",
                    "display_name": "Test",
                    "gender": "M",
                    "age": 30,
                    "height_cm": 175,
                }
            )

            with mock.patch("builtins.print") as print_mock:
                rc = healthfit.dispatch(
                    [
                        "checkin",
                        "answer",
                        "--user-id",
                        "u1",
                        "--meal-type",
                        "lunch",
                        "--text",
                        "今天午餐吃了雞胸肉150g、茶葉蛋和無糖豆漿",
                        "--db-path",
                        tmp_db.name,
                    ]
                )

            self.assertEqual(rc, 0)
            payload = json.loads(print_mock.call_args.args[0])
            self.assertEqual(payload["status"], "logged")
            self.assertEqual(payload["logged_rows"], 3)
            row = db.fetch_one(
                "SELECT COUNT(*) AS count FROM food_logs WHERE user_id = ? AND food_db_source = ?",
                ("u1", "MANUAL"),
            )
            self.assertEqual(row["count"], 3)
        finally:
            os.unlink(tmp_db.name)

    def test_gi_alias_lookup_maps_to_classify(self):
        with mock.patch("scripts.healthfit.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            rc = healthfit.dispatch(["gi", "lookup", "--food", "白飯"])

        self.assertEqual(rc, 0)
        cmd = run_mock.call_args.args[0]
        self.assertEqual(Path(cmd[1]).name, "gi_guide.py")
        self.assertEqual(cmd[2:], ["classify", "--food", "白飯"])

    def test_alert_check_dispatches(self):
        with mock.patch("scripts.healthfit.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            rc = healthfit.dispatch(["alert", "check", "--json"])

        self.assertEqual(rc, 0)
        cmd = run_mock.call_args.args[0]
        self.assertEqual(Path(cmd[1]).name, "health_alerts.py")
        self.assertEqual(cmd[2:], ["check", "--json"])

    def test_notify_checkin_dispatches(self):
        with mock.patch("scripts.healthfit.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            rc = healthfit.dispatch(["notify", "checkin", "--meal-type", "lunch"])

        self.assertEqual(rc, 0)
        cmd = run_mock.call_args.args[0]
        self.assertEqual(Path(cmd[1]).name, "notification_scheduler.py")
        self.assertEqual(cmd[2:], ["checkin", "--meal-type", "lunch"])
