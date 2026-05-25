#!/usr/bin/env python3
"""Tests for unified healthfit.py CLI dispatch."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SKILL_DIR))

from scripts import healthfit


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
