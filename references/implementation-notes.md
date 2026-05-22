# HealthFit Advisor Implementation Notes

## Current Phase: Phase 2 Complete

Phase 2 deliverables:
- `scripts/menu_advisor.py` — curated recommendation engine
- `scripts/diet_dialogue.py` — guided dialogue tree

## Phase 2 Architecture

### menu_advisor.py

Provides `MenuAdvisor.recommend_meal()` with:
- Input: cuisine_type, eating_location, meal_type, calorie/protein targets
- Output: primary recommendation, alternatives, avoid list, rationale, warnings
- Scoring: calorie fit + (protein shortfall × 1.5) + (sodium penalty × 0.35)
- Fallback cascade: exact cuisine+location → cuisine only → location only → any

Curated templates cover:
- convenience_store: 3 templates (lunch/dinner, breakfast, snack)
- buffet: 1 template (lunch/dinner)
- restaurant: 3 templates (japanese, korean, southeast asian)
- chain_restaurant: 1 template (western)
- home: 1 template (lunch/dinner)

### diet_dialogue.py

Agent-facing conversation flow:
- Accepts cuisine/location/meal inputs (any combination)
- Returns either `ready` (with recommendation) or `clarification_needed` (with prompt for next missing field)
- Supports `DialogueState` object for multi-turn conversation continuity
- Chinese/English keyword matching with specificity ordering
- `no_preference` → `any` for cuisine, `convenience_store` for location

### Data Flow

```
User text → diet_dialogue.build_recommendation()
  ├─ clarification_needed → agent asks next question
  └─ ready → MenuAdvisor.recommend_meal()
              └─ Recommendation (with formatted text)
```

## Design Corrections From Plan Review

1. "NIH BWP" and "Mifflin-St Jeor + PAL" are not the same.
   - Phase 1 uses an engineering approximation.
   - Full NIH/Hall dynamic model is deferred.
2. Single-user profile bootstrap moved to Phase 1 (from Phase 4).
3. SQLite is the dev default; PostgreSQL is deploy-time only.
4. Medical safety guardrails are front-loaded.
5. Phase 2 curated templates are an intentional simplification before Taiwan/USDA food DB import.

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

## Deferred To Later Phases

- Taiwan and USDA food database import
- Food image analysis (vision-agnostic)
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