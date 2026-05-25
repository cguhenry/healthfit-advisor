---
name: healthfit-advisor
description: 提供健康減重、增肌、維持體重的技能化工作流程，適合用在 AI Agent 需要建立個人健康檔案、計算 BMR/TDEE、評估安全減重或增肌速度、產生每日熱量與巨量營養素目標、整理單人健康追蹤資料，或規劃後續飲食/影像辨識模組時使用。當需求包含「減重」「增肌」「熱量」「TDEE」「BMR」「飲食計劃」「體重目標」「巨量營養素」「健康管理 skill」等情境時使用。
---

# HealthFit Advisor

建立以安全性為優先的健康體重管理流程。先完成個人檔案、基礎能量估算與目標安全檢查，再進入飲食建議、影像分析與追蹤報告。

## 維護狀態

- 目前功能覆蓋 Phase 1–7。
- 文件以中文為主，英文保留在少數程式名與介面名。
- 最新維護輪次已同步 README、schema、測試與 phase progress 文件。

## Core Workflow

1. 先判斷需求屬於哪一類：
   - 新使用者建檔
   - 既有資料的體重目標重算
   - 熱量/巨量營養素快速估算
   - 外食或菜單建議
   - 後續 phase 的規劃或擴充
2. 若是首次使用，先建立或讀取本機單人設定檔 `~/.healthfit/profile.json`。
3. 若需要完整 Phase 1 intake，優先使用 `scripts/intake_flow.py`：
   - 驗證必要欄位
   - 建立或更新 profile
   - 計算安全調整後的 active plan
   - 寫入 SQLite 開發資料庫
4. 用 `scripts/bwp_calculator.py` 計算：
   - BMR
   - TDEE
   - 目標週變化率
   - 每日熱量目標
   - 蛋白質/脂肪/碳水目標
5. 一定執行安全檢查：
   - 每週體重變化是否超過安全範圍
   - 每日熱量是否低於最低安全值
   - 蛋白質是否低於最低建議
   - 是否有未成年、孕期、慢性病或飲食疾患風險
6. 輸出結果時要明示：
   - 這是 Phase 1 的工程近似版，不是假裝完整重現 NIH 線上求解器
   - 若使用者有慢性病、孕期、飲食疾患或未成年，應建議轉專業醫療評估
7. 若需求是「要吃什麼」「外食怎麼選」「超商/自助餐/餐廳建議」，用 `scripts/menu_advisor.py`：
   - 讀取或要求 cuisine/location/meal type
   - 使用 active plan 的 daily calorie target 與 protein target
   - 若已知今日剩餘熱量或已攝取蛋白質，優先用剩餘缺口
   - 輸出主建議、替代選項、避免項目與搭配理由
8. 若需求是重複食品查詢、常見食材估算或批次營養查詢，優先用 `scripts/food_db_cache.py` 包住 `food_db_lookup.py`，避免重複打 DB。
9. 若需求涉及個資匯出、刪除、資料可攜或合規檢查，用 `scripts/privacy_manager.py`，不要手寫散落 SQL。
10. 大幅修改跨 phase 流程後，用 `scripts/integration_test.py` 做 smoke test，再回頭跑單元測試。

## Phase 1 Boundaries

- Phase 1 只實作單人模式。
- Phase 1 先用本機檔案與 SQLite-ready schema/abstraction，避免被執行環境是否有 PostgreSQL 阻塞。
- `scripts/db_manager.py` 目前是 **SQLite-specific implementation**，包含 `PRAGMA` 與 SQLite DDL/UPSERT 假設；若要接 PostgreSQL，需另做 adapter 或 ORM 層，不是直接切 backend。
- 不在 Phase 1 直接承諾圖片辨識、菜單 OCR、食品資料庫完整匯入。

## Phase 4 Boundaries

- Phase 4 expects Phase 3 analysis results as input dicts (not raw images).
- Phase 3 → Phase 4 handoff contract is versioned in `references/phase3_output_schema.json`; `scripts/calorie_tracker.py` normalizes and validates this payload before DB writes.
- `log_meal_analysis()` writes individual food rows plus an optional `___MEAL_TOTAL___` row.
- `log_meal_analysis()` itself does not recompute summaries; `upsert_daily_summary()` performs an explicit full-day recompute from `food_logs`.
- Full recompute is acceptable for current single-user/local scope, but should be replaced with dirty-flag or incremental aggregation before scale-out.
- History comparison queries `food_logs` directly; uses trailing 7-day average when data is sparse.
- Calorie progress reads targets from the active weight_plan (fallback to daily_summaries).
- Human-readable formatters exist for CLI and agent reply use.

