#!/usr/bin/env python3
"""
bootstrap_food_db.py — One-shot food nutrition DB bootstrap.

Imports both TW_FDA and USDA Foundation Foods using the correct pivot importers.
No arguments needed; paths are relative to the project root.

Usage:
    python scripts/bootstrap_food_db.py

Exit codes:
    0  — success (at least one source imported > 0 records)
    1  — both sources failed / no records imported
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Resolve project root (parent of scripts/)
PROJECT_ROOT = _SCRIPT_DIR.parent
os.environ.setdefault(
    "HEALTHFIT_DB",
    str(PROJECT_ROOT / "data" / "healthfit.db"),
)

from db_manager import DBManager
from food_db_import_pivot import import_taiwan, import_usda_foundation

ASSETS_DIR = PROJECT_ROOT / "assets"
TW_CSV     = ASSETS_DIR / "tw_food_db" / "tw_food_db.csv"
USDA_DIR   = ASSETS_DIR / "usda_food_db" / "foundation_foods_csv"


def main() -> int:
    db = DBManager(Path(os.environ["HEALTHFIT_DB"]).expanduser())
    db.initialize()

    print("=" * 55)
    print("HealthFit Food DB Bootstrap")
    print("=" * 55)

    tw_count = 0
    if TW_CSV.exists():
        tw_count = import_taiwan(db, TW_CSV)
        print(f"   → TW_FDA: {tw_count} records")
    else:
        print(f"   ⚠ TW_FDA CSV not found at {TW_CSV}, skipping")

    print()

    usda_count = 0
    if USDA_DIR.exists():
        usda_count = import_usda_foundation(db, str(USDA_DIR))
        print(f"   → USDA:   {usda_count} records")
    else:
        print(f"   ⚠ USDA dir not found at {USDA_DIR}, skipping")

    print()
    print("-" * 55)
    total = tw_count + usda_count
    print(f"Total imported: {total} records (TW_FDA={tw_count}, USDA={usda_count})")

    if total == 0:
        print("ERROR: no food nutrition data imported.", file=sys.stderr)
        print("Check that asset CSV files exist and are readable.", file=sys.stderr)
        return 1

    print("Bootstrap complete.")
    print("Run 'python scripts/food_db_status.py' to verify.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())