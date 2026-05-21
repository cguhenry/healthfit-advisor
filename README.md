# HealthFit Advisor

HealthFit Advisor is an OpenClaw-compatible skill for Phase 1 health and body-weight planning workflows.

It provides:

- single-user profile bootstrap and update
- BMR/TDEE estimation using Mifflin-St Jeor plus PAL activity multipliers
- safety-constrained calorie targets for weight loss, gain, or maintenance
- macro target generation
- local SQLite persistence for the active plan
- high-risk screening flags for minors, pregnancy, chronic disease, and eating disorder risk
- curated meal recommendations for common eating contexts

This is a Phase 1 engineering approximation. It is not a full NIH Body Weight Planner solver and does not provide medical advice.

## Repository Layout

```
healthfit-advisor/
├── SKILL.md
├── README.md
├── agents/
├── examples/
├── references/
├── scripts/
└── tests/
```

The canonical repository root is this directory: `skills/healthfit-advisor/`.

`projects/healthfit-advisor/` is used only for internal planning and progress notes.

## Quick Start

Run tests:

```bash
python3 -m unittest discover -s tests
```

Run the intake flow without writing local state:

```bash
python3 scripts/intake_flow.py examples/intake_payload.json --no-persist
```

Run the intake flow and persist profile plus active plan under `~/.healthfit/`:

```bash
python3 scripts/intake_flow.py examples/intake_payload.json
```

Format an intake result or plan JSON:

```bash
python3 scripts/plan_formatter.py result.json
```

Run a Phase 2 menu recommendation:

```bash
python3 scripts/menu_advisor.py examples/menu_request.json
```

## Intake Payload

Minimum fields:

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

Allowed values:

- `gender`: `M`, `F`, `X`
- `activity_level`: `sedentary`, `light`, `moderate`, `active`, `very_active`
- `risk_flags`: `minor`, `pregnancy`, `chronic_disease`, `eating_disorder`

## Safety Boundaries

HealthFit Advisor automatically constrains aggressive deficits or surpluses and flags high-risk contexts. If `requires_professional_review` is true, the result should not be presented as an actionable medical or nutrition plan.

## Phase 1 Scope

Implemented:

- profile management
- calorie and macro target estimation
- SQLite schema and storage abstraction
- reusable intake flow
- active plan persistence
- user-facing plan formatter
- curated menu advisor for Phase 2 Round 1
- unit tests and basic skill validation

Deferred:

- full NIH/Hall dynamic solver
- Taiwan and USDA food database imports
- food image analysis
- daily and weekly report generation

## Validation

```bash
python3 -m unittest discover -s tests
python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py .
```
