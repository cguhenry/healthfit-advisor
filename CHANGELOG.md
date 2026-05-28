# Changelog

## 0.9.2 - 2026-05-28

**P0 Bug Fixes**

- **P0-1** `menu_nutrition_estimator.py`：便當區塊移至便利商店規則之前，修正「雞胸便當飯半碗」被錯誤估成 180 kcal 的問題；便利商店雞胸規則加上 `"便當" not in name` 防衛

- **P0-2** `menu_nutrition_estimator.py`：鮮奶茶規則（180 kcal）搶先於無糖茶規則，避免「無糖鮮奶茶去珍珠」被估成 0 kcal；無糖茶規則加 `"奶" not in name` 條件，防止含奶的品項誤觸

- **P0-3** `dining_user_context.py`：`load_dining_user_context()` 在找不到 active plan 時主動 raise `RuntimeError`，不再吐出 0 kcal 造成混洧；`dining_advisor.py` 以 `parser.error()` 呈現錯誤訊息

- **P0-4** `dining_advisor.py`：`--remaining-calories`/`--protein-gap` 預設值改為 `None`，可正確覆寫 DB 值；`--protein-gap or 0` 處理 None 輸入

**P1 Bug Fixes**

- **P1-1** `requirements.txt`：新增 `requests>=2.31.0`（`recommendation_explainer.py` 已依賴）

- **P1-2** `can_i_eat.py` `format_result()`：`alternatives` 清單中結尾為 `：` 的項目視為子標題，不套用 `• ` 前綴，解決「🔄 替代選項」區段雙 bullet 問題（`• • 無糖綠茶...`）

- **P1-3** `can_i_eat.py` `check_can_i_eat()`：DB lookup 失敗時，先嘗試 `estimate_menu_item_nutrition()` 估算，再 fallback 至 `2.5kcal/g`。珍珠奶茶（500ml）從錯誤的 ~1250 kcal 修正為正確的 ~550 kcal

- **P1-4** `dining_advisor.py` `format_recommendation()`：`avoid` 清單為空時不印 `⚠️ 較不建議：` header

## 0.9.2 - 2026-05-28 — USDA 資料庫重構

**USDA 資料庫移至 `assets/usda_food_db/foundation_foods_csv/`**

`scripts/food_db_import_pivot.py` 完全重構 USDA 匯入流程：

- 新增 `_resolve_usda_dir()`、`_validate_usda_files()`、`_load_usda_foods()`、`_load_usda_nutrients()`、`_pivot_usda_nutrients()` 輔助函式
- 新增 `import_usda_foundation()` 取代舊版 `import_usda()`，支援 `foundation_foods_csv/` 新目錄結構
- 新增 `_upsert_batch()` 使用 `db.transaction()` 批次寫入（避免 `execute_many` Silent failure）
- CLI 新增 `--usda-dir` 參數：`import-usda --usda-dir assets/usda_food_db/foundation_foods_csv`
- 移除了不再使用的 `USDA_FOOD_CSV`、`USDA_EXTRACT` 常數及舊 nutrient mapping
- 成功匯入 4,821 筆 USDA Foundation Foods 營養資料

## 0.9.1 - 2026-05-27

**Bug fix + Regression tests**

Bug fixes:

- **Bug 10** `menu_image_analyzer.py`：新增 `_strip_json_fence()`，支援 LLM 回傳的 markdown code-fence JSON（```json...```）。處理解析失敗時，會先移除 ``` 包裝再 parse。三種格式皆支援：多行標準格式、無 closing fence、純 JSON（無 fence）

- **Bug 11** `user_restaurant_repository.py`：所有 CRUD 函式（`upsert_user_restaurant_profile`、`upsert_user_restaurant_item`、`load_user_restaurant_profile`、`load_user_restaurant_items`）開頭皆加入 `db.initialize()`，不再依賴呼叫端提前初始化 DB

New test file:

- `tests/test_dining_fixes.py`：5 個迴歸測試，覆蓋 code-fence 解析、repository 自我初始化、推薦結果不重疊、已知食物營養不誤判為不足、str db_path 接受度

## 0.9.0 - 2026-05-27

**Phase 9 — 外食情境推薦引擎（基礎）**

新增 6 個模組，建立外食場景推薦核心架構：

- `scripts/dining_models.py` — 資料模型：
  - `MenuItem`：單一菜單品項（含 source、confidence、營養預估值、標籤）
  - `RestaurantScenarioTemplate`：店家類型模板（推薦/避免/修改規則/風險提醒）
  - `ScoredMenuItem`：評分後的品項（分數、理由、修改建議）
  - `DiningRecommendation`：推薦結果封裝

- `scripts/restaurant_scenarios.py` — 7 種店家類型：
  - `breakfast_shop`、`bento_shop`、`convenience_store`、`bubble_tea`、
    `luwei`、`hotpot`、`noodle_shop`
  - 內建品項、推薦組合、避免組合、修改建議、風險提醒

- `scripts/menu_nutrition_estimator.py` — Rule-based 營養估算：
  - 涵蓋早餐、便當、便利商店、手搖飲、滷味、火鍋、麵店主流品項
  - 自動推斷標籤（`high_protein`、`fried`、`sugary_drink`、`low_calorie` 等）
  - 支援份量關鍵字（「飯半碗」、「少醬」、「加蛋」）自動調整熱量

- `scripts/menu_item_scoring.py` — 評分引擎：
  - 根據：今日剩餘熱量、蛋白質缺口、減脂/維持/增肌目標、低 GI 需求
  - 計算 0~100 分，產生理由與修改建議

- `scripts/dining_context_engine.py` — 推薦主流程：
  - `recommend_without_menu()`：無菜單時以店家類型模板 fallback
  - `recommend_from_menu_items()`：有實際品項時評分排序
  - 預留介面供日後串接 `menu_image_analyzer` 與 `brand_menu_repository`

- `scripts/dining_advisor.py` — CLI 工具

附帶 Bug fix：

- `menu_item_scoring.py`：修正 `over` 變數範圍錯誤（`UnboundLocalError`）

---

## 0.8.0 - 2026-05-27

Phase 8 Feature 1 — `can_i_eat.py` 加入替代份量計算

**功能**：當食物熱量超過今日剩餘預算時，主動計算並顯示建議份量。

- 新增 `PortionAdjustment` dataclass，包含 `suggested_quantity`、`suggested_grams`、
  `calorie_fit_ratio`、`portion_label`、`portion_advice`
- 新增 `_build_portion_adjustment()` 函式：
  - `remaining <= 0` → 建議不吃
  - `ratio >= 1` → 原份量可接受，回傳 None
  - `ratio < 35%` → 建議改選替代品
  - 其餘 → 顯示建議吃的比例與公克數
- `check_can_i_eat()` 在取得 food match 後呼叫 `_build_portion_adjustment()`，結果存入
  `CanIEatResult.portion_adjustment`
- `format_result()` 在 advice 後方顯示 📏 份量調整區塊
- 附带修正：DB match 分支原本未設定 `matched_name`，導致輸出為空；一併修正在此變動中

---

## 0.7.10 - 2026-05-27

Bug 22 — off-by-one in `update_preference_after_log()` rolling average

**Root cause**: Phase 1 increments `total_count` via ON CONFLICT UPDATE, then
Phase 2 re-reads that same row — the `total_count` it fetches is already N+1
(the post-increment value). The formula used `old_count` as both the multiplier
and added +1 in the denominator, effectively skipping one observation:

    # wrong: old_count is already N+1 after the ON CONFLICT update
    new_avg = (old_avg * old_count + new_score) / (old_count + 1)
    # = (avg*N + new) / (N+2)  <- off by one

**Fix**: Capture `previous_count` (the count *before* the upsert) and use it as
the multiplier; the post-increment `old_count` only appears as the denominator.

    new_avg = (old_avg * previous_count + new_score) / old_count
    # = (avg*N + new) / (N+1)  ✓


## 0.7.9 - 2026-05-26

Enhancement — dual-track food preference scoring (Bug 14)

**Problem**: `avg_daily_score_when_eaten` is a blurred attribution signal — a food eaten
on a bad day (because other foods on the same plate dragged the score down) gets
penalised unfairly. Favorites/problematic quadrants were unreliable.

**Solution**: Dual-track scoring where each food gets two independent signals:

- **Track 1 — `avg_daily_score_when_eaten`** (unchanged): does this food tend to appear
  on high- or low-score days? Weak but behaviourally grounded.
- **Track 2 — `avg_food_quality_score`** (new): the food's intrinsic nutrition profile
  based on calorie density, protein, fibre, sodium, and sugar per 100 g. Independent
  of context; stable across all eating occasions. Range 0–100.

**Classification** (updated thresholds):
`final_score = daily_score × 0.6 + food_quality × 0.4`

| Quadrant | Condition |
|----------|------------|
| Favorites | final ≥ 65, total_count ≥ 2 |
| Problematic | final ≤ 40, total_count ≥ 3 |
| Exploratory | grey zone or insufficient data |

**Schema** (`db_schema.sql`): added `avg_food_quality_score REAL` column to
`food_preference_profile`.

---

## 0.7.8 - 2026-05-26

Enhancement — DBManager transaction and batch support

---

## 0.7.8 - 2026-05-27

- **meal_planner.py**: `_get_recent_food_preferences()`、`_get_low_score_patterns()` 移除 SQLite `DATE('now', ?)` 改為參數化 `DATE(?, ?)` 並新增 `today` 參數，行為與 food_preference_engine.py 一致
- **can_i_eat.py**: 找到 DB 食物時優先使用 `serving_size_g` 而非 `_default_serving_for()`，讓食品資料庫的建議份量真正生效
- **can_i_eat.py**: 將 `is_estimate = confidence < 0.5` 拆分為 `source_type: Literal["db", "heuristic"]` + `low_confidence: bool`，語意更精確；保留 `_is_estimate` 作為 `@property` backward-compat
- **can_i_eat.py**: 將 `protein_gap` 拆分為 `protein_gap_before` / `protein_gap_after`，advice 與 output 均使用吃後缺口；保留 `protein_gap` 作為 `@property` backward-compat

## 0.7.7 - 2026-05-26

Bug fixes batch — preference engine, PDF export, can-i-eat, shopping push

- **food_preference_engine.py**: `always_suggest` foods no longer appear in both `preferred` and `problematic` quadrants; added `continue` after appending to `preferred` so they skip quadrant classification
- **food_preference_engine.py**: `db_schema.sql` comment for `recent_count` corrected from「近 30 天次數」to「近 30 天內有記錄此食物的天數（非份數）」to match the `COUNT(DISTINCT DATE(log_datetime))` implementation
- **shopping_push.py** PDF export: replaced the broken column-switching logic (`if col_idx == 1` always true after assignment, `break` reversed by outer loop, no new-page handling); new approach tracks `col_row_y[2]` independently, pre-estimates category height, falls back to the other column or adds a new page when needed
- **shopping_push.py**: `_generate_plan_for_week()` no longer hardcodes `cuisine="台式"`; now queries `weekly_meal_plans` for the user's last-used cuisine and falls back to「台式」only when no history exists
- **can_i_eat.py**: `_determine_verdict()` now has an early return for `remaining < 0` (already over budget today), producing a clear message 「今日已超標 {abs(remaining):.0f} kcal」instead of the confusing 「超出今日剩餘 -N kcal」
- **can_i_eat.py**: `matched_food_display` no longer shows 「估算 份」when not an estimate; fixed to only show「（估算 1 份）」when `is_estimate=True`, and shows quantity multiplier for non-1 quantities
- **can_i_eat.py**: fallback alternatives in `_build_alternatives()` now dynamically compute「✅ 在配額內」vs「⚠️ 超出 {N} kcal」based on the actual `remaining` calorie budget, instead of always appending「✅ 在配額內」
- **can_i_eat.py**: `_build_adjusted_suggestion()` is now called for `verdict="marginal"` (was previously only called for `yes` and `yes_with_caveat`), so marginal situations that need meal-adjustment advice now produce output

## 0.7.6 - 2026-05-25

CLI unification and agent manifest expansion

- Replaced datetime.utcnow() in scripts/gi_guide.py with timezone-aware UTC handling for GI cache cutoff timestamps
- Added scripts/healthfit.py as the unified operator-facing CLI entry point
- Added tests/test_healthfit_cli.py covering dispatcher routing for intake, meal logging, reports, GI lookup, and alerts
- Split agent metadata into agents/openclaw.yaml, agents/hermes.yaml, and an expanded agents/openai.yaml
- Updated README deployment and usage docs to point manifests and human operators at the unified CLI entry point

## 0.7.5 - 2026-05-24

Meal planner PDF export hardening

- Removed the invalid fpdf.pyfunctions.CJK fallback from scripts/meal_planner.py
- Removed deprecated uni=True font registration for fpdf2
- Added explicit CJK font discovery via HEALTHFIT_PDF_FONT or common system font paths
- PDF export now fails with a clear stderr message when no readable CJK font is available
- Added PDF text sanitization to strip emoji/symbol glyphs that common CJK fonts do not render reliably
- Declared fpdf2>=2.7 as an optional PDF dependency in pyproject.toml and documented the install path in README.md
- Added regression tests for font registration, missing-font failure, and PDF text sanitization

## 0.7.4 - 2026-05-24

Meal-plan optimisation and persistence

- Added `generate_optimized_meal_plan()` in `scripts/meal_planner.py`
- New optimisation flow analyzes recent food logs and low-score eating patterns, builds a structured planning prompt, validates LLM output, retries corrections, and falls back to template mode when needed
- Added OpenAI-compatible meal-plan provider bridge via `HEALTHFIT_MEAL_PLAN_MODEL` / `HEALTHFIT_MEAL_PLAN_API_KEY`
- Added `weekly_meal_plans` table and `persist_meal_plan()` helper for optional SQLite persistence
- CLI `meal_planner.py plan` now supports `--restrictions`, `--template-only`, and `--persist`
- Added regression tests for calorie tolerance, duplicate-meal limits, low-protein validation, fallback behavior, and DB persistence

## 0.7.3 - 2026-05-24

GI fallback automation and provider bridge

- Extended `scripts/gi_guide.py` to a 3-layer lookup path: static GI DB → TW_FDA macro proxy → optional OpenAI-compatible LLM fallback
- Added persistent `GI_LLM` caching in `food_nutrition_cache` with a 30-day TTL to avoid repeated model calls for compound dishes
- Added an environment-variable driven provider bridge using Chat Completions semantics
- Added CLI controls for `--no-db` and `--no-llm`
- Added regression tests covering env-configured HTTP fallback, cache reuse, and explicit CLI disable behavior
- Updated README, SKILL.md, and implementation notes for deployment and configuration

## 0.7.2 - 2026-05-24

Bugfix consolidation, schema cleanup, and Chinese deployment docs

- Fixed Phase 3 → Phase 4 nutrition handoff so per-food nutrition is preserved in parser output and to_dict serialization
- Updated the FOOD prompt template to require per-food calories/macros plus a summed meal total
- Fixed calorie_tracker date handling at month boundaries and moved query-only connection paths to explicit closing()
- Fixed weekly scoring sparse-data behavior so missing weight data is treated as unavailable input, not as 0.0 kg
- Renamed misleading weekly-report internal variables in _get_week_weight_change()
- Added score_events to scripts/db_schema.sql so the canonical schema is complete
- Intake flow now writes the initial body weight into weight_logs during persistence
- ProfileManager.load() is now read-only and no longer rewrites the profile file
- Added tests/test_profile_manager.py
- Localized README into Chinese and expanded installation / deployment guidance
- Updated maintenance docs: SKILL.md, README.md, CHANGELOG.md, references/implementation-notes.md, projects/healthfit-advisor/PHASE_PROGRESS.md

## 0.7.1 - 2026-05-24

**Contract hardening, sparse-data fallback, and boundary clarification**

- Added `references/phase3_output_schema.json` as the Phase 3 → Phase 4 handoff contract
- Added `references/exercise_eat_back_policy.md` documenting the rationale behind loss/maintain/gain eat-back ratios
- Updated `scripts/calorie_tracker.py`:
  - added `normalize_phase3_analysis_payload()` so native Phase 3 output can be passed into Phase 4 without ad-hoc field mapping
  - CLI `log` path now validates and normalizes payloads before DB write-back
- Updated `scripts/scoring_engine.py`:
  - weekly scoring now marks weight trend unavailable when no weight data exists
  - the missing 20% weight-trend component is redistributed across the remaining components instead of silently scoring zero
  - persisted weekly summary metadata now includes component weights and fallback notes
- Updated `scripts/integration_test.py` to exercise the canonical Phase 3 → Phase 4 normalization path
- Added tests for Phase 3 payload normalization and sparse weekly scoring fallback
- Clarified SQLite-only implementation scope, GI fallback behavior, and notification env requirements in docs

## 0.7.0 - 2026-05-24

**Phase 7: Cache, privacy tooling, and end-to-end smoke coverage**

- Added `scripts/food_db_cache.py`:
  - TTL-based in-memory cache in front of `food_db_lookup.py`
  - Hot food search TTL: 1 hour
  - Cold exact lookup / empty-result TTL: 24 hours
  - Cache stats, invalidation, and expired-entry purge
  - No Redis or external cache dependency
- Added `scripts/privacy_manager.py`:
  - `preview_user_data()` row counts by table
  - `export_user_data()` JSON + CSV export bundle with manifest and zip archive
  - `delete_user_data()` full per-user deletion with required confirmation
- Added `scripts/integration_test.py`:
  - End-to-end smoke flow covering representative Phase 1-7 operations
  - Exercises intake, dialogue, analysis parsing, calorie tracking, scoring, report generation, exercise adjustment, cycle logging, GI guidance, food cache, and privacy export/delete
- Added test modules:
  - `tests/test_food_db_cache.py`
  - `tests/test_privacy_manager.py`
  - `tests/test_integration_test.py`
- Updated README, SKILL.md, and PHASE_PROGRESS.md for Phase 7

## 0.6.0 - 2026-05-23

**Phase 6: Exercise tracking, health alerts, GI guide, menstrual tracker, meal planner & notification completion**

- Added `scripts/exercise_tracker.py`:
  - MET-based calorie estimation from Compendium of Physical Activities (75+ activity-MET pairs)
  - `log_exercise()`: write/accumulate exercise sessions to `exercise_logs`
  - `adjust_daily_calorie_target()`: dynamic quota adjustment by goal type (loss:50%, gain:100%, maintain:75% eat-back)
  - `daily_calorie_ledger` persistence with upsert
  - Chinese/English intensity normalization and auto-type classification
  - CLI: `log`, `status`, `adjust`, `met` subcommands
- Added `scripts/health_alerts.py`:
  - 7 alert types: low_calorie_streak (3+ days < safe floor), rapid_weight_loss (>1.5kg/week), protein_deficiency, missing_logs (5+ days), plateau (3+ weeks no change), binge_day (>50% over target), excessive_exercise (>800 kcal burn)
  - `run_all_checks()` with 3-day dedup window
  - Severity tiers: info/warning/critical with emoji icons
  - DB persistence with acknowledge workflow
  - CLI: `check`, `list`, `ack` subcommands
- Added `scripts/gi_guide.py`:
  - 75-food GI database (University of Sydney values)
  - `classify_food()`: classify foods into low/medium/high GI tiers
  - `recommend_swap()`: high→low GI alternatives
  - `get_meal_strategy()`: phase-specific strategies (breakfast/lunch/dinner/snack/pre-workout/post-workout)
  - CLI: `classify`, `swap`, `strategy`, `list` subcommands
- Added `scripts/menstrual_tracker.py`:
  - 5-phase cycle model: menstruation/follicular/ovulation/luteal/premenstrual
  - BMR adjustments: baseline (1.00) to luteal (+7%) based on Davidsen et al. (2007)
  - `adjust_calorie_target()`: phase-aware calorie adjustment
  - `log_period_start()`: DB persistence with customizable cycle length
  - Phase-specific nutrition advice (6 phases)
  - CLI: `log-period`, `current-phase`, `adjust` subcommands
- Added `scripts/meal_planner.py`:
  - 7-day meal plan generator (3 cuisines × 3 preference profiles = 9 templates)
  - Calorie-aware distribution (25/35/35/5 balanced, high_protein, light options)
  - Automatic shopping list from meal plan
  - Rotating variety across days
  - CLI: `plan` subcommand
- Updated `scripts/scoring_engine.py`:
  - `run_daily_scoring()` now reads daily_calorie_ledger for exercise-adjusted targets
  - Exercise bonus (+5) when exercise is logged
- Updated `scripts/notification_scheduler.py`:
  - Discord webhook delivery (_deliver_discord) via DISCORD_WEBHOOK_URL
  - LINE Messaging API delivery (_deliver_line) via LINE_CHANNEL_ACCESS_TOKEN
  - Dry-run support via HEALTHFIT_DRY_RUN env var
- Updated `scripts/db_manager.py`:
  - Added `fetchone()` and `fetchall()` convenience methods
- Updated `scripts/db_schema.sql`:
  - New tables: exercise_logs, daily_calorie_ledger, menstrual_logs, health_alerts
  - Added UNIQUE constraint on menstrual_logs(user_id, period_start)
- Added test modules:
  - `tests/test_exercise_tracker.py`: 36 tests (MET lookup, calorie estimation, type classification, DB, and calorie adjustment)
  - `tests/test_health_alerts.py`: 43 tests (all alert types, persistence, format, full pipeline)
  - `tests/test_gi_guide.py`: 26 tests (classification, swaps, strategies, data integrity)
  - `tests/test_meal_planner.py`: 31 tests (generation, variety, shopping list, template integrity)
  - `tests/test_menstrual_tracker.py`: 31 tests (phase calculation, calorie adjustment, DB persistence)
  - Total: **284 tests** all passing
- Updated SKILL.md, README.md, CHANGELOG.md, PHASE_PROGRESS.md

**Phase 5: Daily & weekly scoring and report generation**

- Added `scripts/scoring_engine.py`:
  - `score_daily()`: 100-point base scoring with deductions for calorie over/under, protein deficiency/excess, fiber, sodium, refined sugar, and missing meals
  - `score_weekly()`: weighted scoring (50% daily avg + 20% weight trend + 15% diversity + 15% completeness)
  - `get_daily_nutrition()`: aggregates food_logs per day (excluding ___MEAL_TOTAL___)
  - `run_daily_scoring()`: end-to-end pipeline (aggregate → score → persist)
  - `persist_daily_score()`: writes score_events and updates daily_summaries
  - `persist_weekly_score()`: upserts weekly_summaries
  - Grade classification: ⭐優秀(90+) / 良好(75-89) / 及格(60-74) / 待加強(40-59) / ⚠️警示(<40)
  - CLI interface: `score` and `weekly` subcommands
- Added `scripts/report_generator.py`:
  - `generate_daily_report()`: full daily report with plan summary, meal breakdown, score, history comparison, and recommendations
  - `generate_weekly_report()`: full weekly report with 7-day score bar, calorie chart, weight change, score table, and next-week suggestions
  - Text-based calorie trend charts and visual score bars
  - CLI interface: `daily` and `weekly` subcommands
- Added `tests/test_scoring_engine.py`: 43 tests (grade classification, daily scoring, weekly scoring, persistence, nutrition aggregation, full pipeline)
- Added `tests/test_report_generator.py`: 20 tests (daily report, weekly report, edge cases)
- Updated SKILL.md: Phase 5 boundaries
- Updated CHANGELOG.md, PHASE_PROGRESS.md

## 0.4.0 - 2026-05-22

**Phase 4: Calorie tracking, DB persistence, and history comparison**

- Added `scripts/calorie_tracker.py`:
  - `log_meal_analysis()`: writes food analysis results (Phase 3) into `food_logs` table
  - `upsert_daily_summary()`: recalculates and upserts `daily_summaries` from food_logs
  - `get_daily_summary()`: reads existing daily summary by date
  - `get_history_comparison()`: compares today vs yesterday, last week, 7-day trailing average, and plan start
  - `get_recent_trend()`: rolling N-day per-day calorie/protein totals (with zero-fill for missing days)
  - `get_calorie_progress()`: calorie/protein snapshot with meal breakdown, reads target from active plan
  - `format_progress()` and `format_comparison()`: human-readable output
  - CLI interface: `log`, `summary`, `compare`, `trend`, `progress` subcommands
- Added 31 Phase 4 tests (71 total tests)
- Updated SKILL.md, CHANGELOG.md, PHASE_PROGRESS.md

## 0.3.0 - 2026-05-22

**Phase 3 complete: Vision-agnostic food image analysis**

- Added `scripts/vision_capability_check.py`:
  - Substring-based model ID detection (vision vs non-vision)
  - KNOWN_NONVISION checked FIRST to avoid substring collisions (e.g. gpt-4o-mini vs gpt-4o)
  - `check()`, `require()`, `VisionNotSupportedError`
  - CLI for manual testing
- Added `scripts/food_analyzer.py`:
  - Three analysis scenarios: MENU / FOOD / BEFORE_AFTER
  - `build_llm_prompt()`: returns (system_prompt, user_message) for agent's multimodal LLM
  - `parse_llm_response()`: parses LLM JSON → MealAnalysisResult dataclass
  - `format_analysis_result()`: human-readable output with confidence tier icons
  - Confidence tiers: HIGH ≥85%, MEDIUM 60–85%, LOW <60%
  - Low-confidence items auto-flagged and warned
- Added mock LLM response examples in `examples/mock_responses/`
- Added 18 Phase 3 tests (48 total tests)
- Added 4 Phase 3 eval cases (11 total)
- Updated skill docs for Phase 3 boundaries

## 0.2.0 - 2026-05-22

## 0.1.0 - 2026-05-21

Phase 1 close-out:

- Added BMR/TDEE and macro target calculator.
- Added safety-constrained weight plan generation.
- Added single-user profile management.
- Added SQLite storage manager and schema.
- Added reusable intake flow.
- Added high-risk screening flags.
- Added active plan persistence.
- Added user-facing plan formatter.
- Added example payload and tests.
- Added GitHub-ready repository metadata.
