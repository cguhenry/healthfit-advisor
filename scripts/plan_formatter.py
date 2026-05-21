#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def format_plan_summary(plan: Mapping[str, Any]) -> str:
    macros = plan["macros"]
    lines = [
        "HealthFit Phase 1 plan",
        f"- Goal: {plan['goal_type']} from {plan['current_weight_kg']} kg to {plan['goal_weight_kg']} kg over {plan['target_weeks']} weeks",
        f"- BMR/TDEE: {plan['bmr']} / {plan['tdee']} kcal",
        f"- Daily target: {plan['daily_calorie_target']} kcal ({plan['daily_calorie_delta']:+d} vs TDEE)",
        f"- Macros: protein {macros['protein_g']} g, carbs {macros['carb_g']} g, fat {macros['fat_g']} g",
        f"- Method: {plan['methodology']}",
    ]
    warnings = plan.get("warnings") or []
    if warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {warning}" for warning in warnings)
    if plan.get("requires_professional_review"):
        lines.append("- Professional review: required before treating this as an actionable medical/nutrition plan")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Format a HealthFit plan JSON payload for user-facing replies.")
    parser.add_argument("payload", help="Path to JSON containing either a plan object or an intake result with a plan field.")
    args = parser.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    plan = payload.get("plan", payload)
    print(format_plan_summary(plan))


if __name__ == "__main__":
    main()
