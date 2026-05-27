#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import uuid
import json
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterable, Mapping, Optional, Iterator

DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().with_name("db_schema.sql")
SCHEMA_VERSION = 1

WEIGHT_PLAN_COLUMNS = {
    "target_weeks": "INTEGER",
    "weekly_change_kg": "NUMERIC",
    "weekly_change_pct": "NUMERIC",
    "bmr": "INTEGER",
    "tdee": "INTEGER",
    "daily_calorie_delta": "INTEGER",
    "warnings": "TEXT",
    "requires_professional_review": "BOOLEAN DEFAULT FALSE",
}

# Phase 8 Feature 4: extra columns for data-quality tracking
EXTRA_TABLE_COLUMNS: dict[str, dict[str, str]] = {
    "food_nutrition_cache": {
        "source_confidence": "REAL DEFAULT 0.8",
        "nutrition_confidence": "REAL DEFAULT 0.8",
        "match_method": "TEXT DEFAULT 'unknown'",
        "quality_notes": "TEXT",
    },
    "food_logs": {
        "nutrition_confidence": "REAL",
        "match_method": "TEXT",
    },
}

class DBManager:
    DEFAULT_DB_PATH = DEFAULT_DB_PATH
    DEFAULT_SCHEMA_PATH = DEFAULT_SCHEMA_PATH

    def __init__(self, db_path: Path = DEFAULT_DB_PATH, *, fast_mode: bool = False) -> None:
        self.db_path = db_path.expanduser()
        self.fast_mode = fast_mode
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if self.fast_mode:
            conn.execute("PRAGMA synchronous = OFF")
            conn.execute("PRAGMA journal_mode = MEMORY")
        return conn

    def initialize(self, schema_path: Path = DEFAULT_SCHEMA_PATH) -> None:
        sql = schema_path.read_text(encoding="utf-8")
        with closing(self.connect()) as conn:
            with conn:
                conn.executescript(sql)
                self._migrate(conn)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        """Add missing columns to table without altering others."""
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for column_name, column_type in columns.items():
            if column_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(weight_plans)").fetchall()
        }
        for column_name, column_type in WEIGHT_PLAN_COLUMNS.items():
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE weight_plans ADD COLUMN {column_name} {column_type}")

        # Phase 8 Feature 4: extra data-quality columns
        for table, columns in EXTRA_TABLE_COLUMNS.items():
            self._ensure_columns(conn, table, columns)

        conn.execute(
            """
            INSERT INTO schema_meta (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )

    def fetch_one(self, query: str, params: Iterable[object] = ()) -> Optional[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return conn.execute(query, tuple(params)).fetchone()

    def fetchone(self, query: str, params: Iterable[object] = ()) -> Optional[sqlite3.Row]:
        """Alias for fetch_one, for sqlite3-idiomatic usage in newer modules."""
        return self.fetch_one(query, params)

    def fetchall(self, query: str, params: Iterable[object] = ()) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return list(rows) if rows else []

    def execute(self, query: str, params: Iterable[object] = ()) -> None:
        with closing(self.connect()) as conn:
            with conn:
                conn.execute(query, tuple(params))

    def execute_many(self, query: str, params_iterable: Iterable[Iterable[object]]) -> None:
        """Execute a query with many parameter sets in one batch.

        More efficient than calling execute() repeatedly when inserting
        many rows at once. Uses a single transaction internally.

        Args:
            query: SQL statement (may contain ? placeholders).
            params_iterable: Iterable of parameter tuples/lists.
        """
        with closing(self.connect()) as conn:
            with conn:
                conn.executemany(query, [tuple(p) for p in params_iterable])

    def execute_script(self, sql: str) -> None:
        """Execute multiple SQL statements in one call.

        Automatically wraps in a transaction — commits on success,
        rolls back on error.

        Args:
            sql: Multi-statement SQL script string.
        """
        with closing(self.connect()) as conn:
            with conn:
                conn.executescript(sql)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager that yields a connection inside a transaction.

        Usage:
            with db.transaction() as conn:
                conn.execute("INSERT INTO ...", (...))
                conn.execute("UPDATE ...", (...))
                conn.executemany("INSERT INTO ...", many_params)
            # commits on normal exit, rolls back on exception

        All work inside the block runs in a single transaction — either all
        succeed together or all roll back together.
        """
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_user_profile(self, profile: Mapping[str, object]) -> None:
        self.initialize()
        with closing(self.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO users (user_id, display_name, gender, age, height_cm, ethnicity, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        gender = excluded.gender,
                        age = excluded.age,
                        height_cm = excluded.height_cm,
                        ethnicity = excluded.ethnicity,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        profile["user_id"],
                        profile.get("display_name"),
                        profile.get("gender"),
                        profile.get("age"),
                        profile.get("height_cm"),
                        profile.get("ethnicity", "east_asian"),
                    ),
                )

    def save_active_plan(self, user_id: str, plan: Mapping[str, object], target_date: Optional[str] = None) -> str:
        self.initialize()
        plan_id = str(uuid.uuid4())
        macros = plan["macros"]
        with closing(self.connect()) as conn:
            with conn:
                conn.execute("UPDATE weight_plans SET is_active = 0 WHERE user_id = ? AND is_active = 1", (user_id,))
                conn.execute(
                    """
                    INSERT INTO weight_plans (
                        plan_id, user_id, start_weight_kg, goal_weight_kg, target_weeks,
                        weekly_change_kg, weekly_change_pct, bmr, tdee, activity_level,
                        daily_calorie_target, daily_calorie_delta,
                        protein_target_g, carb_target_g, fat_target_g,
                        target_date, goal_type, warnings, requires_professional_review, is_active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        plan_id,
                        user_id,
                        plan["current_weight_kg"],
                        plan["goal_weight_kg"],
                        plan["target_weeks"],
                        plan["weekly_change_kg"],
                        plan["weekly_change_pct"],
                        plan["bmr"],
                        plan["tdee"],
                        plan["activity_level"],
                        plan["daily_calorie_target"],
                        plan["daily_calorie_delta"],
                        macros["protein_g"],
                        macros["carb_g"],
                        macros["fat_g"],
                        target_date,
                        plan["goal_type"],
                        json.dumps(plan.get("warnings", []), ensure_ascii=False),
                        bool(plan.get("requires_professional_review", False)),
                    ),
                )
            return plan_id

    def get_active_plan(self, user_id: str) -> Optional[sqlite3.Row]:
        self.initialize()
        return self.fetch_one(
            "SELECT * FROM weight_plans WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