## Phase 3 Boundaries

- Vision capability check is model ID-based; no Vision API calls.
- Image analysis is delegated to the agent framework's own LLM.
- Prompt templates (`build_llm_prompt()`) and response schema are skill-provided.
- Native FOOD output intended for Phase 4 ingestion is documented in `references/phase3_output_schema.json`.
- Confidence tiers classify results: ≥85% high, 60–85% medium, <60% low (auto-flagged).
- Low-confidence items produce warnings asking user to confirm manually.
- Not yet integrated with `calorie_tracker.py` for DB write-back; that is Phase 4.

## Phase 5 Boundaries

- Daily scoring follows the HealthFit rubric: 100-point base with deductions for calorie over/under, protein, fiber, sodium, sugar, and missing meals.
- Weekly scoring uses 50% daily score average + 20% weight trend + 15% food diversity + 15% record completeness.
- Weekly score requires logged weight data for an accurate weight trend component.
- If the week has no weight data, `scoring_engine.py` marks that component unavailable and proportionally redistributes the missing 20% instead of silently scoring it as zero.
- Daily and weekly reports aggregate data from food_logs, daily_summaries, and weight_logs.
- Reports include text-based calorie trend charts, per-meal breakdowns, and actionable recommendations.
- All scores are persisted to score_events, daily_summaries, and weekly_summaries.
- `report_generator.py` depends on `calorie_tracker.py` and `scoring_engine.py`.

## Files To Use

- `scripts/scoring_engine.py` — Phase 5 daily & weekly scoring engine
- `scripts/report_generator.py` — Phase 5 daily & weekly report generator
- `scripts/bwp_calculator.py`
  - 體重目標與巨量營養素計算核心
- `scripts/profile_manager.py`
  - 單人模式設定檔建立、讀取、更新
- `scripts/db_manager.py`
  - 開發期儲存抽象，預設 SQLite；可初始化 schema、upsert profile、保存/讀取 active plan
- `scripts/intake_flow.py`
  - Phase 1 agent-facing intake procedure，串接 profile、calculator、database
- `scripts/plan_formatter.py`
  - 將 plan payload 轉成可讀摘要，適合用於聊天回覆
- `scripts/menu_advisor.py`
  - Phase 2 飲食諮詢引擎，根據料理類型、用餐地點、餐別與熱量/蛋白缺口推薦外食搭配
- `scripts/diet_dialogue.py`
  - Phase 2 對話引導樹，解析 cuisine/location/meal 自然語言，支援多輪 state 持續
- `scripts/calorie_tracker.py`
  - Phase 4 熱量追蹤模組，將 Phase 3 分析結果寫入 food_logs、驗證/正規化交接 payload、提供 daily summary 彙總、歷史對比（vs 昨日/上週/7天平均/計劃起始日）與滾動趨勢
- `scripts/exercise_tracker.py`
  - Phase 6 運動記錄追蹤，MET 法估算熱量消耗、動態熱量配額調整（loss 50%/gain 100%/maintain 75% eat-back）、整合 scoring engine
- `scripts/health_alerts.py`
  - Phase 6 健康警示系統，偵測 7 種徵兆：低熱量連續日、快速減重、蛋白質不足、長期未記錄、體重停滯、暴食日、運動過量
- `scripts/gi_guide.py`
  - Phase 6 低 GI 飲食指引，75+ 食品 GI 資料庫、替換建議、分餐策略；對複合料理可用 TW_FDA proxy + optional LLM fallback 自動補 GI
- `scripts/menstrual_tracker.py`
  - Phase 6 月經週期追蹤，5 階段週期模型、BMR 調整（黃體期 +7%）、分階段營養建議
- `scripts/meal_planner.py`
  - Phase 6 一週飲食計劃產生器，支援 LLM 最佳化週計劃、驗證/修正迴圈、template fallback 與採購清單
- `scripts/notification_scheduler.py`
  - Phase 6 Cron 排程報告，支援 Discord/LINE webhook 傳送
- `scripts/food_db_cache.py`
  - Phase 7 食品資料庫快取（TTL in-memory cache，無 Redis 依賴）
- `scripts/privacy_manager.py`
  - Phase 7 隱私管理，匯出/刪除個人資料（HIPAA/GDPR 基礎）
- `scripts/integration_test.py`
  - Phase 7 端到端整合測試，覆蓋所有 phase 的 smoke test
- `scripts/db_schema.sql`
  - Phase 1 schema 草案
