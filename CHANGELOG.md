# Changelog

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
