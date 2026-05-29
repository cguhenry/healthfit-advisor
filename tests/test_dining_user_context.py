#!/usr/bin/env python3
"""
test_dining_user_context.py — 測試 dietary_restrictions JSON 解析與低 GI 判斷邏輯

Run with:
    python3 test_dining_user_context.py
(Or with pytest:  python3 -m pytest test_dining_user_context.py -v)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

# ── path helpers ─────────────────────────────────────────────────────────────
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_DB_SCHEMA = _SCRIPTS / "db_schema.sql"

# ── helpers ────────────────────────────────────────────────────────────────


def _db_with_plan(plan: dict, tmp_path: Path) -> Path:
    """Build a minimal DB with the weight_plan row including dietary_restrictions."""
    db_path = tmp_path / "healthfit.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_DB_SCHEMA.read_text())
    conn.execute(
        "INSERT INTO users (user_id,display_name,gender,age,height_cm,created_at) "
        "VALUES ('u1','Test','M',30,175,'2026-01-01')"
    )
    conn.execute(
        "INSERT INTO food_logs "
        "(user_id,meal_type,log_datetime,food_name,calories,protein_g,carb_g,fat_g) "
        "VALUES ('u1','lunch','2026-05-28 12:00:00','x',500,30,60,20)"
    )
    conn.execute(
        "INSERT INTO daily_summaries "
        "(user_id,summary_date,total_calories,total_protein_g,total_carb_g,total_fat_g) "
        "VALUES ('u1','2026-05-28',500,30,60,20)"
    )
    conn.commit()

    # Add dynamic columns (same as DBManager._ensure_columns for weight_plans)
    existing_cols: set = set()
    for row in conn.execute("PRAGMA table_info(weight_plans)").fetchall():
        existing_cols.add(row[1])

    for col_name, col_type in [
        ("warnings", "TEXT"),
        ("is_plateau_adjustment", "INTEGER DEFAULT 0"),
        ("requires_professional_review", "INTEGER DEFAULT 0"),
        ("dietary_restrictions", "TEXT"),
    ]:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE weight_plans ADD COLUMN {col_name} {col_type}")

    conn.execute(
        """
        INSERT INTO weight_plans
          (plan_id,user_id,start_weight_kg,goal_weight_kg,target_weeks,
           weekly_change_kg,weekly_change_pct,bmr,tdee,activity_level,
           daily_calorie_target,daily_calorie_delta,
           protein_target_g,carb_target_g,fat_target_g,
           target_date,goal_type,is_active,warnings,dietary_restrictions)
        VALUES
          (lower(hex(randomblob(16))),
           'u1',80,75,12,-0.4,0.005,1700,2200,'light',
           1800,-400,120,180,60,
           '2026-05-28','loss',1,'[]',:dr)
        """,
        {"dr": json.dumps(plan.get("dietary_restrictions", []), ensure_ascii=False)},
    )
    conn.commit()
    conn.close()
    return db_path


# ── unit tests for the inline parsing helpers ────────────────────────────────


def _parse_dietary_restrictions(value) -> list[str]:
    """Mirror of the function defined inside load_dining_user_context."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return [
        x.strip()
        for x in text.replace("\uff0c", ",").replace("，", ",").split(",")
        if x.strip()
    ]


def _requires_low_gi(restrictions: list[str]) -> bool:
    """Mirror of the function defined inside load_dining_user_context."""
    normalized = {x.lower() for x in restrictions}
    return bool(
        normalized
        & {
            "low_gi",
            "low-gi",
            "diabetes",
            "blood_sugar_control",
            "血糖控制",
            "低gi",
            "低升糖",
        }
    )


class TestParseDietaryRestrictions:
    def test_none(self):
        assert _parse_dietary_restrictions(None) == []

    def test_list_plain(self):
        assert _parse_dietary_restrictions(["low_gi", "vegetarian"]) == [
            "low_gi",
            "vegetarian",
        ]

    def test_json_string(self):
        raw = json.dumps(["low_gi", "no_oil"])
        assert _parse_dietary_restrictions(raw) == ["low_gi", "no_oil"]

    def test_unicode_json_string(self):
        raw = json.dumps(["低gi"], ensure_ascii=False)
        assert _parse_dietary_restrictions(raw) == ["低gi"]

    def test_comma_separated(self):
        assert _parse_dietary_restrictions("low_gi,no_oil") == [
            "low_gi",
            "no_oil",
        ]

    def test_chinese_comma(self):
        assert _parse_dietary_restrictions("low_gi， vegetarian") == [
            "low_gi",
            "vegetarian",
        ]

    def test_empty_string(self):
        assert _parse_dietary_restrictions("") == []

    def test_whitespace_only(self):
        assert _parse_dietary_restrictions("   ") == []

    def test_invalid_json_falls_back_to_comma_split(self):
        assert _parse_dietary_restrictions("low_gi, diabetes") == [
            "low_gi",
            "diabetes",
        ]


