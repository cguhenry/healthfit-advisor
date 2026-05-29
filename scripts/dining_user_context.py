#!/usr/bin/env python3
"""
dining_user_context.py — Phase 2A: 從 DB 載入使用者今日外食上下文

自動從 calorie_tracker + weight_plan 取得：
- 今日剩餘熱量
- 蛋白質缺口
- goal_type
- 是否低 GI
"""

from __future__ import annotations

import json

from dataclasses import dataclass, asdict
from datetime import date

from calorie_tracker import get_calorie_progress
from db_manager import DBManager


@dataclass
class DiningUserContext:
    user_id: str
    target_date: str
    calories_remaining: float
    protein_gap_g: float
    goal_type: str = "loss"
    require_low_gi: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def load_dining_user_context(
    *,
    db_path: str | None = None,
    user_id: str,
    target_date: str | None = None,
) -> DiningUserContext:
    target_date = target_date or date.today().isoformat()

    db = DBManager(db_path) if db_path else DBManager()

    progress = get_calorie_progress(db, user_id, log_date=target_date)

    calories_remaining = float(progress.get("calories_remaining") or 0)
    protein_gap_g = float(progress.get("protein_remaining_g") or 0)

    goal_type = "loss"
    require_low_gi = False

    plan = db.get_active_plan(user_id)
    if not plan:
        raise RuntimeError(
            f"user_id={user_id} 沒有 active weight plan。"
            "請先建立計畫（建議用 Phase 1 的 intake flow），"
            "或改用 --remaining-calories 手動指定。"
        )
    # ── dietary_restrictions 解析 ─────────────────────────────────────────
    def _parse_dietary_restrictions(value: object) -> list[str]:
        """Parse dietary_restrictions from DB (list, JSON string, or plain text)."""
        if value is None:
            return []

        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]

        text = str(value).strip()
        if not text:
            return []

        # Try JSON array
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass

        # Fallback: comma-separated (backward compatible)
        return [
            x.strip()
            for x in text.replace("\uff0c", ",").replace("，", ",").split(",")
            if x.strip()
        ]

    def _requires_low_gi(restrictions: list[str]) -> bool:
        """Check if restrictions indicate low-GI / blood-sugar control need."""
        normalized = {x.lower() for x in restrictions}
        return bool(
            normalized
            & {
                "low_gi",
                "low-gi",
                "diabetes",
                "blood_sugar_control",
                "血糖控制",
                "低gi",
                "低升糖",
            }
        )

    plan_dict = dict(plan)
    goal_type = str(plan_dict.get("goal_type") or "loss")

    restrictions = _parse_dietary_restrictions(plan_dict.get("dietary_restrictions"))
    require_low_gi = _requires_low_gi(restrictions)

    return DiningUserContext(
        user_id=user_id,
        target_date=target_date,
        calories_remaining=calories_remaining,
        protein_gap_g=protein_gap_g,
        goal_type=goal_type,
        require_low_gi=require_low_gi,
    )