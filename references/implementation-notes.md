# HealthFit Advisor Implementation Notes

## Current Phase: Phase 3 Complete

Phase 3 deliverables:
- `scripts/vision_capability_check.py`
- `scripts/food_analyzer.py`

## Phase 3 Architecture

### vision_capability_check.py

Design: does NOT call any Vision API. Detects via model ID substring matching.

Priority:
1. KNOWN_NONVISION list (checked FIRST to avoid `gpt-4o-mini` being caught by `gpt-4o`)
2. KNOWN_VISION_SUBSTRINGS
3. Unknown → conservative NOT supported

Key exports:
- `check(model_id)` → VisionCheckResult
- `require(model_id)` → raises VisionNotSupportedError if not supported
- `VisionNotSupportedError` exception class

### food_analyzer.py — Vision-Agnostic Design

The skill does NOT call any Vision API directly. Instead:

```
Agent framework (current LLM, e.g. Claude 3 Sonnet)
    ↓ [sends prompt from build_llm_prompt() + image]
LLM returns structured JSON
    ↓
Agent passes JSON to parse_llm_response()
    ↓
MealAnalysisResult → format_analysis_result() → human-readable text
```

Three scenarios:
1. `MENU` — OCR + parse + filter against calorie target + recommended/avoid lists
2. `FOOD` — identify foods + estimate portions + calculate nutrition + remaining calories
3. `BEFORE_AFTER` — compare pre/post photos + consumed_pct + actual intake calculation

Confidence tiers:
- HIGH ≥ 85%: direct value
- MEDIUM 60–85%: range estimate + note
- LOW < 60%: flagged in `low_confidence_warnings`, user prompted to confirm manually

## Design Corrections From Plan Review

1. "NIH BWP" and "Mifflin-St Jeor + PAL" are not the same.
   - Phase 1 uses an engineering approximation.
   - Full NIH/Hall dynamic model is deferred.
2. Single-user profile bootstrap moved to Phase 1 (from Phase 4).
3. SQLite is the dev default; PostgreSQL is deploy-time only.
4. Medical safety guardrails are front-loaded.
5. Phase 2 curated templates are an intentional simplification before Taiwan/USDA food DB import.
6. Vision is handled by the agent's own LLM, not by this skill calling a Vision API.

## Phase 1 Scope

- Skill scaffold
- Single-user profile management
- BMR/TDEE/calorie/macro calculation
- Safety checks and auto-adjustment
- SQLite storage abstraction
- Intake flow with profile + active plan persistence
- High-risk screening flags
- Plan formatter

## Phase 2 Scope

- Curated menu recommendation (9 templates)
- Guided diet consultation dialogue tree
- Chinese/English keyword matching
- Multi-turn dialogue state support
- Menu request example and tests

## Phase 3 Scope

- Vision capability check (model ID-based, no Vision API calls)
- Three analysis scenarios: menu / food / before_after
- Structured LLM prompt templates
- Response parsing with confidence tiers
- Human-readable output formatting
- 48 total unit tests

## Deferred To Later Phases

- Taiwan and USDA food database import
- Daily/weekly report generation
- Exercise integration
- Menstrual cycle adjustments
- GI management
- Multi-user mode

## Publication Strategy

The canonical repository root is `skills/healthfit-advisor/`.

- `projects/healthfit-advisor/` contains internal planning/progress docs.
- GitHub push happens after each phase is closed and validated.
- `.github/workflows/test.yml` is local-only (PAT lacks `workflow` scope).