class TestRequiresLowGi:
    @staticmethod
    def check_positive(r: str):
        assert _requires_low_gi([r]) is True, f"expected True for {r!r}"

    @staticmethod
    def check_negative(r: str):
        assert _requires_low_gi([r]) is False, f"expected False for {r!r}"

    def test_positive_low_gi(self):
        for r in ["low_gi", "low-gi", "diabetes", "blood_sugar_control", "血糖控制", "低gi", "低升糖"]:
            TestRequiresLowGi.check_positive(r)

    def test_negative(self):
        for r in ["vegetarian", "vegan", "halal", "gluten_free", ""]:
            TestRequiresLowGi.check_negative(r)

    def test_case_insensitive(self):
        assert _requires_low_gi(["LOW_GI"]) is True
        assert _requires_low_gi(["Diabetes"]) is True

    def test_mixed_list(self):
        assert _requires_low_gi(["low_gi", "vegetarian"]) is True


# ── integration test ────────────────────────────────────────────────────────


def test_require_low_gi_from_json_restrictions(tmp_path: Path):
    """
    P0-2 regression: dietary_restrictions stored as JSON list in the
    weight_plans dietary_restrictions column must be correctly parsed
    and trigger require_low_gi=True on load.
    """
    sys.path.insert(0, str(_SCRIPTS))
    from dining_user_context import load_dining_user_context

    plan = {
        "current_weight_kg": 80,
        "goal_weight_kg": 75,
        "target_weeks": 12,
        "weekly_change_kg": -0.4,
        "weekly_change_pct": 0.005,
        "bmr": 1700,
        "tdee": 2200,
        "activity_level": "light",
        "daily_calorie_target": 1800,
        "daily_calorie_delta": -400,
        "goal_type": "loss",
        "macros": {"protein_g": 120, "carb_g": 180, "fat_g": 60},
        "dietary_restrictions": ["low_gi"],
    }

    db_path = _db_with_plan(plan, tmp_path)

    ctx = load_dining_user_context(
        db_path=str(db_path),
        user_id="u1",
        target_date="2026-05-28",
    )

    assert ctx.require_low_gi is True


# ── runner ─────────────────────────────────────────────────────────────────


def _run_all():
    """Standalone runner (no pytest needed)."""
    import traceback

    passed = failed = 0
    results: list[tuple[str, bool, str | None]] = []

    all_tests = [
        ("Parsing / None", lambda: _parse_dietary_restrictions(None) == []),
        ("Parsing / list", lambda: _parse_dietary_restrictions(["low_gi","veg"]) == ["low_gi","veg"]),
        ("Parsing / JSON str", lambda: _parse_dietary_restrictions(json.dumps(["low_gi"])) == ["low_gi"]),
        ("Parsing / comma-sep", lambda: _parse_dietary_restrictions("low_gi, veg") == ["low_gi","veg"]),
        ("Parsing / CN comma", lambda: _parse_dietary_restrictions("low_gi，veg") == ["low_gi","veg"]),
        ("Parsing / empty str", lambda: _parse_dietary_restrictions("") == []),
        ("Parsing / invalid JSON fallback", lambda: _parse_dietary_restrictions("low_gi, diabetes") == ["low_gi","diabetes"]),
        ("Low-GI / low_gi", lambda: _requires_low_gi(["low_gi"]) is True),
        ("Low-GI / low-gi", lambda: _requires_low_gi(["low-gi"]) is True),
        ("Low-GI / diabetes", lambda: _requires_low_gi(["diabetes"]) is True),
        ("Low-GI / 血糖控制", lambda: _requires_low_gi(["血糖控制"]) is True),
        ("Low-GI / 低gi", lambda: _requires_low_gi(["低gi"]) is True),
        ("Low-GI / vegetarian (neg)", lambda: _requires_low_gi(["vegetarian"]) is False),
        ("Low-GI / vegan (neg)", lambda: _requires_low_gi(["vegan"]) is False),
        ("Low-GI / case-insensitive", lambda: _requires_low_gi(["LOW_GI"]) is True),
        ("Low-GI / mixed list", lambda: _requires_low_gi(["low_gi","veg"]) is True),
    ]

    for name, fn in all_tests:
        try:
            ok = fn()
            results.append((name, ok, None))
        except Exception as exc:
            results.append((name, False, traceback.format_exc()))

    for name, ok, tb in results:
        if ok:
            print(f"  OK   {name}")
            passed += 1
        else:
            print(f"  FAIL {name}")
            if tb:
                print(tb)
            failed += 1

    # Integration test
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            test_require_low_gi_from_json_restrictions(tmp_path)
            print("  OK   Integration / require_low_gi from JSON")
            passed += 1
        except Exception as exc:
            print(f"  FAIL Integration / require_low_gi from JSON")
            print(traceback.format_exc())
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = _run_all()
    sys.exit(0 if ok else 1)