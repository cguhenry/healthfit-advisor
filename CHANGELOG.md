# Changelog

## 0.2.0 - 2026-05-22

**Phase 2 complete: Diet Consultation Engine**

- Added curated menu recommendation engine with 9 meal templates.
- Added cuisine/location/meal type validation.
- Added recommendation ranking with calorie/protein/sodium scoring.
- Added fallback behavior preserving cuisine preference.
- Added guided dialogue tree (`diet_dialogue.py`) with:
  - Chinese/English keyword matching (ordered by specificity)
  - Multi-turn `DialogueState` support
  - Automatic clarification prompts for missing fields
  - Handles `no_preference` gracefully
- Added 9 diet dialogue tests and 5 eval cases.
- Added menu request example.
- Updated skill docs and implementation notes.

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
