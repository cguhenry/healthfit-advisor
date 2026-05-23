#!/usr/bin/env python3
"""
food_db_importer.py — Phase 6: Nutrition Database Importer.

Handles importing nutrition data from Taiwan Open Data and USDA FoodData Central.
Stores data in the `food_nutrition_cache` table for fast local lookup.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

# Default local storage for assets
ASSETS_DIR = Path("~/.healthfit/assets").expanduser()
TW_FOOD_DB_PATH = ASSETS_DIR / "tw_food_db.csv"
USDA_FOOD_DB_PATH = ASSETS_DIR / "usda_food_db.json"

# ─────────────────────────────────────────────────────────────
# Importer Logic
# ─────────────────────────────────────────────────────────────

class FoodDBImporter:
    def __init__(self, db: DBManager):
        self.db = db
        self._ensure_assets_dir()

    def _ensure_assets_dir(self) -> None:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    def import_taiwan_db(self, file_path: Optional[str] = None) -> int:
        """
        Import Taiwan Food Composition data.
        Expects CSV with: food_name, calories, protein, fat, carbs, fiber, sodium
        """
        path = Path(file_path) if file_path else TW_FOOD_DB_PATH
        if not path.exists():
            print(f"❌ 找不到台灣食品資料庫檔案: {path}")
            return 0

        print(f"🚀 正在匯入台灣食品資料庫: {path}...")
        count = 0
        with open(path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Normalization
                    name = row.get("食品名稱") or row.get("food_name", "Unknown")
                    cal = float(row.get("熱量", 0) or 0)
                    prot = float(row.get("蛋白質", 0) or 0)
                    fat = float(row.get("脂肪", 0) or 0)
                    carb = float(row.get("碳水化合物", 0) or 0)
                    fib = float(row.get("膳食纖維", 0) or 0)
                    sod = float(row.get("鈉", 0) or 0)

                    self.db.execute(
                        """INSERT INTO food_nutrition_cache (
                            source, food_id, food_name, calories_100g, protein_100g, fat_100g, carb_100g, fiber_100g, sodium_100g
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source, food_id) DO UPDATE SET
                            calories_100g = excluded.calories_100g,
                            protein_100g = excluded.protein_100g,
                            fat_100g = excluded.fat_100g,
                            carb_100g = excluded.carb_100g,
                            fiber_100g = excluded.fiber_100g,
                            sodium_100g = excluded.sodium_100g""",
                        ("TW_FDA", f"tw_{count}", name, cal, prot, fat, carb, fib, sod),
                    )
                    count += 1
                except (ValueError, TypeError) as e:
                    continue

        print(f"✅ 成功匯入 {count} 筆台灣食品資料。")
        return count

    def import_usda_db(self, file_path: Optional[str] = None) -> int:
        """
        Import USDA FoodData Central data.
        Expects JSON format.
        """
        path = Path(file_path) if file_path else USDA_FOOD_DB_PATH
        if not path.exists():
            print(f"❌ 找不到 USDA 資料庫檔案: {path}")
            return 0

        print(f"🚀 正在匯入 USDA 食品資料庫: {path}...")
        count = 0
        with open(path, mode="r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                try:
                    name = item.get("description", "Unknown")
                    # USDA typically uses 100g basis
                    nutrients = item.get("nutrients", {})
                    # Common USDA Nutrient IDs
                    # 205: Energy, 1003: Protein, 1004: Fat, 1005: Carbs, 1079: Fiber, 1085: Sodium
                    cal = float(nutrients.get("205", 0))
                    prot = float(nutrients.get("1003", 0))
                    fat = float(nutrients.get("1004", 0))
                    carb = float(nutrients.get("1005", 0))
                    fib = float(nutrients.get("1079", 0))
                    sod = float(nutrients.get("1085", 0))

                    self.db.execute(
                        """INSERT INTO food_nutrition_cache (
                            source, food_id, food_name, calories_100g, protein_100g, fat_100g, carb_100g, fiber_100g, sodium_100g
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source, food_id) DO UPDATE SET
                            calories_100g = excluded.calories_100g,
                            protein_100g = excluded.protein_100g,
                            fat_100g = excluded.fat_100g,
                            carb_100g = excluded.carb_100g,
                            fiber_100g = excluded.fiber_100g,
                            sodium_100g = excluded.sodium_100g""",
                        ("USDA", f"usda_{count}", name, cal, prot, fat, carb, fib, sod),
                    )
                    count += 1
                except (ValueError, TypeError, KeyError) as e:
                    continue

        print(f"✅ 成功匯入 {count} 筆 USDA 食品資料。")
        return count

    def clear_cache(self) -> None:
        """Clear the nutrition cache."""
        self.db.execute("DELETE FROM food_nutrition_cache")
        print("🗑️ 已清空營養快取。")

# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="HealthFit Food DB Importer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_tw = sub.add_parser("import-tw", help="Import Taiwan food DB")
    p_tw.add_argument("--file", help="Custom CSV path")

    p_usda = sub.add_parser("import-usda", help="Import USDA food DB")
    p_usda.add_argument("--file", help="Custom JSON path")

    p_clear = sub.add_parser("clear", help="Clear food cache")

    args = parser.parse_args()
    db = DBManager(Path("~/.healthfit/healthfit.db").expanduser())
    db.initialize()
    importer = FoodDBImporter(db)

    if args.command == "import-tw":
        importer.import_taiwan_db(args.file)
    elif args.command == "import-usda":
        importer.import_usda_db(args.file)
    elif args.command == "clear":
        importer.clear_cache()

if __name__ == "__main__":
    main()
