#!/usr/bin/env python3
"""
bootstrap_food_db.py — One-shot food nutrition DB bootstrap.

Imports both TW_FDA and USDA Foundation Foods using the correct pivot importers.

Usage:
    python scripts/bootstrap_food_db.py                          # defaults
    python scripts/bootstrap_food_db.py --help                  # show help
    python scripts/bootstrap_food_db.py --db-path /tmp/test.db
    python scripts/bootstrap_food_db.py --usda-dir /path/to/csv --max-foods 50

Exit codes:
    0  — success (at least one source imported > 0 records)
    1  — both sources failed / no records imported
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

PROJECT_ROOT = _SCRIPT_DIR.parent
ASSETS_DIR   = PROJECT_ROOT / "assets"
TW_CSV       = ASSETS_DIR / "tw_food_db" / "tw_food_db.csv"
USDA_DIR     = ASSETS_DIR / "usda_food_db" / "foundation_foods_csv"

from db_manager import DBManager
from food_db_import_pivot import import_taiwan, import_usda_foundation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap HealthFit food nutrition database using TW_FDA and USDA pivot importers.",
    )
    parser.add_argument(
        "--db-path",
        default=os.environ.get("HEALTHFIT_DB"),
        help="SQLite DB path. Defaults to HEALTHFIT_DB or project-root data/healthfit.db.",
    )
    parser.add_argument(
        "--usda-dir",
        default=str(USDA_DIR),
        help="USDA Foundation Foods CSV directory.",
    )
    parser.add_argument(
        "--tw-csv",
        default=str(TW_CSV),
        help="Taiwan FDA CSV path.",
    )
    parser.add_argument(
        "--max-foods",
        type=int,
        default=0,
        help="Cap USDA import to N foods (0 = unlimited). Useful for sampling.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=0,
        help="Print progress every N rows during USDA pivot scan (0 = off).",
    )

    args = parser.parse_args(argv)

    db_path = args.db_path or str(PROJECT_ROOT / "data" / "healthfit.db")
    db = DBManager(Path(db_path).expanduser())
    db.initialize()

    tw_csv = Path(args.tw_csv).expanduser()
    usda_dir = Path(args.usda_dir).expanduser()

    print("=" * 55)
    print("HealthFit Food DB Bootstrap")
    print("=" * 55)

    tw_count = 0
    if tw_csv.exists():
        tw_count = import_taiwan(db, tw_csv)
        print(f"   → TW_FDA: {tw_count} records")
    else:
        print(f"   ⚠ TW_FDA CSV not found at {tw_csv}, skipping")

    print()

    usda_count = 0
    if usda_dir.exists():
        usda_count = import_usda_foundation(
            db,
            str(usda_dir),
            max_foods=args.max_foods or None,
            progress_every=args.progress_every or 0,
        )
        print(f"   → USDA:   {usda_count} records")
    else:
        print(f"   ⚠ USDA dir not found at {usda_dir}, skipping")

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