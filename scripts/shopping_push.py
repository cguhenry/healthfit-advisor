#!/usr/bin/env python3
"""
shopping_push.py
────────────────
每週日自動執行，產生下週飲食計劃 → 格式化購物清單 → 推播 + 可選 PDF。

CLI:
 python3 scripts/shopping_push.py --week-start 2026-06-01
 python3 scripts/shopping_push.py --week-start next     # 自動算下週一
 python3 scripts/shopping_push.py --pdf --output ~/shopping.pdf
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

DEFAULT_DB_PATH = Path(os.environ.get("HEALTHFIT_DB_PATH", Path("~/.healthfit/healthfit.db").expanduser()))

# ─────────────────────────────────────────────────────────────
# Category emoji mapping
# ─────────────────────────────────────────────────────────────

_CATEGORY_EMOJI: dict[str, str] = {
    "蛋白質": "🥩",
    "蔬菜": "🥦",
    "水果": "🍎",
    "主食": "🌾",
    "飲料/調味": "🧂",
    "堅果/種子": "🥜",
}

# ─────────────────────────────────────────────────────────────
# Text formatting
# ─────────────────────────────────────────────────────────────

def format_shopping_list_text(shopping_list: dict[str, list[str]], week_start: date) -> str:
    """Format shopping list as mobile-optimised text with emoji categories.

    Args:
        shopping_list: {category: [item1, item2, ...]}
        week_start: Monday of the target week

    Returns multi-line formatted string.
    """
    week_end = week_start + timedelta(days=6)
    total_items = sum(len(items) for items in shopping_list.values())

    lines: list[str] = []
    # Title in Discord/LINE format — emoji header
    lines.append(
        f"🛒 下週採購清單（{week_start.month}/{week_start.day}–{week_end.month}/{week_end.day}）"
    )
    lines.append("")

    for cat, items in shopping_list.items():
        if not items:
            continue
        emoji = _CATEGORY_EMOJI.get(cat, "📦")
        lines.append(f"{emoji} **{cat}**（{len(items)} 項）")
        for item in items:
            lines.append(f"　□ {item}")
        lines.append("")

    # Budget estimate — rough heuristic: ~50-100 per item from template categories
    estimate_low = total_items * 45
    estimate_high = total_items * 85
    lines.append(f"共 {total_items} 項 ｜ 預估花費：${estimate_low}–{estimate_high} 元")
    lines.append("可回覆「已採購」完成確認 ✅")
    lines.append("─" * 30)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────

def _lookup_existing_meal_plan(db, user_id: str, week_start: date) -> Optional[dict]:
    """Look up an existing meal plan for the given week from weekly_meal_plans."""
    ws = week_start.isoformat()
    row = db.fetch_one(
        """SELECT plan_json, shopping_list_json, summary_json, source
             FROM weekly_meal_plans
             WHERE user_id = ? AND week_start_date = ?
             ORDER BY created_at DESC LIMIT 1""",
        (user_id, ws),
    )
    if not row:
        return None
    try:
        return {
            "plan": json.loads(row["plan_json"]),
            "shopping_list": json.loads(row["shopping_list_json"]),
            "summary": json.loads(row["summary_json"]),
        }
    except (json.JSONDecodeError, TypeError):
        return None


def _generate_plan_for_week(db, user_id: str, week_start: date) -> dict:
    """Generate and persist a meal plan for the week.

    Reads the user's active weight plan for calorie/macro targets.
    """
    from meal_planner import generate_meal_plan, persist_meal_plan

    daily_calories = 1800
    protein_target = None

    active_plan = db.fetch_one(
        """SELECT daily_calorie_target, protein_target_g, carb_target_g, fat_target_g
             FROM weight_plans WHERE user_id = ? AND is_active = 1 LIMIT 1""",
        (user_id,),
    )
    if active_plan and active_plan["daily_calorie_target"]:
        daily_calories = int(active_plan["daily_calorie_target"])
    if active_plan and "protein_target_g" in active_plan and active_plan["protein_target_g"]:
        protein_target = int(active_plan["protein_target_g"])

    # 繼承最近一次計劃的 cuisine，避免每次都強制台式
    last_plan_row = db.fetch_one(
        """SELECT cuisine FROM weekly_meal_plans
             WHERE user_id = ? AND cuisine IS NOT NULL AND cuisine != ''
             ORDER BY created_at DESC LIMIT 1""",
        (user_id,),
    )
    cuisine = last_plan_row["cuisine"] if last_plan_row else "台式"

    plan = generate_meal_plan(
        daily_calories=daily_calories,
        cuisine=cuisine,
        meal_preference="balanced",
        protein_target_g=protein_target,
    )

    persist_meal_plan(db, user_id, plan, week_start_date=week_start.isoformat())
    return plan


def run_weekly_shopping_push(
    db,
    user_id: str,
    week_start: date,
    channels: list[str],
    pdf_output: Optional[Path] = None,
) -> dict:
    """
    主流程：
    1. 查 DB 是否已有本週計劃（weekly_meal_plans），沒有則重新產生
    2. 從 shopping_list_json 取出採購清單
    3. 格式化為手機友善文字（分類 + emoji）
    4. 推播到指定頻道
    5. 可選：輸出超市格式 PDF（一頁，每欄對應一個食材類別）

    Returns:
        {"status": "sent", "channel_count": 2, "item_count": 23, "pdf_path": "..."}
    """
    # 1. Get or generate meal plan
    plan = _lookup_existing_meal_plan(db, user_id, week_start)
    if plan is None:
        plan = _generate_plan_for_week(db, user_id, week_start)

    shopping_list: dict[str, list[str]] = plan.get("shopping_list", {})

    # 2. Format text
    text = format_shopping_list_text(shopping_list, week_start)

    # 3. Push to channels
    from notification_scheduler import deliver_report

    payload = {
        "report_text": text,
        "category": "shopping_push",
        "user_id": user_id,
    }
    for ch in channels:
        deliver_report(payload, [ch])

    # 4. Optional PDF
    pdf_path_str: Optional[str] = None
    if pdf_output:
        export_shopping_pdf(shopping_list, week_start, pdf_output)
        pdf_path_str = str(pdf_output)

    total_items = sum(len(items) for items in shopping_list.values())
    return {
        "status": "sent",
        "channel_count": len(channels),
        "item_count": total_items,
        "pdf_path": pdf_path_str,
    }


# ─────────────────────────────────────────────────────────────
# PDF export — A5 supermarket-friendly layout
# ─────────────────────────────────────────────────────────────

def _find_cjk_font() -> Optional[Path]:
    """Mirror meal_planner's CJK font detection logic."""
    custom = os.environ.get("HEALTHFIT_PDF_FONT", "").strip()
    if custom:
        p = Path(custom)
        if p.is_file():
            return p

    candidates = [
        # Debian/Ubuntu fonts
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Synology
        "/usr/local/share/fonts/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        p = Path(path)
        if p.is_file():
            return p
    return None


def _sanitize_pdf_text(value: Any) -> str:
    """Strip emoji/symbol glyphs that CJK fonts cannot render."""
    text = str(value).replace("•", "-")
    cleaned: list[str] = []
    for char in text:
        cp = ord(char)
        if cp in (0x200D, 0xFE0F):
            continue
        if unicodedata.category(char) in {"So", "Cs"}:
            continue
        cleaned.append(char)
    return "".join(cleaned)


def export_shopping_pdf(shopping_list: dict[str, list[str]], week_start: date, output_path: Path) -> None:
    """A5 portrait, two-column layout with checkbox items per category.

    Uses the same CJK font detection as meal_planner.export_plan_pdf().
    """
    try:
        from fpdf import FPDF
    except ImportError:
        print("ERROR: fpdf2 not installed. Run: pip install fpdf2", file=sys.stderr)
        return

    font_path = _find_cjk_font()
    if not font_path:
        print(
            "ERROR: No CJK font found. Install fonts-wqy-zenhei or set HEALTHFIT_PDF_FONT.",
            file=sys.stderr,
        )
        return

    pdf = FPDF(orientation="P", unit="mm", format="A5")  # A5 = 148×210mm
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_font("CJK", "", str(font_path))
    pdf.add_font("CJK", "B", str(font_path))

    week_end = week_start + timedelta(days=6)
    title = f"採購清單  {week_start.month}/{week_start.day} – {week_end.month}/{week_end.day}"

    pdf.add_page()
    # header bar
    pdf.set_fill_color(0x1A, 0x7A, 0x5C)
    pdf.rect(0, 0, 148, 12, "F")
    pdf.set_font("CJK", "B", 12)
    pdf.set_text_color(255, 255, 255)
    pdf.set_y(3)
    pdf.cell(0, 8, _sanitize_pdf_text(title), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_text_color(0, 0, 0)

    col_w = 62   # column width (mm)
    col_x = [10, 76]   # left edge of each column

    categories = ["蛋白質", "蔬菜", "水果", "主食", "飲料/調味", "堅果/種子"]

    y_start = 22
    col_row_y = [y_start, y_start]  # col_row_y[0]=左欄, col_row_y[1]=右欄
    col_idx = 0
    PAGE_BOTTOM = 195  # A5 高 210mm，邊距 12mm，留白

    for cat in categories:
        items = shopping_list.get(cat, [])
        if not items:
            continue

        # 估算這個 category 需要的高度：header(6) + items(5 each) + gap(3)
        cat_height = 6 + len(items) * 5 + 3

        # 如果目前欄放不下整個 category，試試另一欄
        if col_row_y[col_idx] + cat_height > PAGE_BOTTOM:
            other = 1 - col_idx
            if col_row_y[other] + cat_height <= PAGE_BOTTOM:
                col_idx = other
            else:
                # 兩欄都放不下 → 新頁
                pdf.add_page()
                col_row_y = [y_start, y_start]
                col_idx = 0

        x = col_x[col_idx]
        row_y = col_row_y[col_idx]

        # category header
        emoji = _CATEGORY_EMOJI.get(cat, "")
        pdf.set_font("CJK", "B", 9)
        pdf.set_fill_color(235, 245, 235)
        pdf.set_xy(x, row_y)
        pdf.cell(col_w, 6, _sanitize_pdf_text(f"{emoji} {cat}（{len(items)} 項）"),
                 border=0, fill=True, new_x="LMARGIN", new_y="NEXT")
        row_y = pdf.get_y() + 1

        # checkbox items
        pdf.set_font("CJK", "", 8)
        for item in items:
            pdf.set_xy(x + 2, row_y)
            pdf.cell(col_w - 2, 5, _sanitize_pdf_text(f"☐ {item}"),
                     new_x="LMARGIN", new_y="NEXT")
            row_y = pdf.get_y()

        col_row_y[col_idx] = row_y + 3

        # 下一個 category 自動交替欄位
        col_idx = (col_idx + 1) % 2

    pdf.output(str(output_path))
    print(f"✅ Shopping PDF exported: {output_path}")


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def _parse_week_start(raw: str) -> date:
    """Parse --week-start as ISO date or 'next' for next Monday."""
    if raw.lower() == "next":
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7  # if today is Monday, go to next Monday
        return today + timedelta(days=days_until_monday)
    return date.fromisoformat(raw)


def cmd_shopping_push(args: argparse.Namespace) -> None:
    from db_manager import DBManager

    db = DBManager(db_path=DEFAULT_DB_PATH)

    # resolve user_id from profile
    profile_path = Path(os.environ.get("HEALTHFIT_PROFILE", Path("~/.healthfit/profile.json").expanduser()))
    user_id = ""
    if profile_path.exists():
        with open(profile_path) as f:
            profile = json.load(f)
        user_id = profile.get("user_id") or profile.get("user", {}).get("user_id", "")

    if not user_id:
        print("ERROR: Could not determine user_id from profile.", file=sys.stderr)
        sys.exit(1)

    week_start = _parse_week_start(args.week_start)
    channels = args.channels or os.environ.get("HEALTHFIT_CHANNELS", "print").split(",")
    pdf_out = Path(args.output) if args.pdf and args.output else None

    result = run_weekly_shopping_push(
        db=db,
        user_id=user_id,
        week_start=week_start,
        channels=channels,
        pdf_output=pdf_out,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly shopping list push notification")
    parser.add_argument(
        "--week-start", default="next",
        help="ISO date of the Monday (e.g. 2026-06-01) or 'next' for next Monday",
    )
    parser.add_argument(
        "--channels", "-c", nargs="+",
        help="Delivery channels: discord line print",
    )
    parser.add_argument("--pdf", action="store_true", help="Export supermarket PDF")
    parser.add_argument("--output", "-o", help="PDF output path")

    args = parser.parse_args()
    cmd_shopping_push(args)


if __name__ == "__main__":
    main()