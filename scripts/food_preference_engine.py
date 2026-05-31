#!/usr/bin/env python3
"""
food_preference_engine.py — Phase 6: Food Fingerprint / Preference Learning.

Maintains a persistent per-user food-preference profile in the
food_preference_profile table.  Updated asynchronously after every
food-log write (fire-and-forget, failures are silent).

Quadrants:
  favorites      — high frequency + high daily score → priority suggest
  problematic    — high frequency + low daily score  → avoid or suggest swaps
  exploratory    — low frequency + high daily score  → variety boosters
  avoid          — user explicitly said never_suggest
  preferred      — user explicitly said always_suggest

CLI (via healthfit.py):
  python3 scripts/healthfit.py preference show [--user-id U] [--db-path P] [--json]
  python3 scripts/healthfit.py preference set 雞胸肉 always
  python3 scripts/healthfit.py preference set 珍珠奶茶 avoid
  python3 scripts/healthfit.py preference reset 珍珠奶茶
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal, Optional, Sequence

# ── food‑quality scoring weights ──────────────────────────────────────────
# Scores are 0–100; higher = nutritionally better independent of context.
# Based on per‑100 g values from food_nutrition_cache.

_QUALITY_WEIGHTS = dict(
    cal_density_max=400,     # cal/100g above which we heavily penalise
    protein_min=15,           # g/100g above which is excellent
    fiber_min=4,              # g/100g above which is excellent
    sodium_max=600,           # mg/100g above which is penalised
    sugar_max=10,             # g/100g above which is penalised
    sat_fat_max=8,            # g/100g above which is penalised
)


# ── Phase 8: Recency‑decay helpers ──────────────────────────────────────
from datetime import date
import math


def _parse_date_safe(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _recency_decay_multiplier(
    *,
    last_eaten_date: str | None,
    today: str,
    half_life_days: int = 45,
    floor: float = 0.15,
) -> float:
    """
    回傳 0.15~1.0 的衰退係數。
    half_life_days=45 代表 45 天沒吃，權重剩一半。
    """
    last = _parse_date_safe(last_eaten_date)
    current = _parse_date_safe(today)

    if not last or not current:
        return floor

    days = max((current - last).days, 0)
    multiplier = math.pow(0.5, days / half_life_days)
    return round(max(multiplier, floor), 4)


def _preference_strength(
    *,
    total_count: int,
    recent_count: int,
    last_eaten_date: str | None,
    today: str,
) -> float:
    decay = _recency_decay_multiplier(
        last_eaten_date=last_eaten_date,
        today=today,
    )
    raw = total_count * 0.35 + recent_count * 0.65
    return round(raw * decay, 3)


def _compute_food_quality_score(
    cal_100g: Optional[float],
    protein_100g: Optional[float],
    carb_100g: Optional[float],
    fat_100g: Optional[float],
    fiber_100g: Optional[float],
    sodium_100g: Optional[float],
) -> Optional[float]:
    """Return a food‑intrinsic quality score 0–100, or None if data insufficient.

    Dual‑track scoring — Track 2: pure nutrition characteristics.
    Independent of the user's daily score; unaffected by what else they ate that day.

    Scoring sub‑components (each 0–25, summed to 100):
      • calorie_density  — lower cal/100g is better
      • protein_quality  — higher protein + lower fat is better
      • fibre_quality    — higher fibre is better
      • sodium_penalty   — lower sodium is better
      • sugar_penalty    — lower sugar is better

    Reference: WHO, USDA, and TW_FDA dietary guidelines.
    """
    if cal_100g is None:
        return None

    cal = max(cal_100g or 0, 0)
    prot = max(protein_100g or 0, 0)
    carb = max(carb_100g or 0, 0)
    fat = max(fat_100g or 0, 0)
    fib = max(fiber_100g or 0, 0)
    sod = max(sodium_100g or 0, 0)
    total_macros = prot + carb + fat

    # ── 1. Calorie density (0–25) ─────────────────────────────────────────
    if cal <= 50:
        cal_score = 25
    elif cal <= 100:
        cal_score = 22
    elif cal <= 200:
        cal_score = 17
    elif cal <= 300:
        cal_score = 11
    elif cal <= 450:
        cal_score = 5
    else:
        cal_score = 0

    # ── 2. Protein quality (0–25) — high protein, low saturated fat ────────
    if total_macros > 0:
        prot_ratio = prot / total_macros           # 0–1
        sat_ratio = (fat / total_macros) if total_macros > 0 else 0
    else:
        prot_ratio, sat_ratio = 0.0, 0.0

    if prot >= 20:
        prot_score = 25
    elif prot >= 12:
        prot_score = 20
    elif prot >= 7:
        prot_score = 14
    elif prot >= 3:
        prot_score = 8
    else:
        prot_score = 3

    # slight penalty for high sat fat relative to total fat
    if total_macros > 0 and fat > 0:
        sat_pct = fat / total_macros
        if sat_pct > 0.4:
            prot_score = max(0, prot_score - 5)
        elif sat_pct > 0.25:
            prot_score = max(0, prot_score - 2)

    # ── 3. Fibre quality (0–25) ─────────────────────────────────────────────
    if fib >= 6:
        fib_score = 25
    elif fib >= 4:
        fib_score = 20
    elif fib >= 2.5:
        fib_score = 14
    elif fib >= 1:
        fib_score = 8
    else:
        fib_score = 3

    # ── 4. Sodium penalty (0–25, penalise high sodium) ───────────────────────
    if sod < 100:
        sod_score = 25
    elif sod < 300:
        sod_score = 20
    elif sod < 500:
        sod_score = 14
    elif sod < 800:
        sod_score = 8
    elif sod < 1200:
        sod_score = 3
    else:
        sod_score = 0

    # ── 5. Sugar penalty (0–25, penalise high sugar) ─────────────────────────
    sugar = carb  # use total carb as proxy; real impl would need added_sugar field
    if sugar < 3:
        sug_score = 25
    elif sugar < 8:
        sug_score = 20
    elif sugar < 15:
        sug_score = 14
    elif sugar < 25:
        sug_score = 7
    else:
        sug_score = 0

    total = cal_score + prot_score + fib_score + sod_score + sug_score
    return round(min(max(total, 0), 100), 1)

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

DEFAULT_DB_PATH = Path("~/.healthfit/healthfit.db").expanduser()

# ── quad‑thresholds ──────────────────────────────────────────────────────
# These define how food_names get classified into quadrants.
# "high frequency" = total_count >= MIN_TOTAL_COUNT  (recent_count is also considered for recency)
# "high score"     = avg_daily_score_when_eaten >= MIN_SCORE
# Values chosen so that a food needs ≥2 records before being classified.
MIN_TOTAL_FOR_CLASSIFICATION = 2     # minimum total_count to enter favourites/problematic
MIN_SCORE_FOR_FAVOURITE = 70         # threshold for "high score"
MAX_SCORE_FOR_PROBLEMATIC = 50       # threshold for "low score" (only applies when MIN_TOTAL_FOR_CLASSIFICATION is met)
MIN_COUNT_FOR_PROBLEMATIC = 3        # must have at least this many entries to be labelled problematic


# ─────────────────────────────────────────────────────────────────────────
# SQL helpers  (kept module‑private so callers use the public API)
# ─────────────────────────────────────────────────────────────────────────

def _get_daily_score(db, user_id: str, log_date: str) -> Optional[float]:
    """Return daily_score for user on log_date, or None."""
    row = db.fetch_one(
        """SELECT daily_score FROM daily_summaries
           WHERE user_id = ? AND summary_date = ?""",
        (user_id, log_date),
    )
    if row is None:
        return None
    # daily_score can be None even when the row exists (before scoring runs)
    return row["daily_score"]


def _rows_to_name_list(rows: Sequence[dict[str, Any]], key: str = "food_name") -> list[str]:
    return [r[key] for r in rows]


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────

def update_preference_after_log(
    db,
    user_id: str,
    food_name: str,
    log_date: str,
    *,
    today: str | None = None,
) -> None:
    """Fire-and-forget update after a food_log row is written.

    Dual‑track scoring:
      Track 1 — avg_daily_score_when_eaten:  does this food tend to appear on
        high‑score or low‑score days? (attribution is blurry when multiple
        foods share the same day)
      Track 2 — avg_food_quality_score:      the food's intrinsic nutrition
        profile (calorie density, protein, fibre, sodium, sugar).  Independent
        of context; stays stable across all eating occasions.

    Args:
        db: Initialised DBManager.
        user_id: Target user.
        food_name: Cleaned food name (not ___MEAL_TOTAL___).
        log_date: YYYY-MM-DD of the log event.
        today: Reference date for recent_count window. Defaults to
               date.today().isoformat().  Pass an explicit value in tests
               to make recent_count deterministic.
    """
    today = today or date.today().isoformat()
    if not food_name or food_name == "___MEAL_TOTAL___":
        return

    # Look up nutrition data for this food (Track 2 signal)
    nutrition_row = db.fetch_one(
        """SELECT calories_100g, protein_100g, carb_100g, fat_100g,
                     fiber_100g, sodium_100g
               FROM food_nutrition_cache
              WHERE food_name = ?
              LIMIT 1""",
        (food_name,),
    )
    food_quality = None
    if nutrition_row:
        food_quality = _compute_food_quality_score(
            cal_100g=nutrition_row["calories_100g"],
            protein_100g=nutrition_row["protein_100g"],
            carb_100g=nutrition_row["carb_100g"],
            fat_100g=nutrition_row["fat_100g"],
            fiber_100g=nutrition_row["fiber_100g"],
            sodium_100g=nutrition_row["sodium_100g"],
        )

    daily_score = _get_daily_score(db, user_id, log_date)

    # Phase 1: upsert a row with INSERT ON CONFLICT
    db.execute(
        """INSERT INTO food_preference_profile
             (user_id, food_name, total_count, recent_count,
              avg_daily_score_when_eaten, avg_food_quality_score, last_eaten_date)
           VALUES (?, ?, 1, 1, ?, ?, ?)
           ON CONFLICT(user_id, food_name) DO UPDATE SET
             total_count = total_count + 1,
             last_eaten_date = MAX(last_eaten_date, ?),
             updated_at = CURRENT_TIMESTAMP""",
        (user_id, food_name, daily_score, food_quality, log_date, log_date),
    )

    # ── Phase 2: rolling refresh ────────────────────────────────────────────
    # avg = (old_avg * (old_count - 1) + new_score) / old_count
    # old_count is already-incremented; (old_count - 1) is the count before this upsert.
    row = db.fetch_one(
        """SELECT total_count, avg_food_quality_score
             FROM food_preference_profile
            WHERE user_id = ? AND food_name = ?""",
        (user_id, food_name),
    )
    if row and food_quality is not None:
        old_count = int(row["total_count"] or 0)
        old_avg   = row["avg_food_quality_score"]
        # avg = (old_avg * (old_count - 1) + new_score) / old_count
        # old_count is already-incremented; (old_count - 1) is the count before this upsert.
        previous_count = max(old_count - 1, 0)
        if old_avg is not None and previous_count > 0:
            new_food_quality = (old_avg * previous_count + food_quality) / old_count
        else:
            new_food_quality = food_quality
        db.execute(
            """UPDATE food_preference_profile SET
                  recent_count = (
                    SELECT COUNT(DISTINCT DATE(fl.log_datetime))
                      FROM food_logs fl
                     WHERE fl.user_id    = food_preference_profile.user_id
                       AND fl.food_name  = food_preference_profile.food_name
                       AND DATE(fl.log_datetime) >= DATE(?, '-30 day')
                  ),
                  avg_daily_score_when_eaten = (
                    SELECT AVG(ds.daily_score)
                      FROM food_logs fl
                      JOIN daily_summaries ds
                        ON ds.user_id = fl.user_id
                       AND ds.summary_date = DATE(fl.log_datetime)
                     WHERE fl.user_id    = food_preference_profile.user_id
                       AND fl.food_name  = food_preference_profile.food_name
                       AND ds.daily_score IS NOT NULL
                  ),
                  avg_food_quality_score = ?
                WHERE user_id = ?
                  AND food_name = ?""",
            (today, round(new_food_quality, 1), user_id, food_name),
        )
    else:
        db.execute(
            """UPDATE food_preference_profile SET
                  recent_count = (
                    SELECT COUNT(DISTINCT DATE(fl.log_datetime))
                      FROM food_logs fl
                     WHERE fl.user_id    = food_preference_profile.user_id
                       AND fl.food_name  = food_preference_profile.food_name
                       AND DATE(fl.log_datetime) >= DATE(?, '-30 day')
                  ),
                  avg_daily_score_when_eaten = (
                    SELECT AVG(ds.daily_score)
                      FROM food_logs fl
                      JOIN daily_summaries ds
                        ON ds.user_id = fl.user_id
                       AND ds.summary_date = DATE(fl.log_datetime)
                     WHERE fl.user_id    = food_preference_profile.user_id
                       AND fl.food_name  = food_preference_profile.food_name
                       AND ds.daily_score IS NOT NULL
                  )
                WHERE user_id = ?
                  AND food_name = ?""",
            (today, user_id, food_name),
        )


def get_food_fingerprint(
    db,
    user_id: str,
    top_n: int = 20,
    *,
    today: str | None = None,
) -> dict[str, Any]:
    """Return a quadrant‑based food‑fingerprint for user_id.

    Args:
        db: Initialised DBManager.
        user_id: Target user.
        top_n: Maximum items per quadrant.
        today: Reference date for recent windows.  Defaults to
               date.today().isoformat().  Pass an explicit value in tests
               to make date-window queries deterministic.
    """
    today = today or date.today().isoformat()
    db.initialize()

    # Fetch all rows for the user (both tracks of the dual‑track system)
    all_rows = db.fetchall(
        """SELECT food_name, total_count, recent_count,
                  avg_daily_score_when_eaten, avg_food_quality_score, last_eaten_date,
                  never_suggest, always_suggest
             FROM food_preference_profile
            WHERE user_id = ?
            ORDER BY total_count DESC, food_name ASC""",
        (user_id,),
    )

    # ── quad‑classification (dual‑track) ───────────────────────────────────
    # Score = daily_score × 0.6 + food_quality × 0.4
    #   daily_score   (Track 1) — high when food appears on good‑score days
    #   food_quality  (Track 2) — intrinsic nutrition profile (stable)
    #
    # Thresholds:
    #   favorites    : final ≥ 65  AND total ≥ MIN_TOTAL_FOR_CLASSIFICATION
    #   problematic  : final ≤ 40  AND total ≥ MIN_COUNT_FOR_PROBLEMATIC
    #   exploratory  : everything else (or insufficient data)
    #
    avoid: list[str] = []
    preferred: list[str] = []
    candidates: list[dict[str, Any]] = []

    for r in all_rows:
        name = r["food_name"]
        if r["never_suggest"]:
            avoid.append(name)
            continue
        if r["always_suggest"]:
            preferred.append(name)
            continue

        candidates.append(dict(r))  # general foods enter quadrant classification

    favorites: list[str] = []
    problematic: list[str] = []
    exploratory: list[str] = []

    for r in candidates:
        name = r["food_name"]
        total = int(r["total_count"] or 0)
        recent = int(r["recent_count"] or 0)
        strength = _preference_strength(
            total_count=total,
            recent_count=recent,
            last_eaten_date=r["last_eaten_date"],
            today=today,
        )
        daily = r["avg_daily_score_when_eaten"]   # may be None
        fq    = r["avg_food_quality_score"]        # may be None

        is_classifiable = (
            total >= MIN_TOTAL_FOR_CLASSIFICATION
            and (recent > 0 or strength >= MIN_TOTAL_FOR_CLASSIFICATION)
        )

        if is_classifiable:
            # Compute final dual‑track score; prefer quality if daily is missing
            if daily is not None and fq is not None:
                final = daily * 0.6 + fq * 0.4
            elif daily is not None:
                final = daily  # fallback: only daily track
            elif fq is not None:
                final = fq      # fallback: only quality track
            else:
                exploratory.append(name)
                continue

            if final >= 65:
                favorites.append(name)
            elif final <= 40 and total >= MIN_COUNT_FOR_PROBLEMATIC:
                problematic.append(name)
            else:
                exploratory.append(name)
        else:
            if total > 0:
                exploratory.append(name)

    # Phase 8: build strength lookup once for sorting
    strength_by_name = {
        r["food_name"]: _preference_strength(
            total_count=int(r["total_count"] or 0),
            recent_count=int(r["recent_count"] or 0),
            last_eaten_date=r["last_eaten_date"],
            today=today,
        )
        for r in all_rows
    }

    def _sort_by_strength(names: list[str]) -> list[str]:
        return sorted(names, key=lambda n: (-strength_by_name.get(n, 0), n))

    favorites = _sort_by_strength(favorites)
    problematic = _sort_by_strength(problematic)
    exploratory = _sort_by_strength(exploratory)

    # ---- recent 14d from food_logs (robust, not dependent on profile table) ----
    recent_rows = db.fetchall(
        """SELECT DISTINCT food_name
             FROM food_logs
            WHERE user_id = ?
              AND food_name != '___MEAL_TOTAL___'
              AND DATE(log_datetime) >= DATE(?, '-14 day')
            ORDER BY food_name""",
        (user_id, today),
    )
    recent_14d = _rows_to_name_list(recent_rows)

    return {
        "favorites": favorites[:top_n],
        "problematic": problematic[:top_n],
        "exploratory": exploratory[:top_n],
        "avoid": avoid,
        "preferred": preferred,
        "recent_14d": recent_14d,
    }


def get_preference_prompt_context(
    db,
    user_id: str,
    *,
    today: str | None = None,
) -> str:
    """Return a LLM‑ready text string for meal‑plan prompts.

    Args:
        db: Initialised DBManager.
        user_id: Target user.
        today: Passed through to get_food_fingerprint.  Defaults to
               date.today().isoformat().
    """
    fp = get_food_fingerprint(db, user_id, today=today)
    lines: list[str] = []

    if fp["favorites"]:
        lines.append(
            f"使用者喜歡且評分高的食物（優先推薦）：{', '.join(fp['favorites'][:8])}"
        )
    if fp["problematic"]:
        lines.append(
            f"常吃但拉低評分的食物（建議少推薦或給替換選項）：{', '.join(fp['problematic'][:5])}"
        )
    if fp["recent_14d"]:
        lines.append(
            f"近兩週已出現的食物（請避免重複）：{', '.join(fp['recent_14d'][:12])}"
        )
    if fp["avoid"]:
        lines.append(
            f"使用者設定不要推薦：{', '.join(fp['avoid'])}"
        )

    return "\n".join(lines)


def mark_food_preference(
    db,
    user_id: str,
    food_name: str,
    preference: Literal["avoid", "always", "reset"],
) -> None:
    """Explicit user override for a food.

    - 'avoid'  → set never_suggest=1, always_suggest=0
    - 'always' → set always_suggest=1, never_suggest=0
    - 'reset'  → set both to 0
    """
    db.initialize()

    if preference == "avoid":
        db.execute(
            """INSERT INTO food_preference_profile
                 (user_id, food_name, never_suggest, always_suggest)
               VALUES (?, ?, 1, 0)
               ON CONFLICT(user_id, food_name) DO UPDATE SET
                 never_suggest = 1, always_suggest = 0,
                 updated_at = CURRENT_TIMESTAMP""",
            (user_id, food_name),
        )
    elif preference == "always":
        db.execute(
            """INSERT INTO food_preference_profile
                 (user_id, food_name, never_suggest, always_suggest)
               VALUES (?, ?, 0, 1)
               ON CONFLICT(user_id, food_name) DO UPDATE SET
                 never_suggest = 0, always_suggest = 1,
                 updated_at = CURRENT_TIMESTAMP""",
            (user_id, food_name),
        )
    elif preference == "reset":
        db.execute(
            """INSERT INTO food_preference_profile
                 (user_id, food_name, never_suggest, always_suggest)
               VALUES (?, ?, 0, 0)
               ON CONFLICT(user_id, food_name) DO UPDATE SET
                 never_suggest = 0, always_suggest = 0,
                 updated_at = CURRENT_TIMESTAMP""",
            (user_id, food_name),
        )
    else:
        raise ValueError(
            f"preference must be 'avoid', 'always', or 'reset', got {preference!r}"
        )


# ─────────────────────────────────────────────────────────────────────────
# CLI  (used by healthfit.py preference subcommand)
# ─────────────────────────────────────────────────────────────────────────

def _cmd_show(db, args: argparse.Namespace) -> int:
    fp = get_food_fingerprint(db, args.user_id)

    if args.json:
        print(json.dumps(fp, indent=2, ensure_ascii=False))
        return 0

    print(f"🍽️  Food Fingerprint — user={args.user_id}\n")
    _print_section("⭐ Favorites (高頻+高評分)", fp["favorites"])
    _print_section("⚠️  Problematic (高頻+低評分)", fp["problematic"])
    _print_section("🔍 Exploratory (低頻/新食物)", fp["exploratory"])
    _print_section("🚫 Avoid (使用者標記)", fp["avoid"])
    _print_section("💚 Preferred (使用者標記)", fp["preferred"])
    _print_section("📅 Recent 14d", fp["recent_14d"])
    return 0


def _print_section(title: str, items: list[str]) -> None:
    if not items:
        return
    print(f"{title} ({len(items)}):")
    for item in items:
        print(f"  • {item}")
    print()


def _ensure_user_exists(db, user_id: str) -> None:
    """Create a stub user row if missing (avoids FK failures in CLI)."""
    row = db.fetch_one("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    if not row:
        db.execute(
            """INSERT OR IGNORE INTO users (user_id, display_name, gender, age, height_cm)
               VALUES (?, '[auto]', 'O', 0, 0)""",
            (user_id,),
        )


def _cmd_set(db, args: argparse.Namespace) -> int:
    preference = args.preference.lower()
    if preference not in ("avoid", "always", "reset"):
        print(f"❌ preference must be avoid|always|reset, got {args.preference}", file=sys.stderr)
        return 2

    _ensure_user_exists(db, args.user_id)
    mark_food_preference(db, args.user_id, args.food_name, preference)  # type: ignore[arg-type]

    labels = {"avoid": "🚫 不再推薦", "always": "💚 喜歡，常推薦", "reset": "🔄 已重置偏好"}
    print(f"{labels[preference]}：{args.food_name}")
    return 0


def build_preference_parser(subparsers) -> None:
    """Attach 'preference' subcommand to an argparse subparsers object."""
    pref = subparsers.add_parser("preference", help="食物偏好學習 — 飲食指紋管理")
    pref_sub = pref.add_subparsers(dest="preference_command", required=True)

    # preference show
    p_show = pref_sub.add_parser("show", help="顯示飲食指紋")
    p_show.add_argument("--user-id", required=True, help="User id.")
    p_show.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=_cmd_show)

    # preference set
    p_set = pref_sub.add_parser("set", help="設定食物偏好標籤")
    p_set.add_argument("food_name", help="Food name, e.g. 雞胸肉")
    p_set.add_argument("preference", choices=("avoid", "always", "reset"),
                       help="avoid / always / reset")
    p_set.add_argument("--user-id", required=True, help="User id.")
    p_set.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    p_set.set_defaults(func=_cmd_set)


def dispatch_preference(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone entry for testing, or invoked by healthfit.py."""
    import argparse as _argparse

    parser = _argparse.ArgumentParser(prog="food_preference_engine")
    sub = parser.add_subparsers(dest="command", required=True)
    build_preference_parser(sub)
    args = parser.parse_args(argv)

    from db_manager import DBManager

    db = DBManager(Path(args.db_path).expanduser())
    db.initialize()
    return args.func(db, args)


if __name__ == "__main__":
    raise SystemExit(dispatch_preference())