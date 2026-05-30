#!/usr/bin/env python3
"""
food_db_status.py — Sanity check for food nutrition database.

Shows per-source record counts and coverage completeness.

Usage:
    python scripts/food_db_status.py
    HEALTHFIT_DB=data/healthfit.db PYTHONPATH=scripts python scripts/food_db_status.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager


def main() -> int:
    db_path = os.environ.get("HEALTHFIT_DB", "~/.healthfit/healthfit.db")
    db = DBManager(Path(db_path).expanduser())
    db.initialize()

    rows = db.fetchall("""
        SELECT
            source,
            COUNT(*)                                             AS total,
            SUM(CASE WHEN calories_100g IS NOT NULL
                     AND calories_100g > 0 THEN 1 ELSE 0 END)    AS has_calories,
            SUM(CASE WHEN protein_100g   IS NOT NULL
                     AND protein_100g   > 0 THEN 1 ELSE 0 END)   AS has_protein,
            SUM(CASE WHEN carb_100g      IS NOT NULL
                     AND carb_100g      > 0 THEN 1 ELSE 0 END)   AS has_carb,
            SUM(CASE WHEN fat_100g      IS NOT NULL
                     AND fat_100g      > 0 THEN 1 ELSE 0 END)    AS has_fat,
            SUM(CASE WHEN sodium_100g    IS NOT NULL
                     AND sodium_100g    > 0 THEN 1 ELSE 0 END)  AS has_sodium
        FROM food_nutrition_cache
        GROUP BY source
        ORDER BY source
    """)

    if not rows:
        print("food_nutrition_cache is empty.")
        print("Run: python scripts/bootstrap_food_db.py")
        return 1

    print(f"{'source':<10} {'total':>7} {'cal':>7} {'prot':>7} {'carb':>7} {'fat':>7} {'Na':>7}  coverage")
    print("-" * 65)
    for r in rows:
        cov = (r["has_calories"] + r["has_protein"] + r["has_carb"] + r["has_fat"]) / (r["total"] * 4) * 100
        print(
            f"{r['source']:<10} "
            f"{r['total']:>7} "
            f"{r['has_calories']:>7} "
            f"{r['has_protein']:>7} "
            f"{r['has_carb']:>7} "
            f"{r['has_fat']:>7} "
            f"{r['has_sodium']:>7}  "
            f"{cov:5.1f}%"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())