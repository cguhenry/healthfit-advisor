#!/usr/bin/env python3
"""
food_db_lookup.py — Phase 1.3/6: Food nutrition database lookup engine.

Provides fuzzy search across Taiwan FDA + USDA FoodData Central cached data.
This is the backbone of AI food recognition — turning a food name into
real nutritional values from authoritative databases.

Usage (CLI):
    python3 scripts/food_db_lookup.py search "白飯"
    python3 scripts/food_db_lookup.py search "雞胸肉" --top 5
    python3 scripts/food_db_lookup.py search "salad" --source USDA
    python3 scripts/food_db_lookup.py lookup --source TW_FDA --id tw_12345
    python3 scripts/food_db_lookup.py stats

Usage (Python):
    from food_db_lookup import FoodDBLookup, NutritionInfo
    lookup = FoodDBLookup()
    results = lookup.search("滷肉飯")
    for r in results:
        print(r.food_name, r.calories_100g, "kcal/100g")
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Literal, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from db_manager import DBManager

DEFAULT_DB_PATH = Path(os.environ.get("HEALTHFIT_DB", "~/.healthfit/healthfit.db")).expanduser()

# ─────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────

Source = Literal["TW_FDA", "USDA"]


@dataclass
class NutritionInfo:
    """Per 100g nutritional values for a single food item."""
    source: Source
    food_id: str
    food_name: str
    food_name_en: Optional[str] = None
    category: Optional[str] = None
    calories_100g: float = 0.0
    protein_100g: float = 0.0
    carb_100g: float = 0.0
    fat_100g: float = 0.0
    fiber_100g: float = 0.0
    sodium_100g: float = 0.0
    serving_size_g: float = 100.0  # default 100g
    confidence: float = 0.0       # search match confidence 0–1
    raw_json: Optional[dict] = None

    def calories_for(self, grams: float) -> float:
        return round(self.calories_100g * grams / 100, 1)

    def protein_for(self, grams: float) -> float:
        return round(self.protein_100g * grams / 100, 1)

    def carb_for(self, grams: float) -> float:
        return round(self.carb_100g * grams / 100, 1)

    def fat_for(self, grams: float) -> float:
        return round(self.fat_100g * grams / 100, 1)

    def to_macro_dict(self, grams: float) -> dict:
        return {
            "grams": grams,
            "calories": self.calories_for(grams),
            "protein_g": self.protein_for(grams),
            "carb_g": self.carb_for(grams),
            "fat_g": self.fat_for(grams),
            "fiber_g": round(self.fiber_100g * grams / 100, 1),
            "sodium_mg": round(self.sodium_100g * grams / 100, 1),
        }

    def to_display(self, grams: float = 100) -> str:
        m = self.to_macro_dict(grams)
        return (
            f"🍽️  {self.food_name}\n"
            f"   熱量 {m['calories']} kcal｜蛋白 {m['protein_g']}g｜"
            f"碳水 {m['carb_g']}g｜脂肪 {m['fat_g']}g\n"
            f"   📍 {self.source}｜{self.category or '未分類'}"
        )


@dataclass
class SearchResult:
    """A ranked search result with confidence score."""
    item: NutritionInfo
    match_score: float  # 0–1, higher is better
    matched_on: str     # 'name', 'name_en', 'category'


# ─────────────────────────────────────────────────────────────
# Fuzzy matching utilities
# ─────────────────────────────────────────────────────────────

def _score(a: str, b: str) -> float:
    """Return 0–1 similarity score between two strings (case-insensitive)."""
    if not a or not b:
        return 0.0
    a_lower = a.lower().strip()
    b_lower = b.lower().strip()
    if a_lower == b_lower:
        return 1.0
    return SequenceMatcher(None, a_lower, b_lower).ratio()


def _normalize_chinese(text: str) -> str:
    """Strip spaces, punctuation, and normalize for comparison."""
    import re
    text = re.sub(r"[\s\W_]", "", text)
    return text.lower()


def _match_score(query: str, target: str) -> float:
    """Compute a robust match score using multiple signals."""
    if not query or not target:
        return 0.0
    q = _normalize_chinese(query)
    t = _normalize_chinese(target)
    if q == t:
        return 1.0
    # Exact substring match within
    if q in t:
        return 0.85 + 0.1 * (len(q) / max(len(t), 1))
    if t in q:
        return 0.80
    # SequenceMatcher base
    base = SequenceMatcher(None, q, t).ratio()
    # Bonus: query words appear in target
    words = q
    word_bonus = sum(0.1 for w in words if len(w) >= 2 and w in t)
    return min(0.95, base + word_bonus)


def _looks_english_query(text: str) -> bool:
    """Return True if the query text is predominantly English (ASCII letters > CJK chars)."""
    ascii_letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    cjk_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return ascii_letters > 0 and cjk_chars == 0


def _source_priority_for_query(query: str) -> list[str]:
    """Return [primary, secondary] source order based on query language."""
    if _looks_english_query(query):
        return ["USDA", "TW_FDA"]
    return ["TW_FDA", "USDA"]


def _source_rank(source: str, priority: list[str]) -> int:
    """Return sort rank for a source (lower = higher priority). Unknown sources go last."""
    try:
        return priority.index(source)
    except ValueError:
        return 999


# ─────────────────────────────────────────────────────────────
# Main lookup class
# ─────────────────────────────────────────────────────────────

class FoodDBLookup:
    """
    Fuzzy-search across cached Taiwan FDA + USDA nutrition databases.

    Query priority:
    1. TW_FDA Chinese name (primary — most relevant for Taiwanese users)
    2. TW_FDA English name
    3. USDA Chinese name (via food_name_en field)
    4. USDA English name (foundation search)
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        *,
        db: Optional[DBManager] = None,
    ):
        if db is not None:
            self._db = db
        else:
            self._db = DBManager(db_path=db_path, fast_mode=True)
        self._db.initialize()


    # ── Alias expansion ───────────────────────────────────────
    # Maps common compound food names → base ingredient for better DB matching.
    _FOOD_ALIASES: dict[str, str] = {
        "燙青菜": "青菜",
        "炒青菜": "青菜",
        "清炒蔬菜": "青菜",
        "炒蛋": "雞蛋",
        "荷包蛋": "雞蛋",
        "水煮蛋": "雞蛋",
        "茶葉蛋": "雞蛋",
        "蒸蛋": "雞蛋",
        "蛋花湯": "雞蛋",
        "蛋炒飯": "米飯",
        "雞胸肉": "雞胸",
        "煎雞胸": "雞胸",
        "烤雞胸": "雞胸",
        "燉牛肉": "牛肉",
        "滷牛肉": "牛肉",
        "燙肉片": "豬肉",
        "涮肉片": "豬肉",
        "炸雞排": "雞排",
        "滷肉飯": "米飯",
        "炒麵": "麵",
        "湯麵": "麵",
        "乾麵": "麵",
        "白米飯": "白飯",
        "糙米飯": "糙米飯",
    }

    def _expand_alias(self, query: str) -> str:
        """Expand cooking-method aliases to base ingredient names for better DB matching."""
        return self._FOOD_ALIASES.get(query.strip(), query)

    # ── Core search ──────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        top: int = 5,
        sources: Optional[list[Source]] = None,
        category: Optional[str] = None,
        min_score: float = 0.30,
    ) -> list[SearchResult]:
        """
        Fuzzy search for foods by name.

        Args:
            query: Food name in Chinese or English
            top: Maximum number of results to return
            sources: Filter to specific sources ['TW_FDA', 'USDA']. None = both.
            category: Filter by food category (e.g. '肉類', '蔬菜')
            min_score: Minimum match score threshold (0–1)

        Returns:
            List of SearchResult sorted by match_score descending.
        """
        if not query or len(query.strip()) < 1:
            return []

        priority = _source_priority_for_query(query)
        if sources is None:
            sources = priority
        source_filter = f"AND source IN ({','.join(repr(s) for s in sources)})"
        cat_filter = f"AND category = {repr(category)}" if category else ""

        # Fetch candidate rows — SQLite doesn't have great fulltext search
        # so we pull candidates broadly then score in Python
        rows = self._db.fetchall(
            f"""SELECT * FROM food_nutrition_cache
                WHERE (food_name LIKE ? OR food_name_en LIKE ? OR category LIKE ?)
                {source_filter} {cat_filter}
                ORDER BY food_name
                LIMIT 500""",
            (f"%{query}%", f"%{query}%", f"%{query}%"),
        )

        scored: list[tuple[float, NutritionInfo, str]] = []
        for row in rows:
            ni = self._row_to_nutrition_info(row)
            expanded_q = self._expand_alias(query)
            score1 = _match_score(query, ni.food_name)
            score2 = _match_score(expanded_q, ni.food_name) if expanded_q != query else 0
            score = max(score1, score2)
            matched_on = "name"
            if score < 0.4 and ni.food_name_en:
                en_score = _match_score(query, ni.food_name_en)
                if en_score > score:
                    score = en_score
                    matched_on = "name_en"
            if score >= min_score:
                scored.append((score, ni, matched_on))

        scored.sort(
            key=lambda x: (
                -x[0],
                _source_rank(x[1].source, priority),
                x[1].food_name,
            )
        )
        results: list[SearchResult] = [
            SearchResult(item=ni, match_score=score, matched_on=matched_on)
            for score, ni, matched_on in scored[:top]
        ]

        # ── Category keyword fallback ────────────────────────────
        # Generic terms (青菜/葉菜/豆腐) not found in DB → browse category
        _CAT_KEYWORDS = {
            "青菜": "蔬菜類", "蔬菜": "蔬菜類", "葉菜": "蔬菜類",
            "水果": "水果類", "蘋果": "水果類", "香蕉": "水果類",
            "肉": "肉類", "雞肉": "肉類", "牛肉": "肉類", "豬肉": "肉類",
            "魚": "魚貝類", "海鮮": "魚貝類", "蝦": "魚貝類",
            "蛋": "蛋類", "雞蛋": "蛋類",
            "奶": "乳品類", "牛奶": "乳品類", "優格": "乳品類",
            "豆": "豆類", "豆腐": "豆類",
            "飯": "穀物類", "米飯": "穀物類",
            "堅果": "油脂類", "油": "油脂類",
        }

        if not results and min_score >= 0.30 and category is None:
            for kw, cat in _CAT_KEYWORDS.items():
                if kw in query:
                    cat_rows = self._db.fetchall(
                        f"SELECT * FROM food_nutrition_cache "
                        f"WHERE source IN ('TW_FDA','USDA') AND category = ? AND calories_100g > 0 LIMIT 5",
                        (cat,),
                    )
                    for row in cat_rows:
                        ni = self._row_to_nutrition_info(row)
                        if ni:
                            results.append(
                                SearchResult(item=ni, match_score=0.30, matched_on="category_browse")
                            )
                    break

        return results

    def search_tw(self, query: str, *, top: int = 5) -> list[SearchResult]:
        """Search Taiwan FDA database only (primary for zh-TW users)."""
        return self.search(query, top=top, sources=["TW_FDA"])

    def search_usda(self, query: str, *, top: int = 5) -> list[SearchResult]:
        """Search USDA database only."""
        return self.search(query, top=top, sources=["USDA"])

    def lookup(self, source: Source, food_id: str) -> Optional[NutritionInfo]:
        """Exact lookup by source + food_id."""
        row = self._db.fetchone(
            "SELECT * FROM food_nutrition_cache WHERE source = ? AND food_id = ?",
            (source, food_id),
        )
        return self._row_to_nutrition_info(row) if row else None

    # ── Bulk operations ──────────────────────────────────────

    def search_many(
        self, queries: Iterable[str], *, top: int = 3
    ) -> dict[str, list[SearchResult]]:
        """Search multiple food names at once. Returns {query: [results]}."""
        return {q: self.search(q, top=top) for q in queries}

    def get_foods_by_category(
        self, category: str, *, source: Optional[Source] = None
    ) -> list[NutritionInfo]:
        """Get all foods in a given category."""
        if source:
            rows = self._db.fetchall(
                "SELECT * FROM food_nutrition_cache WHERE category = ? AND source = ? ORDER BY food_name",
                (category, source),
            )
        else:
            rows = self._db.fetchall(
                "SELECT * FROM food_nutrition_cache WHERE category = ? ORDER BY food_name",
                (category,),
            )
        return [self._row_to_nutrition_info(r) for r in rows if r]

    def get_stats(self) -> dict:
        """Return database statistics."""
        rows = self._db.fetchall(
            """SELECT source, COUNT(*) AS count,
                      ROUND(AVG(calories_100g),1) AS avg_cal,
                      ROUND(AVG(protein_100g),1) AS avg_prot,
                      COUNT(DISTINCT category) AS cat_count
               FROM food_nutrition_cache
               GROUP BY source"""
        )
        total = self._db.fetchone("SELECT COUNT(*) AS n FROM food_nutrition_cache")
        cats = self._db.fetchall(
            "SELECT category, COUNT(*) AS n FROM food_nutrition_cache WHERE category IS NOT NULL GROUP BY category ORDER BY n DESC LIMIT 20"
        )
        return {
            "total_items": total["n"] if total else 0,
            "by_source": [dict(r) for r in rows],
            "top_categories": [dict(r) for r in cats],
        }

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _row_to_nutrition_info(row) -> Optional[NutritionInfo]:
        if not row:
            return None

        def _get(key, default=None):
            try:
                val = row[key]
                return val if val is not None else default
            except (KeyError, IndexError):
                return default

        return NutritionInfo(
            source=row["source"],
            food_id=row["food_id"],
            food_name=row["food_name"],
            food_name_en=_get("food_name_en"),
            category=_get("category"),
            calories_100g=float(row["calories_100g"]) if _get("calories_100g") else 0.0,
            protein_100g=float(row["protein_100g"]) if _get("protein_100g") else 0.0,
            carb_100g=float(row["carb_100g"]) if _get("carb_100g") else 0.0,
            fat_100g=float(row["fat_100g"]) if _get("fat_100g") else 0.0,
            fiber_100g=float(row["fiber_100g"]) if _get("fiber_100g") else 0.0,
            sodium_100g=float(row["sodium_100g"]) if _get("sodium_100g") else 0.0,
            serving_size_g=float(_get("serving_size_g") or 100.0),
            raw_json=json.loads(_get("raw_json")) if _get("raw_json") else None,
        )


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def _format_search_results(results: list[SearchResult]) -> str:
    if not results:
        return "  （無符合結果）"
    lines = []
    for i, r in enumerate(results, 1):
        ni = r.item
        conf_pct = round(r.match_score * 100)
        lines.append(
            f"  {i}. {ni.food_name}  【{ni.source}】\n"
            f"     熱量 {ni.calories_100g} kcal/100g｜蛋白 {ni.protein_100g}g｜"
            f"碳 {ni.carb_100g}g｜脂 {ni.fat_100g}g\n"
            f"     符合度 {conf_pct}%（匹配：{r.matched_on}）｜ID: {ni.food_id}"
        )
    return "\n".join(lines)


