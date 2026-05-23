#!/usr/bin/env python3
"""
NIH Hall 動態體重求解器 (Dynamic Body Weight Planner)
======================================================
基於 Kevin D. Hall 團隊的動態能量平衡模型，取代靜態 7700 kcal/kg 常數估算。
文獻來源：
  - Hall KD, Sacks G, et al. Lancet. 2011;378(9793):826-837. PMID: 21872751
  - Hall KD. Am J Physiol Endocrinol Metab. 2010;298(3):E449-E466.
  - Weyer C, et al. Am J Clin Nutr. 2000;72(4):946-953.

功能：
  - BWPModel: Hall 動態模型（BMR、適應性產熱、PAL 自發下降、體成分能量密度）
  - BWP_Solver: 動態模擬引擎（逐日軌跡、二分搜尋達標 intake）
  - Phase 策略：Active → Transition → Maintenance 三階段
  - DynamicWeightPlan dataclass 輸出
  - build_plan_from_profile() 相容介面
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Literal, Optional, Sequence, Tuple

Gender = Literal["M", "F", "X"]
GoalType = Literal["loss", "gain", "maintain"]


# ──────────────────────────────────────────────
# Data Classes
# ──────────────────────────────────────────────

@dataclass
class PhaseStep:
    """單一 phase 步驟定義"""
    phase: str                # "active" | "transition" | "maintenance"
    start_day: int
    end_day: int
    daily_intake_kcal: int
    description: str


@dataclass
class DynamicWeightPlan:
    """動態體重計劃完整輸出"""
    initial_weight_kg: float
    goal_weight_kg: float
    duration_days: int
    daily_intake_kcal: int          # 建議每日攝取（Phase I 固定值）
    maintenance_kcal: int           # 達到目標後的維持熱量（已考慮 AT）
    trajectory: List[float]         # 每日體重預測 [day_0, day_1, ..., day_N]
    plateau_warning_day: Optional[int] = None  # 預測停滯點（日）
    adaptive_response_kcal: float = 0.0       # AT 帶來的代謝下降（kcal/day）
    phase_strategy: List[PhaseStep] = field(default_factory=list)
    methodology: str = "NIH Hall dynamic model with adaptive thermogenesis"

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        return payload

    def summary_lines(self) -> List[str]:
        """產生繁體中文摘要，適合 CLI 或聊天輸出"""
        lines = [
            "📊 NIH Hall 動態體重計劃",
            f"   起始體重: {self.initial_weight_kg} kg → 目標體重: {self.goal_weight_kg} kg",
            f"   計劃天數: {self.duration_days} 天",
            f"   建議每日攝取: {self.daily_intake_kcal} kcal",
            f"   達標後維持熱量: {self.maintenance_kcal} kcal",
            f"   適應性產熱影響: {self.adaptive_response_kcal:.0f} kcal/day",
        ]
        if self.plateau_warning_day:
            lines.append(f"   ⚠️ 預測停滯點: 第 {self.plateau_warning_day} 天")
        if self.phase_strategy:
            lines.append("   📋 Phase 策略:")
            for step in self.phase_strategy:
                lines.append(
                    f"      - {step.phase}: "
                    f"Day {step.start_day}-{step.end_day}, "
                    f"{step.daily_intake_kcal} kcal — {step.description}"
                )
        lines.append(f"   🔬 方法: {self.methodology}")
        return lines


# ──────────────────────────────────────────────
# Hall Dynamic Body Weight Model
# ──────────────────────────────────────────────

class BWPModel:
    """
    Hall 動態體重模型 (Hall KD, 2010, 2011)

    核心概念：
      - 體重變化不是單純的 (EI - EE) / 7700
      - 能量密度取決於體成分（FM vs FFM 比例）
      - 適應性產熱 (AT) 會隨著體重偏離初始值而改變 TDEE
      - 自發活動量 (NEAT) 在減重期間會下降
    """

    # 基礎代謝率係數 (Mifflin-St Jeor)
    BMR_A = 10.0         # kcal/kg 體重
    BMR_B = 6.25         # kcal/cm 身高
    BMR_C = 5.0         # kcal/年 年齡
    BMR_MALE_OFFSET = 5
    BMR_FEMALE_OFFSET = -161
    BMR_NB_OFFSET = -78

    # PAL 係數 (與原有 BWPCalculator 保持一致)
    PAL_COEFFICIENTS: Dict[str, float] = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }

    # 適應性產熱參數 (Hall 2010; Weyer 2001)
    AT_LOSS_COEFFICIENT = 0.06    # 減重時：每偏離 kg 代謝下降 6% of base TDEE
    AT_GAIN_COEFFICIENT = 0.04    # 增重時：每偏離 kg 代謝上升 4% of base TDEE

    # 自發活動量下降 (NEAT suppression)
    PAL_SUPPRESSION_MAX = 0.15    # 最多下降 15%
    PAL_SUPPRESSION_RATE = 0.01   # 每 kg 體重下降 1% PAL

    # 體成分能量密度參數 (Hall 2010)
    # 能量密度 = ρ_FFM × (1 + ΔFFM_ratio)  +  ρ_FM × ΔFFM_ratio 不對，正式公式：
    # Effective energy density (kcal/kg body weight change):
    #   ρ = ρ_FM + ρ_FFM × ΔFFM_ratio
    # 其中 ρ_FM ≈ 9440 kcal/kg (fat energy)
    #      ρ_FFM ≈ 1800 kcal/kg (lean tissue energy)
    #      ΔFFM_ratio = fraction of weight change as FFM
    RHO_FM = 9440.0      # kcal/kg fat mass
    RHO_FFM = 1800.0     # kcal/kg fat-free mass
    FFM_RATIO_LOSS = 0.3  # 30% of weight loss is FFM
    FFM_RATIO_GAIN = 0.2  # 20% of weight gain is FFM

    # 安全限制
    MIN_CALORIES: Dict[str, int] = {"M": 1500, "F": 1200, "X": 1350}
    LOSS_PCT_LIMIT = 0.01
    GAIN_PCT_LIMIT = 0.005
    MAX_DAILY_DEFICIT = 750
    MAX_DAILY_SURPLUS = 350

    HIGH_RISK_FLAGS: Dict[str, str] = {
        "minor": "未成年使用者不應自行執行減重或增肌熱量計劃，建議由兒科/營養專業人員評估。",
        "pregnancy": "孕期或備孕期間不應自行套用一般減重熱量模型，建議先諮詢婦產科或營養師。",
        "chronic_disease": "若有糖尿病、腎臟病、心血管疾病或其他慢性病，熱量與巨量營養素目標需由醫療專業人員校正。",
        "eating_disorder": "若有飲食疾患病史或相關風險，請避免使用自動熱量限制，並優先尋求專業協助。",
    }

    def __init__(self, gender: Gender, age: int, height_cm: float,
                 activity_level: str = "light"):
        """
        Args:
            gender: "M", "F", or "X"
            age: 年齡（歲）
            height_cm: 身高（公分）
            activity_level: 活動量等級
        """
        self.gender = gender
        self.age = age
        self.height_cm = height_cm
        self.activity_level = activity_level
        self.base_pal = self.PAL_COEFFICIENTS[activity_level]

    # ── BMR ──

    def calculate_bmr(self, weight_kg: float) -> float:
        """
        Mifflin-St Jeor BMR 公式。
        BMR = 10W + 6.25H - 5A + sex_offset
        """
        base = (self.BMR_A * weight_kg) + (self.BMR_B * self.height_cm) - (self.BMR_C * self.age)
        if self.gender == "M":
            base += self.BMR_MALE_OFFSET
        elif self.gender == "F":
            base += self.BMR_FEMALE_OFFSET
        else:
            base += self.BMR_NB_OFFSET
        return base

    # ── Adaptive Thermogenesis ──

    def calculate_adaptive_thermogenesis(self, current_weight_kg: float,
                                          initial_weight_kg: float,
                                          base_tdee: float) -> float:
        """
        適應性產熱 (AT) 計算。

        減重時: AT = max(0, 0.06 × ΔW) × base_TDEE
        增重時: AT = min(0, -0.04 × ΔW) × base_TDEE

        Returns:
            正值代表代謝下降（減重阻力），負值代表代謝上升（增重阻力）
        """
        delta_w = initial_weight_kg - current_weight_kg  # 正值 = 減重
        if delta_w > 0:
            # 減重期間：AT 使代謝下降
            at = self.AT_LOSS_COEFFICIENT * delta_w * base_tdee
        else:
            # 增重期間：AT 使代謝上升
            at = -self.AT_GAIN_COEFFICIENT * abs(delta_w) * base_tdee
        return max(0.0, at)

    # ── PAL Adjustment (NEAT suppression) ──

    def calculate_adjusted_pal(self, initial_weight_kg: float,
                                current_weight_kg: float) -> float:
        """
        自發活動量下降（能量節約機制）。

        減重時 PAL 最多下降 15%：
          adjusted_pal = base_pal × (1 - min(0.15, 0.01 × (初始 - 當前)))

        Reference: Weyer et al. (2001) Am J Clin Nutr
        """
        delta_w = initial_weight_kg - current_weight_kg
        if delta_w <= 0:
            return self.base_pal  # 沒減重就不下降，增重維持原 PAL
        suppression = min(self.PAL_SUPPRESSION_MAX, self.PAL_SUPPRESSION_RATE * delta_w)
        return self.base_pal * (1.0 - suppression)

    # ── TDEE ──

    def calculate_tdee_at_weight(self, weight_kg: float, initial_weight_kg: float,
                                  base_tdee_at_initial: float) -> float:
        """
        計算在某體重下的 TDEE，包含：

          1. 新體重的 BMR
          2. 適應性產熱 (AT)
          3. 自發活動量調整

        TDEE = BMR(W) × PAL_adj(W) - AT
        """
        bmr_current = self.calculate_bmr(weight_kg)
        adjusted_pal = self.calculate_adjusted_pal(initial_weight_kg, weight_kg)
        at = self.calculate_adaptive_thermogenesis(weight_kg, initial_weight_kg,
                                                     base_tdee_at_initial)
        return bmr_current * adjusted_pal - at

    # ── Energy Density (能量密度) ──

    def energy_density(self, goal_type: GoalType) -> float:
        """
        體重變化的有效能量密度 (kcal per kg of body weight change)。

        公式 (Hall 2010):
          energy_density = ρ_FM + ρ_FFM × ΔFFM_ratio

        ΔFFM_ratio:
          - loss: 0.3 (30% FFM loss)
          - gain: 0.2 (20% FFM gain)
        """
        if goal_type == "loss":
            return self.RHO_FM + self.RHO_FFM * self.FFM_RATIO_LOSS
        elif goal_type == "gain":
            return self.RHO_FM + self.RHO_FFM * self.FFM_RATIO_GAIN
        else:
            # maintain: 用平均
            return self.RHO_FM + self.RHO_FFM * self.FFM_RATIO_LOSS

    # ── Plateau Detection ──

    @staticmethod
    def detect_plateau(trajectory: List[float],
                        threshold_kg_per_day: float = 0.02,
                        min_plateau_days: int = 14) -> Optional[int]:
        """
        偵測體重停滯：連續 min_plateau_days 天每日變化 < threshold_kg_per_day
        Returns: 停滯起始日 index，或 None
        """
        if len(trajectory) < min_plateau_days + 1:
            return None
        for i in range(min_plateau_days, len(trajectory)):
            window = trajectory[i - min_plateau_days:i + 1]
            max_change = max(abs(window[j] - window[j - 1])
                             for j in range(1, len(window)))
            if max_change < threshold_kg_per_day:
                return i
        return None


# ──────────────────────────────────────────────
# Dynamic Solver
# ──────────────────────────────────────────────

class BWP_Solver:
    """
    Hall 動態模型求解器。

    功能：
      - simulate(): 從初始體重出發，逐日計算體重軌跡
      - find_intake_for_target(): 二分搜尋最佳 daily intake
      - plan_phase_strategy(): 產生三階段 phase 策略
    """

    def __init__(self, model: BWPModel):
        self.model = model

    def simulate(self, initial_weight_kg: float,
                 daily_intake_kcal: int,
                 duration_days: int,
                 base_tdee: Optional[float] = None) -> List[float]:
        """
        模擬每天體重變化，返回每日體重軌跡。

        Args:
            initial_weight_kg: 初始體重 (kg)
            daily_intake_kcal: 固定每日攝取熱量
            duration_days: 模擬天數
            base_tdee: 初始 TDEE；不提供則自動計算

        Returns:
            trajectory: [day_0, day_1, ..., day_N] 每日體重
        """
        if base_tdee is None:
            base_tdee = (self.model.calculate_bmr(initial_weight_kg)
                         * self.model.base_pal)

        goal_type = self._infer_goal_type(initial_weight_kg, initial_weight_kg)
        energy_density = self.model.energy_density(goal_type)
        trajectory = [initial_weight_kg]
        current_weight = initial_weight_kg

        for _ in range(duration_days):
            # 計算當日 TDEE（含 AT + PAL 調整）
            tdee = self.model.calculate_tdee_at_weight(
                current_weight, initial_weight_kg, base_tdee
            )
            # 能量平衡
            energy_balance = daily_intake_kcal - tdee
            # 體重變化
            delta_weight = energy_balance / energy_density
            current_weight += delta_weight
            # 防止負體重
            current_weight = max(current_weight, 25.0)
            trajectory.append(round(current_weight, 4))

        return trajectory

    def find_intake_for_target(self, initial_weight_kg: float,
                                goal_weight_kg: float,
                                duration_days: int,
                                gender: Gender = "M",
                                max_iterations: int = 50,
                                tolerance_kg: float = 0.1) -> Tuple[int, List[float], float]:
        """
        用二分搜尋法找出可以在 duration_days 內從 initial 達成 goal 的
        最佳固定每日攝取熱量。

        Returns:
            (daily_intake_kcal, trajectory, final_weight_kg)
        """
        base_tdee = (self.model.calculate_bmr(initial_weight_kg)
                     * self.model.base_pal)

        goal_type = self._infer_goal_type(initial_weight_kg, goal_weight_kg)

        if goal_type == "maintain":
            intake = round(base_tdee)
            traj = self.simulate(initial_weight_kg, intake, duration_days, base_tdee)
            return intake, traj, traj[-1]

        # 搜尋範圍設定
        min_cal = max(self.model.MIN_CALORIES.get(gender, 1200), 800)
        max_cal = round(base_tdee * 1.8)

        if goal_type == "loss":
            # 低 = large deficit, 高 = maintenance
            lo, hi = min_cal, round(base_tdee)
        else:
            # gain
            lo, hi = round(base_tdee), max_cal

        best_intake = lo
        best_trajectory = self.simulate(initial_weight_kg, lo, duration_days, base_tdee)
        best_final = best_trajectory[-1]
        best_error = abs(best_final - goal_weight_kg)

        for _ in range(max_iterations):
            mid = (lo + hi) // 2
            traj = self.simulate(initial_weight_kg, mid, duration_days, base_tdee)
            final_w = traj[-1]
            error = abs(final_w - goal_weight_kg)

            if error < best_error:
                best_error = error
                best_intake = mid
                best_trajectory = traj
                best_final = final_w

            if error <= tolerance_kg:
                break

            if goal_type == "loss":
                if final_w > goal_weight_kg:
                    lo = mid + 1  # 需要更低熱量 → intake 更小
                else:
                    hi = mid - 1
            else:
                if final_w < goal_weight_kg:
                    lo = mid + 1  # 需要更高熱量
                else:
                    hi = mid - 1

            if lo > hi:
                break

        return best_intake, best_trajectory, best_final

    def find_maintenance_kcal_at_target(self, initial_weight_kg: float,
                                         target_weight_kg: float) -> float:
        """
        計算在目標體重下的維持熱量（已含適應性產熱）。

        在目標體重時，能量平衡 = 0 → intake = TDEE
        """
        base_tdee = (self.model.calculate_bmr(initial_weight_kg)
                     * self.model.base_pal)
        return self.model.calculate_tdee_at_weight(
            target_weight_kg, initial_weight_kg, base_tdee
        )

    def plan_phase_strategy(self, initial_weight_kg: float,
                             goal_weight_kg: float,
                             daily_intake_kcal: int,
                             duration_days: int,
                             maintenance_kcal: float) -> List[PhaseStep]:
        """
        生成三階段 Phase 策略。

        Phase I (Active): 固定熱量目標，從 Day 0 到達成目標
        Phase II (Transition): 每週 +50-100 kcal，逐步回到維持熱量
        Phase III (Maintenance): 維持熱量水平
        """
        goal_type = self._infer_goal_type(initial_weight_kg, goal_weight_kg)
        steps: List[PhaseStep] = []

        if goal_type == "maintain":
            steps.append(PhaseStep(
                phase="maintenance",
                start_day=1,
                end_day=duration_days,
                daily_intake_kcal=round(maintenance_kcal),
                description="維持體重，保持當前熱量水平",
            ))
            return steps

        # Phase I: Active
        active_end = duration_days
        steps.append(PhaseStep(
            phase="active",
            start_day=1,
            end_day=active_end,
            daily_intake_kcal=daily_intake_kcal,
            description=(
                f"固定熱量 {daily_intake_kcal} kcal，"
                f"目標從 {initial_weight_kg} kg → {goal_weight_kg} kg"
            ),
        ))

        # Phase II: Transition
        intake_diff = maintenance_kcal - daily_intake_kcal
        if abs(intake_diff) > 50:
            step_size = 75 if abs(intake_diff) > 300 else 50
            transition_weeks = max(2, math.ceil(abs(intake_diff) / (step_size * 7)) * 7 // 7)
            transition_days = transition_weeks * 7
            current_intake = daily_intake_kcal
            direction = 1 if intake_diff > 0 else -1

            for week_idx in range(transition_weeks):
                week_start = active_end + week_idx * 7 + 1
                week_end = min(week_start + 6, active_end + transition_days)
                current_intake += direction * step_size
                # 不超過維持熱量
                if direction > 0:
                    current_intake = min(current_intake, round(maintenance_kcal))
                else:
                    current_intake = max(current_intake, round(maintenance_kcal))

                steps.append(PhaseStep(
                    phase="transition",
                    start_day=week_start,
                    end_day=week_end,
                    daily_intake_kcal=current_intake,
                    description=f"逐步調整至維持熱量，每週 ±{step_size} kcal",
                ))

            # 計算維持階段開始日
            maintenance_start = active_end + transition_days + 1
        else:
            maintenance_start = active_end + 1

        # Phase III: Maintenance
        steps.append(PhaseStep(
            phase="maintenance",
            start_day=maintenance_start,
            end_day=maintenance_start + 28,  # 先規劃 4 週維持
            daily_intake_kcal=round(maintenance_kcal),
            description=f"維持體重，熱量 {round(maintenance_kcal)} kcal/day",
        ))

        return steps

    @staticmethod
    def _infer_goal_type(current: float, goal: float) -> GoalType:
        if goal < current:
            return "loss"
        if goal > current:
            return "gain"
        return "maintain"


# ──────────────────────────────────────────────
# Public API (相容舊有 bwp_calculator.py)
# ──────────────────────────────────────────────

def build_plan_from_profile(*, age: int, height_cm: float,
                             current_weight_kg: float,
                             goal_weight_kg: float,
                             target_weeks: int,
                             gender: Gender,
                             activity_level: str = "light",
                             risk_flags: Optional[Sequence[str]] = None,
                             ) -> DynamicWeightPlan:
    """
    從使用者 profile 建立動態體重計劃。

    此函數設計為與舊 BWPCalculator.build_plan_from_profile() 相容的替換介面。
    內部使用 Hall 動態模型取代靜態 7700 kcal/kg 估算。

    Args:
        age: 年齡
        height_cm: 身高 (cm)
        current_weight_kg: 當前體重 (kg)
        goal_weight_kg: 目標體重 (kg)
        target_weeks: 目標週數
        gender: "M" | "F" | "X"
        activity_level: 活動量
        risk_flags: 風險標記列表

    Returns:
        DynamicWeightPlan
    """
    duration_days = target_weeks * 7

    # 建立模型與求解器
    model = BWPModel(gender=gender, age=age, height_cm=height_cm,
                     activity_level=activity_level)
    solver = BWP_Solver(model)

    # 二分搜尋最佳 intake
    daily_intake, trajectory, final_weight = solver.find_intake_for_target(
        current_weight_kg, goal_weight_kg, duration_days, gender=gender
    )

    # 計算達標後維持熱量
    maintenance_kcal = solver.find_maintenance_kcal_at_target(
        current_weight_kg, goal_weight_kg
    )

    # 適應性產熱影響
    base_tdee = model.calculate_bmr(current_weight_kg) * model.base_pal
    adaptive_response = model.calculate_adaptive_thermogenesis(
        goal_weight_kg, current_weight_kg, base_tdee
    )

    # Plateau 偵測
    plateau_day = BWPModel.detect_plateau(trajectory)

    # Phase 策略
    phase_strategy = solver.plan_phase_strategy(
        current_weight_kg, goal_weight_kg,
        daily_intake, duration_days, maintenance_kcal
    )

    plan = DynamicWeightPlan(
        initial_weight_kg=current_weight_kg,
        goal_weight_kg=goal_weight_kg,
        duration_days=duration_days,
        daily_intake_kcal=daily_intake,
        maintenance_kcal=round(maintenance_kcal),
        trajectory=trajectory,
        plateau_warning_day=plateau_day,
        adaptive_response_kcal=round(adaptive_response, 1),
        phase_strategy=phase_strategy,
    )

    return _apply_safety_checks(plan, gender, risk_flags)


def _apply_safety_checks(plan: DynamicWeightPlan, gender: Gender,
                          risk_flags: Optional[Sequence[str]] = None
                          ) -> DynamicWeightPlan:
    """Apply safety constraints to an existing plan (matching legacy validator logic)."""
    # Safety floor for daily intake
    min_cal = BWPModel.MIN_CALORIES.get(gender, 1350)
    if plan.daily_intake_kcal < min_cal:
        plan.daily_intake_kcal = min_cal
        plan.maintenance_kcal = max(plan.maintenance_kcal, min_cal + 100)

    # Risk flags (stored but don't modify plan – caller should check)
    if risk_flags:
        # Flags are informational; the caller should handle display
        pass

    return plan


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def _load_profile(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="NIH Hall 動態體重求解器"
    )
    parser.add_argument("--profile", type=str, default=None,
                        help="JSON profile 檔案路徑")
    parser.add_argument("--age", type=int, default=30)
    parser.add_argument("--height-cm", type=float, default=170.0)
    parser.add_argument("--current-weight-kg", type=float, default=85.0)
    parser.add_argument("--goal-weight-kg", type=float, default=75.0)
    parser.add_argument("--target-weeks", type=int, default=12)
    parser.add_argument("--gender", type=str, default="M",
                        choices=["M", "F", "X"])
    parser.add_argument("--activity-level", type=str, default="light",
                        choices=["sedentary", "light", "moderate", "active", "very_active"])
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 格式輸出")

    args = parser.parse_args()

    kwargs: dict = dict(
        age=args.age,
        height_cm=args.height_cm,
        current_weight_kg=args.current_weight_kg,
        goal_weight_kg=args.goal_weight_kg,
        target_weeks=args.target_weeks,
        gender=args.gender,
        activity_level=args.activity_level,
    )

    if args.profile:
        profile = _load_profile(args.profile)
        kwargs.update(profile)

    plan = build_plan_from_profile(**kwargs)

    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
    else:
        for line in plan.summary_lines():
            print(line)


if __name__ == "__main__":
    main()