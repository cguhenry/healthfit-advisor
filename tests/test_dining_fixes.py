# filepath: tests/test_dining_fixes.py
"""
test_dining_fixes.py — Phase 2 bug fixes:
  Bug 10  parse_menu_items_from_llm_json supports markdown code fences
  Bug 11  user_restaurant_repository functions call db.initialize()
  Existing coverage: recommended/avoid must not overlap; known food not flagged
  as missing nutrition; source_mode preserved; str db_path accepted
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

DBManager = __import__("db_manager").DBManager


# ─── helpers to lazy-load modules ──────────────────────────────────────────

def _load_module(name: str):
    MODULE_PATH = SCRIPTS / f"{name}.py"
    SPEC = importlib.util.spec_from_file_location(name, MODULE_PATH)
    MODULE = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = MODULE
    assert SPEC and SPEC.loader
    SPEC.loader.exec_module(MODULE)
    return MODULE


# ─── Bug 10: parse_menu_items_from_llm_json supports markdown code fences ──

class TestParseMenuItemsFencedJson(unittest.TestCase):
    def test_parse_menu_items_from_fenced_json(self):
        menu_mod = _load_module("menu_image_analyzer")
        parse_menu_items_from_llm_json = menu_mod.parse_menu_items_from_llm_json

        raw = """```json
{
  "restaurant_type": "breakfast_shop",
  "items": [
    {"name": "鮪魚蛋吐司", "price": 55}
  ]
}
```"""
        scene, items = parse_menu_items_from_llm_json(raw)

        self.assertEqual(scene, "breakfast_shop")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "鮪魚蛋吐司")
        self.assertEqual(items[0].price, 55)

    def test_parse_menu_items_from_fenced_json_no_trailing_fence(self):
        """LLM sometimes omits the closing ``` on a long single-line JSON."""
        menu_mod = _load_module("menu_image_analyzer")
        parse_menu_items_from_llm_json = menu_mod.parse_menu_items_from_llm_json

        # Opens with ```json but content has no closing fence
        raw = """```json
{"restaurant_type": "bento_shop", "items": [{"name": "炸雞腿飯", "price": 85}]}"""
        scene, items = parse_menu_items_from_llm_json(raw)

        self.assertEqual(scene, "bento_shop")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "炸雞腿飯")

    def test_parse_menu_items_plain_json_no_fence(self):
        """Plain JSON without any fence must still parse correctly."""
        menu_mod = _load_module("menu_image_analyzer")
        parse_menu_items_from_llm_json = menu_mod.parse_menu_items_from_llm_json

        raw = """{"restaurant_type": "breakfast_shop", "items": [{"name": "奶茶", "price": 30}]}"""
        scene, items = parse_menu_items_from_llm_json(raw)

        self.assertEqual(scene, "breakfast_shop")
        self.assertEqual(items[0].name, "奶茶")


# ─── Bug 11: user_restaurant_repository calls db.initialize() ───────────────

class TestUserRestaurantRepositoryInitializesDb(unittest.TestCase):
    def test_load_user_restaurant_profile_creates_tables_if_missing(self):
        user_mod = _load_module("user_restaurant_repository")
        from dining_models import MenuItem

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "healthfit.db"
            db = DBManager(db_path, fast_mode=True)
            # do NOT call db.initialize() — repository should do it internally

            # First insert via upsert (which also calls initialize)
            upsert_profile = user_mod.upsert_user_restaurant_profile
            upsert_profile(
                db,
                user_id="u_test",
                restaurant_name="阿姨早餐店",
                scene="breakfast_shop",
                notes="鮪魚蛋吐司少醬",
            )

            # Now load — this also calls initialize internally
            load_profile = user_mod.load_user_restaurant_profile
            profile = load_profile(db, user_id="u_test", restaurant_name="阿姨早餐店")

            self.assertIsNotNone(profile)
            self.assertEqual(profile["scene"], "breakfast_shop")
            self.assertIn("少醬", profile["notes"])

    def test_load_user_restaurant_items_creates_tables_if_missing(self):
        user_mod = _load_module("user_restaurant_repository")
        from dining_models import MenuItem

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "healthfit.db"
            db = DBManager(db_path, fast_mode=True)
            # do NOT call db.initialize() — repository should do it internally

            item = MenuItem(
                name="里肌蛋餅",
                estimated_calories=280,
                estimated_protein_g=18,
                price=50,
                source="user_restaurant_profile",
            )
            user_mod.upsert_user_restaurant_item(
                db,
                user_id="u_test2",
                restaurant_name="阿姨早餐店",
                item=item,
            )

            items = user_mod.load_user_restaurant_items(
                db, user_id="u_test2", restaurant_name="阿姨早餐店"
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].name, "里肌蛋餅")
            self.assertEqual(items[0].estimated_calories, 280)


