#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from dining_context_engine import recommend_without_menu
from restaurant_scenarios import list_supported_scenes


def format_recommendation(result) -> str:
    lines: list[str] = []

    lines.append(result.summary)
    lines.append("")

    lines.append("✅ 較推薦：")
    for idx, scored in enumerate(result.recommended, start=1):
        item = scored.item
        cal = (
            f"{item.estimated_calories:.0f} kcal"
            if item.estimated_calories is not None
            else "熱量未知"
        )
        protein = (
            f"{item.estimated_protein_g:.0f}g 蛋白質"
            if item.estimated_protein_g is not None
            else "蛋白質未知"
        )
        confidence = f"{item.confidence:.2f}"

        lines.append(
            f"{idx}. {item.name}｜{cal}｜{protein}｜分數 {scored.score:.0f}｜估算信心 {confidence}"
        )

        if scored.reasons:
            lines.append(f" 理由：{'；'.join(scored.reasons[:3])}")
        if scored.modifications:
            lines.append(f" 調整：{'；'.join(scored.modifications[:3])}")

    lines.append("")
    lines.append("⚠️ 較不建議：")
    for idx, scored in enumerate(result.avoid, start=1):
        item = scored.item
        cal = (
            f"{item.estimated_calories:.0f} kcal"
            if item.estimated_calories is not None
            else "熱量未知"
        )
        lines.append(f"{idx}. {item.name}｜{cal}｜分數 {scored.score:.0f}")
        if scored.reasons:
            lines.append(f" 原因：{'；'.join(scored.reasons[:3])}")

    if result.general_modifications:
        lines.append("")
        lines.append("🛠 點餐調整建議：")
        for rule in result.general_modifications:
            lines.append(f"- {rule}")

    if result.warnings:
        lines.append("")
        lines.append("注意事項：")
        for note in result.warnings:
            lines.append(f"- {note}")

    return "\n".join(lines)


def main() -> int:
    scenes = list_supported_scenes()

    parser = argparse.ArgumentParser(description="外食情境推薦")
    parser.add_argument(
        "--scene",
        required=True,
        choices=scenes,
        help="店家類型",
    )
    parser.add_argument("--remaining-calories", type=float, required=True)
    parser.add_argument("--protein-gap", type=float, default=0)
    parser.add_argument(
        "--goal-type",
        default="loss",
        choices=["loss", "maintain", "gain"],
    )
    parser.add_argument("--low-gi", action="store_true")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    result = recommend_without_menu(
        scene=args.scene,
        calories_remaining=args.remaining_calories,
        protein_gap_g=args.protein_gap,
        goal_type=args.goal_type,
        require_low_gi=args.low_gi,
        top_n=args.top_n,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_recommendation(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())