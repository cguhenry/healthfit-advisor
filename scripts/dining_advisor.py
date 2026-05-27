#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from db_manager import DBManager
from dining_context_engine import recommend_from_menu_items, recommend_without_menu
from dining_user_context import load_dining_user_context
from restaurant_scenarios import list_supported_scenes
from user_restaurant_repository import (
    load_user_restaurant_items,
    load_user_restaurant_profile,
)

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


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
    parser.add_argument("--user-id", help="使用者 ID，用於從 DB 讀取今日狀態")
    parser.add_argument("--db-path", default="~/.healthfit/healthfit.db", help="SQLite DB path")
    parser.add_argument("--date", help="指定日期，格式 YYYY-MM-DD；預設今天")
    parser.add_argument(
        "--scene",
        required=True,
        choices=scenes,
        help="店家類型",
    )
    parser.add_argument("--remaining-calories", type=float)
    parser.add_argument("--protein-gap", type=float, default=0)
    parser.add_argument(
        "--goal-type",
        default=None,
        choices=["loss", "maintain", "gain"],
        help="預設從 DB 的 plan 自動取得；可手動覆寫",
    )
    parser.add_argument(
        "--low-gi",
        action="store_true",
        help="手動開啟低 GI 模式（DB 有記錄時自動套用，可疊加覆寫）",
    )
    parser.add_argument(
        "--restaurant-name",
        help="使用者常去店家名稱（有設定時優先使用個人店家資料）",
    )
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    # ── Resolve user context (DB auto-fill vs manual) ──────────────────────
    if args.user_id:
        ctx = load_dining_user_context(
            db_path=str(Path(args.db_path).expanduser()),
            user_id=args.user_id,
            target_date=args.date,
        )
        calories_remaining = ctx.calories_remaining
        protein_gap_g = ctx.protein_gap_g
        goal_type = (
            args.goal_type
            if args.goal_type is not None
            else ctx.goal_type
        )
        require_low_gi = ctx.require_low_gi or args.low_gi
        print(
            f"📊 自動載入 DB 狀態："
            f"熱量 {calories_remaining:+.0f} kcal、"
            f"蛋白質 {protein_gap_g:+.0f}g、"
            f"目標 {goal_type}、"
            f"低GI={require_low_gi}",
            file=sys.stderr,
        )
    else:
        if args.remaining_calories is None:
            parser.error(
                "--user-id is required to auto-fill from DB; "
                "otherwise --remaining-calories must be provided"
            )
        calories_remaining = args.remaining_calories
        protein_gap_g = args.protein_gap
        goal_type = args.goal_type or "loss"
        require_low_gi = args.low_gi

    # ── Resolve recommendation (personal restaurant vs generic scene) ──────
    result = None

    if args.user_id and args.restaurant_name:
        _db = DBManager(Path(args.db_path).expanduser())
        profile = load_user_restaurant_profile(
            _db,
            user_id=args.user_id,
            restaurant_name=args.restaurant_name,
        )
        items = load_user_restaurant_items(
            _db,
            user_id=args.user_id,
            restaurant_name=args.restaurant_name,
        )

        if profile and items:
            result = recommend_from_menu_items(
                items=items,
                scene=profile["scene"],
                calories_remaining=calories_remaining,
                protein_gap_g=protein_gap_g,
                goal_type=goal_type,
                require_low_gi=require_low_gi,
                top_n=args.top_n,
            )
            result.summary = (
                f"以下根據你儲存的「{args.restaurant_name}」菜單資料推薦。"
            )
            print(
                f"📍 使用個人店家資料：{args.restaurant_name}（共 {len(items)} 項品項）",
                file=sys.stderr,
            )

    if result is None:
        result = recommend_without_menu(
            scene=args.scene,
            calories_remaining=calories_remaining,
            protein_gap_g=protein_gap_g,
            goal_type=goal_type,
            require_low_gi=require_low_gi,
            top_n=args.top_n,
        )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_recommendation(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())