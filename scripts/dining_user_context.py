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
    if plan:
        plan_dict = dict(plan)
        goal_type = str(plan_dict.get("goal_type") or "loss")

        # 從 dietary_restrictions 判斷低 GI 需求
        restrictions = str(plan_dict.get("dietary_restrictions") or "")
        if "low_gi" in restrictions or "diabetes" in restrictions or "血糖" in restrictions:
            require_low_gi = True

    return DiningUserContext(
        user_id=user_id,
        target_date=target_date,
        calories_remaining=calories_remaining,
        protein_gap_g=protein_gap_g,
        goal_type=goal_type,
        require_low_gi=require_low_gi,
    )