# ─── Existing coverage: recommended/avoid must not overlap ─────────────────

class TestRecommendNoOverlap(unittest.TestCase):
    def test_recommend_from_menu_items_recommended_and_avoid_do_not_overlap(self):
        din_mod = _load_module("dining_context_engine")
        MenuItem = __import__("dining_models").MenuItem

        items = [
            MenuItem(name="珍珠奶茶", source="menu_image"),
            MenuItem(name="無糖綠茶", source="menu_image"),
            MenuItem(name="鮪魚蛋吐司", source="menu_image"),
        ]

        result = din_mod.recommend_from_menu_items(
            items=items,
            scene="breakfast_shop",
            calories_remaining=500,
            protein_gap_g=20,
            top_n=2,
        )

        recommended_names = {x.item.name for x in result.recommended}
        avoid_names = {x.item.name for x in result.avoid}

        self.assertTrue(recommended_names.isdisjoint(avoid_names))

    def test_recommend_from_user_restaurant_preserves_source_mode(self):
        din_mod = _load_module("dining_context_engine")
        MenuItem = __import__("dining_models").MenuItem

        items = [
            MenuItem(
                name="阿姨特製雞肉吐司",
                estimated_calories=420,
                estimated_protein_g=30,
                source="user_restaurant_profile",
            )
        ]

        result = din_mod.recommend_from_menu_items(
            items=items,
            scene="breakfast_shop",
            calories_remaining=500,
            protein_gap_g=20,
        )

        self.assertEqual(result.source_mode, "user_restaurant_profile")


# ─── Known food must not be flagged as missing nutrition ────────────────────

class TestKnownFoodNotFlaggedMissing(unittest.TestCase):
    def test_score_does_not_mark_known_food_as_missing_nutrition(self):
        scoring_mod = _load_module("menu_item_scoring")
        MenuItem = __import__("dining_models").MenuItem

        item = MenuItem(
            name="里肌蛋吐司少醬",
            estimated_calories=430,
            estimated_protein_g=28,
            tags=["high_protein", "reduced_sauce"],
        )

        scored = scoring_mod.score_menu_item(
            item,
            calories_remaining=500,
            protein_gap_g=25,
            goal_type="loss",
        )

        for reason in scored.reasons:
            self.assertNotIn("營養資料不足", reason)


# ─── str db_path accepted by dining_user_context ───────────────────────────

class TestDiningUserContextStrDbPath(unittest.TestCase):
    def test_load_dining_user_context_accepts_str_db_path(self):
        ctx_mod = _load_module("dining_user_context")
        DBManager_mod = _load_module("db_manager").DBManager

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "healthfit.db")

            # Create tables + a minimal user + active plan directly
            db = DBManager_mod(Path(db_path), fast_mode=True)
            db.initialize()
            db.execute(
                "INSERT INTO users (user_id, display_name) VALUES (?, ?)",
                ("u_test", "Test"),
            )
            db.execute(
                """
                INSERT INTO weight_plans
                  (plan_id, user_id, goal_type, daily_calorie_target, protein_target_g,
                   start_weight_kg, goal_weight_kg, target_date, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                ("p_test", "u_test", "loss", 1800, 120, 80.0, 75.0, "2026-05-28"),
            )

            ctx = ctx_mod.load_dining_user_context(
                db_path=db_path,
                user_id="u_test",
                target_date="2026-05-28",
            )

            self.assertEqual(ctx.user_id, "u_test")
            self.assertEqual(ctx.target_date, "2026-05-28")


if __name__ == "__main__":
    unittest.main()