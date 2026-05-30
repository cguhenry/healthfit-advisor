#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Literal, Optional, Sequence

Gender = Literal["M", "F", "X"]
GoalType = Literal["loss", "gain", "maintain"]

@dataclass
class MacroTargets:
    protein_g: int
    carb_g: int
    fat_g: int

@dataclass
class WeightPlan:
    goal_type: GoalType
    current_weight_kg: float
    goal_weight_kg: float
    target_weeks: int
    weekly_change_kg: float
    weekly_change_pct: float
    bmr: int
    tdee: int
    daily_calorie_target: int
    daily_calorie_delta: int
    activity_level: str
    macros: MacroTargets
    warnings: List[str] = field(default_factory=list)
    adjusted: bool = False
    requires_professional_review: bool = False
    trajectory: Optional[List[float]] = field(default=None, repr=False)
    methodology: str = (
        "Phase 1 approximation using Mifflin-St Jeor, PAL multipliers, and "
        "safety-constrained calorie planning. Not a full NIH dynamic solver."
    )

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["macros"] = asdict(self.macros)
        if self.trajectory is not None:
            payload["trajectory"] = self.trajectory
        return payload

class BWPCalculator:
    ETHNICITY_BMR_ADJUSTMENTS = {
        "east_asian": -0.05,
        "southeast_asian": -0.03,
        "south_asian": -0.04,
        "white": 0.0,
        "black": 0.02,
        "hispanic": -0.01,
    }

    PAL_COEFFICIENTS = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }

    MIN_CALORIES = {"M": 1500, "F": 1200, "X": 1350}
    LOSS_PCT_LIMIT = 0.01
    GAIN_PCT_LIMIT = 0.005
    MAX_DAILY_DEFICIT = 750
    MAX_DAILY_SURPLUS = 350
    KCAL_PER_KG = 7700
    HIGH_RISK_FLAGS = {
        "minor": "未成年使用者不應自行執行減重或增肌熱量計劃，建議由兒科/營養專業人員評估。",
        "pregnancy": "孕期或備孕期間不應自行套用一般減重熱量模型，建議先諮詢婦產科或營養師。",
        "chronic_disease": "若有糖尿病、腎臟病、心血管疾病或其他慢性病，熱量與巨量營養素目標需由醫療專業人員校正。",
        "eating_disorder": "若有飲食疾患病史或相關風險，請避免使用自動熱量限制，並優先尋求專業協助。",
    }

    def calculate_bmr(self, weight_kg: float, height_cm: float, age: int, gender: Gender, ethnicity: str = "east_asian") -> int:
        base = (10 * weight_kg) + (6.25 * height_cm) - (5 * age)
        if gender == "M":
            base += 5
        elif gender == "F":
            base -= 161
        else:
            base -= 78
        adjustment = self.ETHNICITY_BMR_ADJUSTMENTS.get(ethnicity, 0.0)
        return round(base * (1 + adjustment))

    def calculate_tdee(self, bmr: int, activity_level: str) -> int:
        return round(bmr * self.PAL_COEFFICIENTS[activity_level])

    def create_weight_plan(self, current_weight: float, goal_weight: float, target_weeks: int, tdee: int, goal_type: GoalType, activity_level: str, gender: Gender, weight_kg: Optional[float] = None, risk_flags: Optional[Sequence[str]] = None) -> WeightPlan:
        if target_weeks <= 0:
            raise ValueError("target_weeks must be positive")
        weight_kg = weight_kg or current_weight
        total_change_kg = goal_weight - current_weight
        weekly_change_kg = total_change_kg / target_weeks
        weekly_change_pct = abs(weekly_change_kg) / current_weight
        raw_daily_delta = round((total_change_kg * self.KCAL_PER_KG) / (target_weeks * 7))
        if goal_type == "maintain":
            raw_daily_delta = 0
            daily_calorie_target = tdee
        else:
            daily_calorie_target = tdee + raw_daily_delta
        macros = self.generate_macro_targets(daily_calorie_target, goal_type, weight_kg)
        plan = WeightPlan(
            goal_type=goal_type,
            current_weight_kg=current_weight,
            goal_weight_kg=goal_weight,
            target_weeks=target_weeks,
            weekly_change_kg=round(weekly_change_kg, 3),
            weekly_change_pct=round(weekly_change_pct, 4),
            bmr=0,
            tdee=tdee,
            daily_calorie_target=daily_calorie_target,
            daily_calorie_delta=raw_daily_delta,
            activity_level=activity_level,
            macros=macros,
        )
        return self.validate_plan_safety(plan, gender, risk_flags=risk_flags)

    def validate_plan_safety(self, plan: WeightPlan, gender: Gender, risk_flags: Optional[Sequence[str]] = None) -> WeightPlan:
        warnings: List[str] = []
        adjusted = False
        requires_professional_review = False
        for flag in risk_flags or ():
            message = self.HIGH_RISK_FLAGS.get(flag)
            if message:
                warnings.append(message)
                requires_professional_review = True
        if plan.goal_type == "loss" and plan.weekly_change_pct > self.LOSS_PCT_LIMIT:
            warnings.append("目標減重速度超過每週體重 1%，已調整為較安全方案。")
            adjusted = True
        if plan.goal_type == "gain" and plan.weekly_change_pct > self.GAIN_PCT_LIMIT:
            warnings.append("目標增重速度超過每週體重 0.5%，已調整為較保守盈餘。")
            adjusted = True
        if plan.goal_type == "loss" and (plan.tdee - plan.daily_calorie_target) > self.MAX_DAILY_DEFICIT:
            plan.daily_calorie_target = plan.tdee - self.MAX_DAILY_DEFICIT
            warnings.append("每日熱量赤字超過 750 kcal，已下修至安全上限。")
            adjusted = True
        if plan.goal_type == "gain" and (plan.daily_calorie_target - plan.tdee) > self.MAX_DAILY_SURPLUS:
            plan.daily_calorie_target = plan.tdee + self.MAX_DAILY_SURPLUS
            warnings.append("每日熱量盈餘過高，已下修至較保守的增肌範圍。")
            adjusted = True
        min_calories = self.MIN_CALORIES[gender]
        if plan.daily_calorie_target < min_calories:
            plan.daily_calorie_target = min_calories
            warnings.append(f"每日熱量低於最低安全值 {min_calories} kcal，已自動調整。")
            adjusted = True
        plan.macros = self.generate_macro_targets(plan.daily_calorie_target, plan.goal_type, plan.current_weight_kg)
        plan.daily_calorie_delta = plan.daily_calorie_target - plan.tdee
        plan.warnings = warnings
        plan.adjusted = adjusted
        plan.requires_professional_review = requires_professional_review
        if plan.trajectory is None:
            total_days = plan.target_weeks * 7
            if total_days > 0:
                plan.trajectory = [
                    round(
                        plan.current_weight_kg
                        + (plan.goal_weight_kg - plan.current_weight_kg)
                        * (i / total_days),
                        3,
                    )
                    for i in range(total_days + 1)
                ]
        return plan

    def generate_macro_targets(self, calories: int, goal_type: GoalType, weight_kg: float) -> MacroTargets:
        if goal_type == "loss":
            protein_ratio, fat_ratio = 0.32, 0.28
            min_protein_g = max(1.6 * weight_kg, calories * protein_ratio / 4)
        elif goal_type == "gain":
            protein_ratio, fat_ratio = 0.27, 0.23
            min_protein_g = max(1.8 * weight_kg, calories * protein_ratio / 4)
        else:
            protein_ratio, fat_ratio = 0.25, 0.30
            min_protein_g = max(1.4 * weight_kg, calories * protein_ratio / 4)
        protein_g = round(min_protein_g)
        fat_g = round((calories * fat_ratio) / 9)
        remaining_calories = calories - (protein_g * 4) - (fat_g * 9)
        carb_g = max(round(remaining_calories / 4), 0)
        return MacroTargets(protein_g=protein_g, carb_g=carb_g, fat_g=fat_g)

    def build_plan_from_profile(self, *, age: int, height_cm: float, current_weight_kg: float, goal_weight_kg: float, target_weeks: int, gender: Gender, activity_level: str, ethnicity: str = "east_asian", risk_flags: Optional[Sequence[str]] = None) -> WeightPlan:
        goal_type = self._infer_goal_type(current_weight_kg, goal_weight_kg)
        bmr = self.calculate_bmr(current_weight_kg, height_cm, age, gender, ethnicity)
        tdee = self.calculate_tdee(bmr, activity_level)
        inferred_risk_flags = list(risk_flags or [])
        if age < 18 and "minor" not in inferred_risk_flags:
            inferred_risk_flags.append("minor")
        plan = self.create_weight_plan(current_weight_kg, goal_weight_kg, target_weeks, tdee, goal_type, activity_level, gender, current_weight_kg, risk_flags=inferred_risk_flags)
        plan.bmr = bmr
        return plan

    @staticmethod
    def _infer_goal_type(current_weight_kg: float, goal_weight_kg: float) -> GoalType:
        if goal_weight_kg < current_weight_kg:
            return "loss"
        if goal_weight_kg > current_weight_kg:
            return "gain"
        return "maintain"

def main() -> None:
    sample = BWPCalculator().build_plan_from_profile(
        age=30,
        height_cm=170,
        current_weight_kg=85,
        goal_weight_kg=75,
        target_weeks=12,
        gender="M",
        activity_level="light",
    )
    print(sample.to_dict())

if __name__ == "__main__":
    main()
