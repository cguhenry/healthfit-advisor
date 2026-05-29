#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from db_manager import DBManager
from dining_context_engine import recommend_from_menu_items, recommend_without_menu
from dining_user_context import load_dining_user_context
from menu_image_analyzer import parse_menu_items_from_llm_json
from restaurant_scenarios import list_supported_scenes
from recommendation_explainer import explain_recommendation
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

    if result.avoid:
        lines.append("")
        avoid_mode = getattr(result, "avoid_mode", "score_threshold")

        if avoid_mode == "template_patterns":
            avoid_header = "⚠️ 此類店家通常較不建議："
        elif avoid_mode == "score_threshold":
            avoid_header = "⚠️ 依目前目標較不適合："
        else:
            avoid_header = "⚠️ 較需注意："

        lines.append(avoid_header)
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


def main(argv: list[str] | None = None) -> int:
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
    parser.add_argument("--remaining-calories", type=float, default=None)
    parser.add_argument("--protein-gap", type=float, default=None)
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
    parser.add_argument(
        "--menu-json",
        help="直接讀取 JSON 檔案（如同 LLM 回傳格式）做推薦，"
            "不需 vision API。格式：{\"restaurant_type\": \"...\", \"items\": [...]}",
    )
    parser.add_argument(
        "--llm-explain",
        action="store_true",
        help="使用 LLM 將結構化推薦結果整理成自然語言說明",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-4o",
        help="LLM model name（預設 gpt-4o）",
    )

    args = parser.parse_args(argv)

    # ── Resolve user context (DB auto-fill vs manual) ──────────────────────
    # Manual context takes priority; allow --user-id to be used for restaurant
    # profiles even when no active plan exists (as long as calories are manual).
    manual_calories = args.remaining_calories is not None

    if args.user_id and not manual_calories:
        # Need DB context to supply calories
        try:
            ctx = load_dining_user_context(
                db_path=str(Path(args.db_path).expanduser()),
                user_id=args.user_id,
                target_date=args.date,
            )
        except RuntimeError as exc:
            parser.error(str(exc))
        calories_remaining = ctx.calories_remaining
        protein_gap_g = (
            args.protein_gap if args.protein_gap is not None else ctx.protein_gap_g
        )
        goal_type = (
            args.goal_type if args.goal_type is not None else ctx.goal_type
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
    elif args.user_id and manual_calories:
        # Manual calories override; try to load DB context for protein/goal.
        # If user has no active plan, ctx will be None and we fall back gracefully.
        ctx = None
        try:
            ctx = load_dining_user_context(
                db_path=str(Path(args.db_path).expanduser()),
                user_id=args.user_id,
                target_date=args.date,
            )
        except RuntimeError:
            pass  # no active plan — use manual values only

        calories_remaining = args.remaining_calories
        protein_gap_g = (
            args.protein_gap
            if args.protein_gap is not None
            else (ctx.protein_gap_g if ctx else 0)
        )
        goal_type = (
            args.goal_type
            if args.goal_type is not None
            else (ctx.goal_type if ctx else "loss")
        )
        require_low_gi = (
            (ctx.require_low_gi if ctx else False) or args.low_gi
        )
        if ctx is None:
            print(
                f"📊 手動熱量模式（無 active plan）："
                f"熱量 {calories_remaining:+.0f} kcal（手動）、"
                f"蛋白質 {protein_gap_g:+.0f}g、"
                f"目標 {goal_type}、"
                f"低GI={require_low_gi}",
                file=sys.stderr,
            )
        else:
            print(
                f"📊 混合模式（手動熱量 {calories_remaining:+.0f} kcal + DB 其餘）："
                f"熱量 {calories_remaining:+.0f} kcal（手動）、"
                f"蛋白質 {protein_gap_g:+.0f}g、"
                f"目標 {goal_type}、"
                f"低GI={require_low_gi}",
                file=sys.stderr,
            )
    else:
        # No user_id — fully manual mode
        if args.remaining_calories is None:
            parser.error(
                "--user-id is required to auto-fill from DB; "
                "otherwise --remaining-calories must be provided"
            )
        calories_remaining = args.remaining_calories
        protein_gap_g = args.protein_gap if args.protein_gap is not None else 0
        goal_type = args.goal_type or "loss"
        require_low_gi = args.low_gi

    # ── Resolve recommendation (menu-json vs personal restaurant vs generic) ─
    result = None

    if args.menu_json:
        import os

        json_path = Path(args.menu_json).expanduser()
        raw = json_path.read_text(encoding="utf-8")
        parsed_scene, items = parse_menu_items_from_llm_json(raw)

        # Allow JSON's restaurant_type to override CLI scene
        if parsed_scene is not None and parsed_scene != args.scene:
            print(
                f'⚠️ JSON restaurant_type "{parsed_scene}" 覆寫控件 scene "{args.scene}"',
                file=sys.stderr,
            )
        effective_scene = parsed_scene or args.scene

        result = recommend_from_menu_items(
            items=items,
            scene=effective_scene,
            calories_remaining=calories_remaining,
            protein_gap_g=protein_gap_g,
            goal_type=goal_type,
            require_low_gi=require_low_gi,
            top_n=args.top_n,
        )
        result.summary = f"已根據 JSON 檔案「{args.menu_json}」推薦。"
        print(
            f"📋 從 JSON 載入 {len(items)} 項品項（scene={effective_scene}）",
            file=sys.stderr,
        )

    elif args.user_id and args.restaurant_name:
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

    # ── Output ─────────────────────────────────────────────────────────────
    if args.llm_explain:
        user_context = {
            "calories_remaining": calories_remaining,
            "protein_gap_g": protein_gap_g,
            "goal_type": goal_type,
            "require_low_gi": require_low_gi,
        }
        try:
            explanation = explain_recommendation(
                user_context=user_context,
                recommendation=result.to_dict(),
                model=args.llm_model,
            )
            print(explanation)
        except Exception as exc:
            print(f"⚠️ LLM 說明失敗：{exc}", file=sys.stderr)
            print(format_recommendation(result))
    elif args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_recommendation(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())