import importlib.util
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

MODULE_PATH = SCRIPTS / "db_manager.py"
SPEC = importlib.util.spec_from_file_location("db_manager", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
DBManager = MODULE.DBManager


class TestDBManager(unittest.TestCase):
    def test_initialize_adds_schema_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DBManager(Path(tmp) / "healthfit.db", fast_mode=True)
            db.initialize()
            row = db.fetch_one("SELECT value FROM schema_meta WHERE key = 'schema_version'")
            self.assertIsNotNone(row)
            self.assertEqual(row["value"], "1")

    def test_initialize_migrates_existing_weight_plan_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "healthfit.db"
            db = DBManager(db_path, fast_mode=True)
            with closing(db.connect()) as conn:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE weight_plans (
                            plan_id TEXT PRIMARY KEY,
                            user_id TEXT,
                            start_weight_kg NUMERIC,
                            goal_weight_kg NUMERIC,
                            activity_level VARCHAR(20),
                            daily_calorie_target INTEGER,
                            protein_target_g INTEGER,
                            carb_target_g INTEGER,
                            fat_target_g INTEGER,
                            target_date DATE,
                            goal_type VARCHAR(10),
                            is_active BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
            db.initialize()
            with closing(db.connect()) as conn:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(weight_plans)").fetchall()}
            self.assertIn("requires_professional_review", columns)
            self.assertIn("daily_calorie_delta", columns)


if __name__ == "__main__":
    unittest.main()
