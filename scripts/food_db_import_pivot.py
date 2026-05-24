#!/usr/bin/env python3
"""
food_db_import_pivot.py — Phase 1.3: Taiwan FDA + USDA food DB import pipeline.

Handles the complex multi-row → single-row pivot for Taiwan FDA CSV,
and multi-table join for USDA FoodData Central.

Taiwan FDA CSV format (Big5, 17 columns):
  食品分類 | 資料類別 | 整合編號 | 樣品名稱 | 俗名 | 樣品英文名稱 | ...
  分析項分類 | 分析項 | 含量單位 | 每100克含量 | 樣本數 | ...

USDA Foundation Foods (CSV relational):
  food.csv → food_nutrient.csv → nutrient.csv

Usage:
    python3 scripts/food_db_import_pivot.py import-tw
    python3 scripts/food_db_import_pivot.py import-usda
    python3 scripts/food_db_import_pivot.py import-all
    python3 scripts/food_db_import_pivot.py stats
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
TW_CSV = ASSETS_DIR / "tw_food_db" / "tw_food_db.csv"
USDA_FOOD_CSV = ASSETS_DIR / "usda_food_db" / "usda_foundation.csv"
USDA_EXTRACT = Path("/tmp/usda_extract") / "FoodData_Central_foundation_food_csv_2026-04-30"

# Taiwan FDA nutrient mapping: 分析項 → DB column (per 100g)
# 一般成分: Calories(熱量), Protein(粗蛋白), Fat(粗脂肪, 飽和脂肪),
#           Carbs(總碳水化合物), Fiber(膳食纖維), Sodium(鈉)
TW_NUTRIENT_MAP = {
    "熱量": "calories_100g",
    "修正熱量": "calories_100g",
    "粗蛋白": "protein_100g",
    "粗脂肪": "fat_100g",
    "總碳水化合物": "carb_100g",
    "膳食纖維": "fiber_100g",
    "鈉": "sodium_100g",
}

# USDA nutrient ID mapping (from foundation food nutrient.csv)
# 1003=Protein, 1004=Total lipid (fat), 1005=Carbohydrate, 1079=Fiber, 1093=Sodium, 2047/2048=Energy
USDA_NUTRIENT_IDS = {
    "1003": "protein_100g",
    "1004": "fat_100g",
    "1005": "carb_100g",
    "1079": "fiber_100g",
    "1093": "sodium_100g",
    "2047": "calories_100g",  # Energy (Atwater General Factors)
    "2048": "calories_100g",  # Energy (Atwater Specific) — fallback
}


# ─────────────────────────────────────────────────────────────
# Taiwan FDA Pivot + Import
# ─────────────────────────────────────────────────────────────

def _read_tw_rows(file_path: Path) -> list[dict]:
    """Read Taiwan FDA CSV and group rows by 整合編號.

    Returns list of dicts with keys matching food_nutrition_cache columns.
    """
    print(f"📖 讀取台灣FDA CSV: {file_path}")
    # Detect encoding — try UTF-8 first, then Big5
    for enc in ["utf-8-sig", "utf-8", "big5", "cp950"]:
        try:
            with open(file_path, "r", encoding=enc, errors="replace") as f:
                f.read(100)
            encoding = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        encoding = "big5"  # fallback

    print(f"   編碼: {encoding}")

    # Group by 整合編號
    groups: dict[str, dict] = defaultdict(lambda: {
        "food_name": "",
        "food_name_en": "",
        "category": "",
        "nutrients": {},
    })

    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) < 12:
                continue
            fid = row[2].strip()  # 整合編號
            g = groups[fid]
            g["food_name"] = row[3].strip()  # 樣品名稱
            g["food_name_en"] = row[5].strip() if len(row) > 5 else ""
            g["category"] = row[0].strip()  # 食品分類

            nutrient_class = row[8].strip()  # 分析項分類
            nutrient_name = row[9].strip()   # 分析項

            # Only extract "一般成分" nutrients
            if nutrient_class != "一般成分":
                continue

            col_name = TW_NUTRIENT_MAP.get(nutrient_name)
            if not col_name:
                continue

            raw_val = row[11].strip() if len(row) > 11 else ""
            try:
                g["nutrients"][col_name] = float(raw_val)
            except ValueError:
                g["nutrients"][col_name] = 0.0

    foods = []
    for fid, g in groups.items():
        nutrients = g["nutrients"]
        if not nutrients:
            continue
        foods.append({
            "source": "TW_FDA",
            "food_id": fid,
            "food_name": g["food_name"],
            "food_name_en": g["food_name_en"] or None,
            "category": g["category"] or None,
            "calories_100g": nutrients.get("calories_100g", 0.0),
            "protein_100g": nutrients.get("protein_100g", 0.0),
            "fat_100g": nutrients.get("fat_100g", 0.0),
            "carb_100g": nutrients.get("carb_100g", 0.0),
            "fiber_100g": nutrients.get("fiber_100g", 0.0),
            "sodium_100g": nutrients.get("sodium_100g", 0.0),
            "serving_size_g": 100.0,
        })
    return foods


def import_taiwan(db: DBManager, file_path: Optional[Path] = None) -> int:
    """Pivot and import Taiwan FDA food DB."""
    path = file_path or TW_CSV
    if not path.exists():
        print(f"❌ 找不到檔案: {path}")
        return 0

    foods = _read_tw_rows(path)
    print(f"   Pivot 完成: {len(foods)} 種食物（from {path.stat().st_size // 1024 // 1024} MB）")

    # Bulk insert
    count = 0
    for food in foods:
        try:
            db.execute(
                """INSERT INTO food_nutrition_cache (
                    source, food_id, food_name, food_name_en, category,
                    calories_100g, protein_100g, fat_100g, carb_100g,
                    fiber_100g, sodium_100g
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, food_id) DO UPDATE SET
                    food_name = excluded.food_name,
                    food_name_en = excluded.food_name_en,
                    category = excluded.category,
                    calories_100g = excluded.calories_100g,
                    protein_100g = excluded.protein_100g,
                    fat_100g = excluded.fat_100g,
                    carb_100g = excluded.carb_100g,
                    fiber_100g = excluded.fiber_100g,
                    sodium_100g = excluded.sodium_100g""",
                (
                    food["source"], food["food_id"], food["food_name"],
                    food["food_name_en"], food["category"],
                    food["calories_100g"], food["protein_100g"],
                    food["fat_100g"], food["carb_100g"],
                    food["fiber_100g"], food["sodium_100g"],
                ),
            )
            count += 1
        except Exception as e:
            print(f"   ⚠️ 跳過 {food['food_id']}: {e}")
            continue

    print(f"✅ 匯入完成: {count} 筆台灣食品資料")
    return count


# ─────────────────────────────────────────────────────────────
# USDA Foundation Foods Import
# ─────────────────────────────────────────────────────────────

def import_usda(db: DBManager) -> int:
    """Import USDA Foundation Foods by joining food + food_nutrient tables."""
    extract = USDA_EXTRACT
    food_csv = extract / "food.csv"
    nutrient_csv = extract / "food_nutrient.csv"

    if not food_csv.exists():
        print(f"❌ 找不到 USDA 檔案: {food_csv}")
        return 0

    print(f"📖 讀取 USDA 資料庫: {extract}")

    # Step 1: Build nutrient lookup: {fdc_id: {nutrient_id: amount}}
    print("   載入食物營養素映射...")
    nutrient_data: dict[str, dict[str, float]] = defaultdict(dict)
    with open(nutrient_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            fid = row["fdc_id"]
            nid = row["nutrient_id"]
            col = USDA_NUTRIENT_IDS.get(nid)
            if col:
                try:
                    amt = float(row["amount"])
                    if col == "calories_100g":
                        # Prefer Atwater General (2047) over Specific (2048)
                        if "calories_100g" not in nutrient_data[fid] or nid == "2047":
                            nutrient_data[fid][col] = amt
                    else:
                        nutrient_data[fid][col] = amt
                except (ValueError, TypeError):
                    pass
    print(f"   營養素資料: {len(nutrient_data)} 種食物")

    # Step 2: Read food metadata + join with nutrient data
    print("   匯入食物 + 營養素...")
    count = 0
    with open(food_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = row["fdc_id"]
            nutrients = nutrient_data.get(fid, {})
            if not nutrients:
                continue

            try:
                db.execute(
                    """INSERT INTO food_nutrition_cache (
                        source, food_id, food_name, category,
                        calories_100g, protein_100g, fat_100g, carb_100g,
                        fiber_100g, sodium_100g
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source, food_id) DO UPDATE SET
                        food_name = excluded.food_name,
                        category = excluded.category,
                        calories_100g = excluded.calories_100g,
                        protein_100g = excluded.protein_100g,
                        fat_100g = excluded.fat_100g,
                        carb_100g = excluded.carb_100g,
                        fiber_100g = excluded.fiber_100g,
                        sodium_100g = excluded.sodium_100g""",
                    (
                        "USDA",
                        f"usda_{fid}",
                        row.get("description", "Unknown"),
                        row.get("food_category_id"),
                        nutrients.get("calories_100g", 0.0),
                        nutrients.get("protein_100g", 0.0),
                        nutrients.get("fat_100g", 0.0),
                        nutrients.get("carb_100g", 0.0),
                        nutrients.get("fiber_100g", 0.0),
                        nutrients.get("sodium_100g", 0.0),
                    ),
                )
                count += 1
                if count % 5000 == 0:
                    print(f"   ... {count} 筆")
            except Exception as e:
                print(f"   ⚠️ 跳過 fdc_id={fid}: {e}")
                continue

    print(f"✅ 匯入完成: {count} 筆 USDA 食品資料")
    return count


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(prog="food_db_import_pivot.py")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("import-tw", help="Import Taiwan FDA food DB (pivot format)")
    sub.add_parser("import-usda", help="Import USDA Foundation Foods")
    sub.add_parser("import-all", help="Import both TW + USDA")
    sub.add_parser("stats", help="Show current DB stats")

    p_clear = sub.add_parser("clear", help="Clear all food cache")
    p_clear.add_argument("--source", choices=["TW_FDA", "USDA"], help="Clear specific source")

    args = parser.parse_args()

    db_path = Path(os.environ.get("HEALTHFIT_DB", "~/.healthfit/healthfit.db")).expanduser()
    db = DBManager(db_path=db_path)
    db.initialize()

    if args.command == "import-tw":
        import_taiwan(db)
    elif args.command == "import-usda":
        import_usda(db)
    elif args.command == "import-all":
        n_tw = import_taiwan(db)
        n_us = import_usda(db)
        print(f"\n📊 總計: {n_tw} 台灣 + {n_us} USDA = {n_tw + n_us} 筆食物資料")
    elif args.command == "clear":
        if hasattr(args, "source") and args.source:
            db.execute("DELETE FROM food_nutrition_cache WHERE source = ?", (args.source,))
            print(f"🗑️ 已清空 {args.source} 快取")
        else:
            db.execute("DELETE FROM food_nutrition_cache")
            print("🗑️ 已清空全部食物快取")
    elif args.command == "stats":
        rows = db.fetchall("SELECT source, COUNT(*) AS n FROM food_nutrition_cache GROUP BY source")
        total = sum(r["n"] for r in rows)
        print(f"📊 食物資料庫統計")
        print(f"   總計: {total} 筆")
        for r in rows:
            print(f"   {r['source']}: {r['n']} 筆")


if __name__ == "__main__":
    main()