- `references/implementation-notes.md`
  - 設計界線、風險與後續 phase 切分
- `references/phase3_output_schema.json`
  - Phase 3 → Phase 4 交接合約
- `references/exercise_eat_back_policy.md`
  - 運動回補熱量比例的設計依據

## Phase 6 Boundaries

- Exercise calorie estimation uses MET values from the Compendium of Physical Activities, which are population averages, not individual measurements.
- Exercise data integration with scoring is currently a +5 flat bonus; future versions may incorporate exercise as a scoring dimension (e.g., 10% weight).
- Exercise eat-back ratios are documented in `references/exercise_eat_back_policy.md` and should be explained to users as conservative defaults, not exact physiology.
- Menstrual cycle tracking requires active user reporting (no automatic prediction at this phase).
- GI database covers 75 common Taiwanese foods; foods outside this range return explicit "not in database" guidance plus generic low-GI heuristics, not a fake exact GI value.
- `gi_guide.py` now supports a 3-layer lookup path: static GI DB → TW_FDA macro proxy → optional OpenAI-compatible LLM fallback with 30-day cache in `food_nutrition_cache`.
- LLM fallback requires `HEALTHFIT_GI_MODEL` and `HEALTHFIT_GI_API_KEY` (or `OPENAI_API_KEY`); optional overrides: `HEALTHFIT_GI_API_URL`, `HEALTHFIT_GI_TIMEOUT_SECONDS`.
- Weekly meal plans now support an LLM-optimised path driven by user history, macro targets, and dietary restrictions; template mode remains the guaranteed fallback.
- Optimised meal plans validate daily calories (±5%), protein floor (>=85% target), and weekly variety (same dish <=2 times).
- Meal plan optimisation requires `HEALTHFIT_MEAL_PLAN_MODEL` and `HEALTHFIT_MEAL_PLAN_API_KEY` (or `OPENAI_API_KEY`); optional overrides: `HEALTHFIT_MEAL_PLAN_API_URL`, `HEALTHFIT_MEAL_PLAN_TIMEOUT_SECONDS`.
- PDF export from meal_planner.py --pdf is optional and requires fpdf2>=2.7 plus a readable CJK font. Use system fonts (fonts-wqy-zenhei / noto-cjk) or set HEALTHFIT_PDF_FONT=/path/to/font.ttf.
- Health alerts run on-demand or via cron; real-time push requires the notification delivery layer to be configured.
- Discord delivery uses webhooks; LINE delivery uses Messaging API.
- Required env vars:
  - `DISCORD_WEBHOOK_URL`
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LINE_REPORT_TARGET`
  - optional `HEALTHFIT_CHANNELS`, `HEALTHFIT_DRY_RUN`, `HEALTHFIT_DB_PATH`, `HEALTHFIT_PROFILE`
- Missing notification credentials should fail explicitly at delivery time; the Phase 7 smoke test does not exercise external delivery.

## Phase 7 Boundaries

- Food DB cache uses TTL-based in-memory cache; no Redis required. Cache expiry is 1 hour for hot foods, 24 hours for cold lookup results.
- Privacy export generates a zip archive with all user data in JSON/CSV format.
- Privacy deletion wipes user data from all tables; a confirmation step is required before deletion.
- The integration test covers all phases as a smoke test; it does not replace unit tests.
- Cron jobs for daily/weekly reports are configured via OpenClaw's cron system (`cron_notifications.yaml`).
- Phase 7 does not implement JWT authentication or full multi-user auth — those are deferred to future phases.

## Working Rules

- 先讀 profile，再讀或建立 active plan。
- 如果輸入缺少年齡、身高、體重、活動量或目標時程，不要硬猜；只補齊必要欄位。
- 人種修正只作可選校正項，不要包裝成高確定性的醫學定論。
- 使用「安全調整後方案」作為預設輸出，並把原始不安全方案列在 warning 中。
- 需要 persistent storage 時，先用 `db_manager.py`，不要把 SQL 散落在各腳本裡。
- 遇到 `requires_professional_review=true` 時，不要把自動熱量目標包裝成醫療建議；輸出需明確建議專業評估。
- Phase 2 menu advice 要明確標示為估算，並提供避免項目與替代選項。

## Validation

- 修改計算或 intake/persistence 邏輯後，執行 `python3 -m unittest discover -s tests -v`
- 修改跨 phase 整合流程後，執行 `python3 scripts/integration_test.py`
- 修改 skill 結構後，執行 `python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py /home/node/.openclaw/workspace/skills/healthfit-advisor`
