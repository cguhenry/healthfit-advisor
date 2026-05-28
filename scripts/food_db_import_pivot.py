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
from collections import defaultdict  # kept for TW pivot
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

# ─────────────────────────────────────────────────────────────
# USDA Foundation Foods — constants & helpers (foundation_foods_csv/)
# ─────────────────────────────────────────────────────────────

from pathlib import Path as _Path
import csv as _csv
import os as _os
from typing import Any

DEFAULT_USDA_DIR = _Path("assets/usda_food_db/foundation_foods_csv")

# USDA FDC nutrient ID → DB column mapping (per 100g)
USDA_NUTRIENT_IDS = {
    "calories_100g":  {1008, 2047, 2048},  # Energy, kcal — all Atwater variants
    "protein_100g":   {1003},  # Protein
    "fat_100g":       {1004},  # Total lipid (fat)
    "carb_100g":      {1005},  # Carbohydrate, by difference
    "fiber_100g":     {1079},  # Fiber, total dietary
    "sugar_100g":     {2000},  # Sugars, total including NLEA
    "sodium_100g":    {1093},  # Sodium, Na
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _resolve_usda_dir(usda_dir: str | _Path | None = None) -> _Path:
    if usda_dir:
        path = _Path(usda_dir).expanduser()
    else:
        path = _Path(_os.environ.get("HEALTHFIT_USDA_DIR", DEFAULT_USDA_DIR)).expanduser()

    if not path.exists():
        raise FileNotFoundError(
            f"USDA directory not found: {path}\n"
            "Please download USDA FoodData Central Foundation Foods CSV "
            "and provide --usda-dir pointing to the extracted folder containing "
            "food.csv, food_nutrient.csv, and nutrient.csv."
        )
    return path


def _validate_usda_files(usda_dir: _Path) -> tuple[_Path, _Path, _Path, _Path]:
    food_csv          = usda_dir / "food.csv"
    food_nutrient_csv = usda_dir / "food_nutrient.csv"
    nutrient_csv      = usda_dir / "nutrient.csv"
    foundation_csv    = usda_dir / "foundation_food.csv"

    missing = [str(p) for p in [food_csv, food_nutrient_csv, nutrient_csv, foundation_csv] if not p.exists()]

    if missing:
        raise FileNotFoundError(
            "USDA Foundation Foods CSV files are missing:\n"
            + "\n".join(f"- {x}" for x in missing)
            + "\nExpected files: food.csv, food_nutrient.csv, nutrient.csv, foundation_food.csv"
        )

    return food_csv, food_nutrient_csv, nutrient_csv, foundation_csv


def _load_usda_foundation_ids(foundation_csv: _Path) -> set[int]:
    """Load fdc_ids listed in foundation_food.csv (authoritative list of Foundation Foods)."""
    ids: set[int] = set()
    with foundation_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            fdc_id = _to_int(row.get("fdc_id"))
            if fdc_id is not None:
                ids.add(fdc_id)
    return ids


def _load_usda_foods(
    food_csv: _Path,
    foundation_ids: set[int] | None = None,
) -> dict[int, dict[str, Any]]:
    """
    Load food.csv rows.

    If foundation_ids is provided, only yield rows whose fdc_id appears in
    that set (strict Foundation Food filtering via foundation_food.csv).
    Otherwise fall back to data_type == "foundation_food" for backward
    compatibility with partial downloads that lack foundation_food.csv.
    """
    foundation_ids = foundation_ids or set()

    foods: dict[int, dict[str, Any]] = {}
    with food_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            fdc_id = _to_int(row.get("fdc_id"))
            if fdc_id is None:
                continue

            data_type = str(row.get("data_type") or "").lower()

            if foundation_ids:
                # Strict: only accept fdc_ids listed in foundation_food.csv
                if fdc_id not in foundation_ids:
                    continue
            else:
                # Fallback for partial downloads
                if data_type != "foundation_food":
                    continue

            description = (row.get("description") or "").strip()
            if not description:
                continue

            foods[fdc_id] = {
                "fdc_id":           fdc_id,
                "description":       description,
                "data_type":        row.get("data_type"),
                "food_category_id": row.get("food_category_id"),
                "publication_date": row.get("publication_date"),
            }

    return foods


def _load_usda_nutrients(nutrient_csv: _Path) -> dict[int, dict[str, Any]]:
    nutrients: dict[int, dict[str, Any]] = {}

    with nutrient_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            nutrient_id = _to_int(row.get("id"))
            if nutrient_id is None:
                continue
            nutrients[nutrient_id] = row

    return nutrients


def _pivot_usda_nutrients(
    food_nutrient_csv: _Path,
    valid_fdc_ids: set[int],
) -> dict[int, dict[str, float]]:
    id_to_field: dict[int, str] = {}
    for field, ids in USDA_NUTRIENT_IDS.items():
        for nutrient_id in ids:
            id_to_field[nutrient_id] = field

    pivot: dict[int, dict[str, float]] = {}

    with food_nutrient_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            fdc_id      = _to_int(row.get("fdc_id"))
            nutrient_id = _to_int(row.get("nutrient_id"))
            amount      = _to_float(row.get("amount"))

            if fdc_id is None or nutrient_id is None or amount is None:
                continue
            if fdc_id not in valid_fdc_ids:
                continue

            field = id_to_field.get(nutrient_id)
            if not field:
                continue

            pivot.setdefault(fdc_id, {})[field] = amount

    return pivot


def import_usda_foundation(db: DBManager, usda_dir: str | _Path | None = None) -> int:
    """
    Import USDA FoodData Central Foundation Foods CSV into food_nutrition_cache.

    Expected directory (foundation_foods_csv/):
        food.csv
        food_nutrient.csv
        nutrient.csv
    """
    usda_path = _resolve_usda_dir(usda_dir)
    food_csv, food_nutrient_csv, nutrient_csv = _validate_usda_files(usda_path)

    print(f"Validating USDA files in {usda_path}")
    food_csv, food_nutrient_csv, nutrient_csv, foundation_csv = _validate_usda_files(usda_path)

    print(f"Loading USDA foundation food IDs from {foundation_csv}")
    foundation_ids = _load_usda_foundation_ids(foundation_csv)
    print(f"   Found {len(foundation_ids)} Foundation Food IDs")

    print(f"Loading USDA foods from {food_csv}")
    foods = _load_usda_foods(food_csv, foundation_ids)
    print(f"   Filtered to {len(foods)} foundation foods")

    print(f"Pivoting USDA food nutrients from {food_nutrient_csv}")
    pivot = _pivot_usda_nutrients(food_nutrient_csv, set(foods.keys()))

    imported = 0
    batch = []
    BATCH_SIZE = 500

    for fdc_id, food in foods.items():
        nutrients = pivot.get(fdc_id)
        if not nutrients:
            continue

        calories = nutrients.get("calories_100g")
        protein  = nutrients.get("protein_100g")
        carb     = nutrients.get("carb_100g")
        fat      = nutrients.get("fat_100g")

        # Skip entries with no meaningful nutrition data
        if calories is None and protein is None and carb is None and fat is None:
            continue

        batch.append((
            "USDA",
            f"fdc_{fdc_id}",
            food["description"],
            calories,
            protein,
            carb,
            fat,
            nutrients.get("fiber_100g"),
            nutrients.get("sodium_100g"),
            100.0,
            food.get("food_category_id"),
        ))

        if len(batch) >= BATCH_SIZE:
            _upsert_batch(db, batch)
            imported += len(batch)
            print(f"   ... {imported} foods imported")
            batch = []

    if batch:
        _upsert_batch(db, batch)
        imported += len(batch)

    print(f"USDA Foundation import complete: {imported} foods")
    return imported


def _upsert_batch(db: DBManager, batch: list[tuple]) -> None:
    """Bulk upsert a batch of USDA foods inside a single transaction."""
    with db.transaction() as conn:
        conn.executemany(
            """
            INSERT INTO food_nutrition_cache (
                source, food_id, food_name,
                calories_100g, protein_100g, carb_100g, fat_100g,
                fiber_100g, sodium_100g,
                serving_size_g, category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, food_id) DO UPDATE SET
                food_name      = excluded.food_name,
                calories_100g  = excluded.calories_100g,
                protein_100g   = excluded.protein_100g,
                carb_100g      = excluded.carb_100g,
                fat_100g       = excluded.fat_100g,
                fiber_100g     = excluded.fiber_100g,
                sodium_100g    = excluded.sodium_100g,
                serving_size_g = excluded.serving_size_g,
                category       = excluded.category
            """,
            batch,
        )


# Backward-compat alias
import_usda = import_usda_foundation


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(prog="food_db_import_pivot.py")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("import-tw", help="Import Taiwan FDA food DB (pivot format)")
    p_usda = sub.add_parser("import-usda", help="Import USDA Foundation Foods")
    p_usda.add_argument(
        "--usda-dir",
        default=None,
        help=(
            "Path to extracted USDA Foundation Foods CSV directory containing "
            "food.csv, food_nutrient.csv, nutrient.csv "
            "(default: assets/usda_food_db/foundation_foods_csv/)"
        ),
    )

    p_all = sub.add_parser("import-all", help="Import both TW + USDA")
    p_all.add_argument(
        "--usda-dir",
        default=None,
        help="Path to extracted USDA Foundation Foods CSV directory",
    )
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
        import_usda_foundation(db, getattr(args, "usda_dir", None))
    elif args.command == "import-all":
        n_tw = import_taiwan(db)
        n_us = import_usda_foundation(db, getattr(args, "usda_dir", None))
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