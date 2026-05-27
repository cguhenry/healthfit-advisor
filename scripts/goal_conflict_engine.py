#!/usr/bin/env python3
"""
goal_conflict_engine.py — Phase 8 Feature 3: Goal Conflict Detection.

Analyzes user nutrition/food goals for internal contradictions and
produces human-readable warnings with prioritized suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal, Optional


ConflictSeverity = Literal["info", "warning", "critical"]


@dataclass
class GoalConflict:
    code: str
    severity: ConflictSeverity
    message: str
    suggestion: str

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_goal_conflicts(
    *,
    daily_calories: int,
    protein_target_g: Optional[int] = None,
    carb_target_g: Optional[int] = None,
    fat_target_g: Optional[int] = None,
    restrictions: Optional[list[str]] = None,
    meal_preference: Optional[str] = None,
    cuisine_pref: Optional[str] = None,
    require_low_gi: bool = False,
    require_low_budget: bool = False,
    require_convenience: bool = False,
    avoid_recent_repetition: bool = False,
) -> list[GoalConflict]:
    """Analyze a set of nutrition/food goals for internal conflicts.

    Args:
        daily_calories:        Daily calorie target in kcal.
        protein_target_g:       Daily protein target in grams.
        carb_target_g:          Daily carb target in grams (unused currently, reserved).
        fat_target_g:           Daily fat target in grams (unused currently, reserved).
        restrictions:          List of dietary restriction tags.
        meal_preference:        User's meal style preference (e.g. "simple", "balanced").
        cuisine_pref:           Cuisine preference string.
        require_low_gi:        True if user asked for low-GI foods.
        require_low_budget:     True if budget constraint is present.
        require_convenience:   True if convenience/quick-prep is a priority.
        avoid_recent_repetition: True if user wants to avoid repeating recent foods.

    Returns:
        List of GoalConflict objects ordered by severity (critical > warning > info).
    """
    restrictions = restrictions or []
    conflicts: list[GoalConflict] = []

    # ── High protein + low calorie ────────────────────────────────────────
    if protein_target_g and daily_calories:
        protein_cal = protein_target_g * 4
        protein_ratio = protein_cal / daily_calories

        if protein_ratio >= 0.38:
            conflicts.append(GoalConflict(
                code="high_protein_low_calorie",
                severity="warning",
                message=(
                    f"蛋白質目標 {protein_target_g}g 佔每日熱量約 {protein_ratio:.0%}，"
                    "在低熱量條件下菜色選擇會明顯變少。"
                ),
                suggestion="建議優先使用雞胸、魚、蛋、豆腐、無糖豆漿等高蛋白低脂選項。",
            ))

    # ── Low GI + convenience store ────────────────────────────────────────
    if require_low_gi and require_convenience:
        conflicts.append(GoalConflict(
            code="low_gi_convenience",
            severity="info",
            message="低 GI 與便利商店外食可同時達成，但主食選擇會受限。",
            suggestion="建議用地瓜、燕麥、沙拉、豆漿取代飯糰、麵包、甜飲。",
        ))

    # ── Budget + low GI + high protein ────────────────────────────────────
    if require_low_budget and require_low_gi and protein_target_g and protein_target_g >= 100:
        conflicts.append(GoalConflict(
            code="budget_low_gi_high_protein",
            severity="warning",
            message="低預算、低 GI、高蛋白三個目標同時存在時，餐點彈性較低。",
            suggestion="建議以蛋、豆腐、雞胸、冷凍蔬菜、地瓜作為基礎模板。",
        ))

    # ── Simple meals + avoid repetition ───────────────────────────────────
    if avoid_recent_repetition and meal_preference == "simple":
        conflicts.append(GoalConflict(
            code="simple_but_no_repetition",
            severity="info",
            message="簡單備餐通常依賴重複食材，但你同時要求避免重複。",
            suggestion="建議允許主蛋白重複，但變化調味與蔬菜。",
        ))

    # ── Vegetarian + high protein ─────────────────────────────────────────
    if "vegetarian" in restrictions and protein_target_g and protein_target_g >= 110:
        conflicts.append(GoalConflict(
            code="vegetarian_high_protein",
            severity="warning",
            message="素食與高蛋白目標可行，但需要更仔細安排豆製品、蛋奶或蛋白補充來源。",
            suggestion="建議明確標示可接受蛋奶素、全素或可否使用蛋白粉。",
        ))

    # ── Ordering: critical → warning → info ────────────────────────────────
    _severity_order = {"critical": 0, "warning": 1, "info": 2}
    conflicts.sort(key=lambda c: _severity_order.get(c.severity, 9))
    return conflicts