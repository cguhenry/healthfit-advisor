#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable

from bwp_calculator import BWPCalculator
from db_manager import DBManager
from profile_manager import DEFAULT_PROFILE_PATH, ProfileManager

REQUIRED_PROFILE_FIELDS = {
    "display_name",
    "gender",
    "age",
    "height_cm",
    "current_weight_kg",
    "activity_level",
}

REQUIRED_PLAN_FIELDS = {"goal_weight_kg", "target_weeks"}
ALLOWED_DIETARY_RESTRICTIONS = {
    "low_gi",
    "vegetarian",
    "low_sodium",
    "low_fat",
    "dairy_free",
    "nut_free",
}
ALLOWED_GENDERS = {"M", "F", "X"}
ALLOWED_ACTIVITY_LEVELS = {"sedentary", "light", "moderate", "active", "very_active"}
ALLOWED_RISK_FLAGS = {"minor", "pregnancy", "chronic_disease", "eating_disorder"}


def _missing(payload: Dict[str, Any], fields: Iterable[str]) -> list[str]:
    return [field for field in fields if payload.get(field) in (None, "")]


def _validate_payload(payload: Dict[str, Any]) -> None:
    missing = _missing(payload, REQUIRED_PROFILE_FIELDS | REQUIRED_PLAN_FIELDS)
    if missing:
        raise ValueError(f"missing required fields: {', '.join(sorted(missing))}")
    if payload["gender"] not in ALLOWED_GENDERS:
        raise ValueError(f"gender must be one of: {', '.join(sorted(ALLOWED_GENDERS))}")
    if payload["activity_level"] not in ALLOWED_ACTIVITY_LEVELS:
        raise ValueError(f"activity_level must be one of: {', '.join(sorted(ALLOWED_ACTIVITY_LEVELS))}")
    unknown_flags = sorted(set(payload.get("risk_flags") or []) - ALLOWED_RISK_FLAGS)
    if unknown_flags:
        raise ValueError(f"unknown risk_flags: {', '.join(unknown_flags)}")
    if int(payload["age"]) <= 0:
        raise ValueError("age must be positive")
    if float(payload["height_cm"]) <= 0:
        raise ValueError("height_cm must be positive")
    if float(payload["current_weight_kg"]) <= 0:
        raise ValueError("current_weight_kg must be positive")
    if float(payload["goal_weight_kg"]) <= 0:
        raise ValueError("goal_weight_kg must be positive")
    if int(payload["target_weeks"]) <= 0:
        raise ValueError("target_weeks must be positive")


def run_intake(payload: Dict[str, Any], *, persist: bool = True, profile_path: Path | None = None, db_path: Path | None = None, db_fast_mode: bool = False) -> Dict[str, Any]:
    _validate_payload(payload)

    profile_manager = ProfileManager(profile_path or DEFAULT_PROFILE_PATH)
    if profile_manager.exists():
        profile = profile_manager.update(
            display_name=payload["display_name"],
            gender=payload["gender"],
            age=int(payload["age"]),
            height_cm=float(payload["height_cm"]),
            current_weight_kg=float(payload["current_weight_kg"]),
            activity_level=payload["activity_level"],
            ethnicity=payload.get("ethnicity", "east_asian"),
        )
    else:
        profile = profile_manager.bootstrap(
            display_name=payload["display_name"],
            gender=payload["gender"],
            age=int(payload["age"]),
            height_cm=float(payload["height_cm"]),
            current_weight_kg=float(payload["current_weight_kg"]),
            activity_level=payload["activity_level"],
            ethnicity=payload.get("ethnicity", "east_asian"),
        )

    risk_flags = payload.get("risk_flags") or []
    plan = BWPCalculator().build_plan_from_profile(
        age=profile.age,
        height_cm=profile.height_cm,
        current_weight_kg=profile.current_weight_kg,
        goal_weight_kg=float(payload["goal_weight_kg"]),
        target_weeks=int(payload["target_weeks"]),
        gender=profile.gender,
        activity_level=profile.activity_level,
        ethnicity=profile.ethnicity,
        risk_flags=risk_flags,
    )

    dietary_restrictions = payload.get("dietary_restrictions") or []
    unknown_restrictions = sorted(set(dietary_restrictions) - ALLOWED_DIETARY_RESTRICTIONS)
    if unknown_restrictions:
        raise ValueError(f"unknown dietary_restrictions: {', '.join(unknown_restrictions)}")

    result = {
        "profile": asdict(profile),
        "plan": plan.to_dict(),
        "persisted": False,
        "active_plan_id": None,
    }
    # Attach dietary_restrictions before persisting
    result["plan"]["dietary_restrictions"] = dietary_restrictions

    if persist:
        db = DBManager(db_path or DBManager().db_path, fast_mode=db_fast_mode)
        db.upsert_user_profile(result["profile"])
        db.execute(
            """
            INSERT OR IGNORE INTO weight_logs (log_id, user_id, log_date, weight_kg)
            VALUES (lower(hex(randomblob(16))), ?, ?, ?)
            """,
            (profile.user_id, date.today().isoformat(), profile.current_weight_kg),
        )
        result["active_plan_id"] = db.save_active_plan(profile.user_id, result["plan"], payload.get("target_date"))
        result["persisted"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HealthFit Phase 1 intake flow.")
    parser.add_argument("payload", help="Path to a JSON payload containing profile and goal fields.")
    parser.add_argument("--no-persist", action="store_true", help="Calculate only; do not write profile/database state.")
    args = parser.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    print(json.dumps(run_intake(payload, persist=not args.no_persist), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
