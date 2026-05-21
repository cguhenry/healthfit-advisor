# HealthFit Advisor Implementation Notes

## Phase 1 Scope

- 完成 skill scaffold
- 完成單人 profile 管理
- 完成 BMR/TDEE/熱量目標/巨量營養素計算
- 完成安全檢查與警告調整
- 完成開發期 storage abstraction 與 schema 草案
- 完成 Phase 1 intake flow：profile create/update、active plan persistence、缺欄位驗證
- 完成高風險安全旗標：minor、pregnancy、chronic_disease、eating_disorder

## Design Corrections From Plan Review

1. 「NIH BWP」與「Mifflin-St Jeor + PAL」不是同一件事。
   - Phase 1 先明確採用工程近似版規劃器。
   - 若要完整重現 NIH/Hall 動態模型，需另做 solver 與 longitudinal validation。
2. 單人模式設定檔應提前到 Phase 1，而不是放到 Phase 4。
3. PostgreSQL 不應成為 skill 啟動前提。
   - 開發與測試預設走 SQLite。
   - 部署到有 DB 的 agent runtime 再切 PostgreSQL。
4. 醫療安全 guardrails 要前置。
   - 極端熱量赤字/盈餘要自動降級
   - 加入轉介提醒條件
5. Active plan persistence 只保存安全調整後方案。
   - 舊 active plan 會被停用
   - 新方案保留計算警告與 `requires_professional_review`

## Phase 1 Agent Intake Payload

Minimum JSON fields:

```json
{
  "display_name": "Henry",
  "gender": "M",
  "age": 30,
  "height_cm": 170,
  "current_weight_kg": 85,
  "activity_level": "light",
  "goal_weight_kg": 78,
  "target_weeks": 16
}
```

Optional fields:

- `ethnicity`: defaults to `east_asian`
- `target_date`: stored with the active plan
- `risk_flags`: `minor`, `pregnancy`, `chronic_disease`, `eating_disorder`

## Publication Strategy

The canonical publishable repository root is `skills/healthfit-advisor/`.

Rationale:

- OpenClaw loads the skill from this directory.
- Keeping implementation and GitHub publication in the same root avoids code duplication.
- `projects/healthfit-advisor/` remains the internal planning/progress workspace.
- If public-facing docs need to diverge from internal notes, put public docs under this skill directory and keep private planning files in `projects/`.

## Deferred To Later Phases

- 台灣食品資料庫匯入
- USDA 整合
- 菜單推薦
- 圖像辨識
- 日報/週報與排程
