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
) -> None:
    """Fire-and-forget update after a food_log row is written.

    Args:
        db: Initialised DBManager.
        user_id: Target user.
        food_name: Cleaned food name (not ___MEAL_TOTAL___).
        log_date: YYYY-MM-DD of the log event.
    """
    if not food_name or food_name == "___MEAL_TOTAL___":
        return

    daily_score = _get_daily_score(db, user_id, log_date)

    # Phase 1: upsert a row with INSERT ON CONFLICT
    db.execute(
        """INSERT INTO food_preference_profile
             (user_id, food_name, total_count, recent_count,
              avg_daily_score_when_eaten, last_eaten_date)
           VALUES (?, ?, 1, 1, ?, ?)
           ON CONFLICT(user_id, food_name) DO UPDATE SET
             total_count = total_count + 1,
             last_eaten_date = MAX(last_eaten_date, ?),
             updated_at = CURRENT_TIMESTAMP""",
        (user_id, food_name, daily_score, log_date, log_date),
    )

    # Phase 2: refresh recent_count and avg_daily_score_when_eaten
    # from the underlying food_logs / daily_summaries tables
    db.execute(
        """UPDATE food_preference_profile SET
             recent_count = (
               SELECT COUNT(DISTINCT DATE(fl.log_datetime))
                 FROM food_logs fl
                WHERE fl.user_id = food_preference_profile.user_id
                  AND fl.food_name  = food_preference_profile.food_name
                  AND DATE(fl.log_datetime) >= DATE('now', '-30 day')
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
        (user_id, food_name),
    )


def get_food_fingerprint(
    db,
    user_id: str,
    top_n: int = 20,
) -> dict[str, Any]:
    """Return a quadrant‑based food‑fingerprint for user_id.

    Returns:
        {
          "favorites":    [...],   # high count + high score
          "problematic":  [...],   # high count + low score
          "exploratory":  [...],   # low count + high score (or no score yet)
          "avoid":        [...],   # never_suggest = 1
          "preferred":    [...],   # always_suggest = 1
          "recent_14d":   [...],   # food names eaten in last 14 days (deduped)
        }
    """
    db.initialize()

    # Fetch all rows for the user
    all_rows = db.fetchall(
        """SELECT food_name, total_count, recent_count,
                  avg_daily_score_when_eaten, last_eaten_date,
                  never_suggest, always_suggest
             FROM food_preference_profile
            WHERE user_id = ?
            ORDER BY total_count DESC, food_name ASC""",
        (user_id,),
    )

    # ---- quad‑classification ----
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
            continue  # 既然使用者明確喜歡，不再進行象限分類

    favorites: list[str] = []
    problematic: list[str] = []
    exploratory: list[str] = []

    for r in candidates:
        name = r["food_name"]
        total = int(r["total_count"] or 0)
        score = r["avg_daily_score_when_eaten"]  # may be None

        if total >= MIN_TOTAL_FOR_CLASSIFICATION:
            if score is not None and score >= MIN_SCORE_FOR_FAVOURITE:
                favorites.append(name)
            elif score is not None and score <= MAX_SCORE_FOR_PROBLEMATIC and total >= MIN_COUNT_FOR_PROBLEMATIC:
                problematic.append(name)
            else:
                # has enough data but in the grey zone — treat as exploratory
                exploratory.append(name)
        else:
            # not enough data — exploratory
            if total > 0:
                exploratory.append(name)

    # Sort each quadrant by total_count desc, then name asc
    _sort_by_count = lambda names, rows: sorted(
        names,
        key=lambda n: next(
            (-(int(r["total_count"] or 0)) for r in rows if r["food_name"] == n), 0
        ),
    )

    favorites = _sort_by_count(favorites, all_rows)
    problematic = _sort_by_count(problematic, all_rows)
    exploratory = _sort_by_count(exploratory, all_rows)

    # ---- recent 14d from food_logs (robust, not dependent on profile table) ----
    recent_rows = db.fetchall(
        """SELECT DISTINCT food_name
             FROM food_logs
            WHERE user_id = ?
              AND food_name != '___MEAL_TOTAL___'
              AND DATE(log_datetime) >= DATE('now', '-14 day')
            ORDER BY food_name""",
        (user_id,),
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


def get_preference_prompt_context(db, user_id: str) -> str:
    """Return a LLM‑ready text string for meal‑plan prompts.

    Replaces _get_recent_food_preferences() in meal_planner.py.
    """
    fp = get_food_fingerprint(db, user_id)
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