import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

MODULE_PATH = SCRIPTS / "intake_flow.py"
SPEC = importlib.util.spec_from_file_location("intake_flow", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
run_intake = MODULE.run_intake
DBManager = __import__("db_manager").DBManager


class TestIntakeFlow(unittest.TestCase):
    def test_intake_persists_profile_and_active_plan(self):
        payload = {
            "display_name": "Henry",
            "gender": "M",
            "age": 30,
            "height_cm": 170,
            "current_weight_kg": 85,
            "activity_level": "light",
            "goal_weight_kg": 78,
            "target_weeks": 16,
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = run_intake(
                payload,
                profile_path=tmp_path / "profile.json",
                db_path=tmp_path / "healthfit.db",
                db_fast_mode=True,
            )
            self.assertTrue(result["persisted"])
            self.assertIsNotNone(result["active_plan_id"])
            self.assertEqual(result["profile"]["display_name"], "Henry")
            self.assertEqual(result["plan"]["goal_type"], "loss")

            db = DBManager(tmp_path / "healthfit.db", fast_mode=True)
            row = db.fetch_one(
                "SELECT log_date, weight_kg FROM weight_logs WHERE user_id = ?",
                (result["profile"]["user_id"],),
            )
            self.assertIsNotNone(row)
            self.assertEqual(row["log_date"], date.today().isoformat())
            self.assertAlmostEqual(float(row["weight_kg"]), 85.0)

    def test_intake_reports_missing_required_fields(self):
        with self.assertRaisesRegex(ValueError, "goal_weight_kg"):
            run_intake({"display_name": "Henry"}, persist=False)

    def test_intake_rejects_unknown_activity_level(self):
        payload = {
            "display_name": "Henry",
            "gender": "M",
            "age": 30,
            "height_cm": 170,
            "current_weight_kg": 85,
            "activity_level": "sometimes",
            "goal_weight_kg": 78,
            "target_weeks": 16,
        }
        with self.assertRaisesRegex(ValueError, "activity_level"):
            run_intake(payload, persist=False)

    def test_intake_rejects_unknown_risk_flags(self):
        payload = {
            "display_name": "Henry",
            "gender": "M",
            "age": 30,
            "height_cm": 170,
            "current_weight_kg": 85,
            "activity_level": "light",
            "goal_weight_kg": 78,
            "target_weeks": 16,
            "risk_flags": ["unknown"],
        }
        with self.assertRaisesRegex(ValueError, "unknown risk_flags"):
            run_intake(payload, persist=False)


if __name__ == "__main__":
    unittest.main()
