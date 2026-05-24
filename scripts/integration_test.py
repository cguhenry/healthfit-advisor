#!/usr/bin/env python3
"""
integration_test.py — Phase 7: End-to-end smoke test across implemented phases.

This script exercises representative flows without replacing unit tests.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from calorie_tracker import log_meal_analysis, normalize_phase3_analysis_payload, upsert_daily_summary
from diet_dialogue import build_recommendation
from exercise_tracker import adjust_daily_calorie_target, log_exercise
from food_analyzer import AnalysisScenario, parse_llm_response
from food_db_cache import FoodDBCache
from gi_guide import classify_food
from health_alerts import run_all_checks
from intake_flow import run_intake
from meal_planner import generate_meal_plan
from menstrual_tracker import get_cycle_info, log_period_start
from privacy_manager import delete_user_data, export_user_data
from report_generator import generate_daily_report
from scoring_engine import run_daily_scoring
from db_manager import DBManager


def _mock_food_response() -> dict[str, Any]:
    return {
        "foods": [
            {
                "name": "白飯",
                "name_en": "steamed rice",
                "estimated_g": 180,
                "calories": 250,
                "protein_g": 4,
                "carb_g": 56,
                "fat_g": 0.5,
                "confidence": 0.92,
                "confidence_tier": "high",
                "size_reference": "半碗到一碗",
            },
            {
                "name": "雞胸肉",
                "name_en": "chicken breast",
                "estimated_g": 120,
                "calories": 198,
                "protein_g": 36,
                "carb_g": 0,
                "fat_g": 4,
                "confidence": 0.89,
                "confidence_tier": "high",
                "size_reference": "一掌大小",
            },
        ],
        "total_calories": 448,
        "macros": {"protein_g": 40, "carb_g": 56, "fat_g": 4.5, "fiber_g": 1.2},
        "confidence": 0.88,
        "confidence_tier": "high",
        "low_confidence_warnings": [],
        "nutrition_advice": "蛋白質充足。",
        "remaining_after_meal": 0,
    }


def run_smoke_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        db_path = root / "healthfit.db"
        profile_path = root / "profile.json"
        export_dir = root / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        result: dict[str, Any] = {"ok": True, "steps": []}

        intake_result = run_intake(
            {
                "display_name": "Smoke User",
                "gender": "M",
                "age": 30,
                "height_cm": 175,
                "current_weight_kg": 82,
                "activity_level": "light",
                "goal_weight_kg": 76,
                "target_weeks": 12,
            },
            persist=True,
            profile_path=profile_path,
            db_path=db_path,
            db_fast_mode=True,
        )
        user_id = intake_result["profile"]["user_id"]
        result["steps"].append({"phase": 1, "status": "ok", "active_plan_id": intake_result["active_plan_id"]})

        db = DBManager(db_path, fast_mode=True)
        dialog = build_recommendation(
            cuisine_input="台式",
            location_input="自助餐",
            meal_input="午餐",
            user_context={
                "daily_calorie_target": intake_result["plan"]["daily_calorie_target"],
                "protein_target_g": intake_result["plan"]["macros"]["protein_g"],
                "protein_consumed_g": 0,
            },
        )
        result["steps"].append({"phase": 2, "status": "ok", "recommendation_ready": bool(dialog.get("recommendation"))})

        analysis = parse_llm_response(AnalysisScenario.FOOD, _mock_food_response())
        result["steps"].append({"phase": 3, "status": "ok", "foods": len(analysis.foods)})

        normalized_foods, normalized_total = normalize_phase3_analysis_payload(
            analysis.raw_llm_response or _mock_food_response()
        )
        log_meal_analysis(
            db,
            user_id,
            "lunch",
            normalized_foods,
            total_nutrition=normalized_total,
        )
        summary = upsert_daily_summary(db, user_id, calorie_target=intake_result["plan"]["daily_calorie_target"])
        result["steps"].append({"phase": 4, "status": "ok", "daily_calories": summary.total_calories})

        daily_score = run_daily_scoring(db, user_id, calorie_target=intake_result["plan"]["daily_calorie_target"])
        daily_report = generate_daily_report(db, user_id)
        result["steps"].append({"phase": 5, "status": "ok", "daily_score": daily_score.final_score, "report_length": len(daily_report)})

        log_exercise(db, user_id, "2026-05-24", "cardio", "跑步", 30, "moderate", 82)
        ledger = adjust_daily_calorie_target(db, user_id, "2026-05-24", intake_result["plan"]["daily_calorie_target"])
        log_period_start(db, user_id, "2026-05-01", 28)
        cycle_info = get_cycle_info(db, user_id)
        gi_info = classify_food("白飯")
        meal_plan = generate_meal_plan(daily_calories=intake_result["plan"]["daily_calorie_target"], cuisine="台式")
        alerts = run_all_checks(db, user_id, "2026-05-24")
        result["steps"].append({
            "phase": 6,
            "status": "ok",
            "adjusted_target": ledger["adjusted_target"],
            "cycle_phase": cycle_info["phase"] if cycle_info else "",
            "gi_classification": gi_info.get("gi_level"),
            "meal_plan_days": len(meal_plan["plan"]),
            "alerts": len(alerts),
        })

        db.execute(
            """INSERT INTO food_nutrition_cache (
                source, food_id, food_name, category, calories_100g, protein_100g, carb_100g, fat_100g
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("TW_FDA", "tw-smoke-001", "白飯", "穀物類", 183, 3.1, 40.0, 0.3),
        )
        cache = FoodDBCache(db_path=db_path)
        cache_results = cache.search("白飯", top=1)
        export_result = export_user_data(db, user_id, output_dir=export_dir)
        delete_result = delete_user_data(db, user_id, confirm=True)
        result["steps"].append({
            "phase": 7,
            "status": "ok",
            "cache_hits": cache.stats()["hits"],
            "cache_results": len(cache_results),
            "export_total_records": export_result["total_records"],
            "deleted_records": delete_result["total_deleted"],
        })

        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="HealthFit phase integration smoke test.")
    parser.parse_args()
    print(json.dumps(run_smoke_test(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
