# Changelog

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