def cmd_search(args: argparse.Namespace) -> None:
    lookup = FoodDBLookup()
    results = lookup.search(args.query, top=args.top, sources=args.source)
    print(f"🔍 搜尋「{args.query}」→ {len(results)} 個結果：\n")
    print(_format_search_results(results))


def cmd_lookup(args: argparse.Namespace) -> None:
    lookup = FoodDBLookup()
    ni = lookup.lookup(args.source, args.id)
    if ni:
        print(ni.to_display(args.grams))
    else:
        print(f"❌ 找不到 {args.source}:{args.id}")


def cmd_stats(args: argparse.Namespace) -> None:
    lookup = FoodDBLookup()
    stats = lookup.get_stats()
    print("📊 食物資料庫統計")
    print(f"  總項目：{stats['total_items']}")
    for s in stats["by_source"]:
        print(f"  ├─ {s['source']}: {s['count']} 筆｜平均熱量 {s['avg_cal']} kcal｜平均蛋白 {s['avg_prot']}g｜{s['cat_count']} 類")
    if stats["top_categories"]:
        print("  熱門分類：")
        for c in stats["top_categories"][:10]:
            print(f"    {c['category']}: {c['n']} 筆")


def cmd_demo(args: argparse.Namespace) -> None:
    """Run demo searches to verify the lookup is working."""
    lookup = FoodDBLookup()
    demos = [
        ("白飯", ["TW_FDA"]),
        ("雞胸肉", None),
        ("鮭魚", None),
        ("蔬菜", ["TW_FDA"]),
    ]
    print("🧪 食物資料庫查詢演示\n")
    for query, sources in demos:
        results = lookup.search(query, top=3, sources=sources)
        print(f"🔍「{query}」{'（'+','.join(sources)+'）' if sources else ''}：")
        print(_format_search_results(results))
        print()


def main() -> None:
    parser = argparse.ArgumentParser(prog="food_db_lookup.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="Search for a food")
    p.add_argument("query", help="Food name to search")
    p.add_argument("--top", "-n", type=int, default=5, help="Number of results")
    p.add_argument("--source", "-s", nargs="+", choices=["TW_FDA", "USDA"],
                   help="Filter by source")

    p2 = sub.add_parser("lookup", help="Exact lookup by source+id")
    p2.add_argument("--source", required=True, choices=["TW_FDA", "USDA"])
    p2.add_argument("--id", required=True)
    p2.add_argument("--grams", type=float, default=100)

    p3 = sub.add_parser("stats", help="Show database statistics")

    p4 = sub.add_parser("demo", help="Run demo searches")

    args = parser.parse_args()

    if args.command == "search":
        cmd_search(args)
    elif args.command == "lookup":
        cmd_lookup(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "demo":
        cmd_demo(args)


if __name__ == "__main__":
    main()