# HealthFit Advisor

HealthFit Advisor is an OpenClaw-compatible skill for staged health, nutrition, and body-weight planning workflows.

It provides:

- single-user profile bootstrap and update
- BMR/TDEE estimation using Mifflin-St Jeor plus PAL activity multipliers
- safety-constrained calorie targets for weight loss, gain, or maintenance
- macro target generation
- local SQLite persistence for the active plan
- high-risk screening flags for minors, pregnancy, chronic disease, and eating disorder risk
- curated meal recommendations for common eating contexts
- food image analysis prompt/parser helpers
- calorie tracking, scoring, reporting, exercise logging, GI guidance, menstrual tracking, meal planning, and alerts
- TTL in-memory food lookup cache
- privacy export/delete tooling
- end-to-end smoke test coverage across implemented phases

This is a Phase 1-7 engineering build. It is not a full NIH Body Weight Planner solver and does not provide medical advice.

## Repository Layout

\`\`\`
healthfit-advisor/
├── SKILL.md
├── README.md
├── agents/
├── examples/
├── references/
├── scripts/
└── tests/
\`\`\`

The canonical repository root is this directory: \`skills/healthfit-advisor/\`.

\`projects/healthfit-advisor/\` is used only for internal planning and progress notes.

## Quick Start

Run tests:

\`\`\`bash
python3 -m unittest discover -s tests
\`\`\`

Run the intake flow without writing local state:

\`\`\`bash
python3 scripts/intake_flow.py examples/intake_payload.json --no-persist
\`\`\`

Run the intake flow and persist profile plus active plan under \`~/.healthfit/\`:

\`\`\`bash
python3 scripts/intake_flow.py examples/intake_payload.json
\`\`\`

Format an intake result or plan JSON:

\`\`\`bash
python3 scripts/plan_formatter.py result.json
\`\`\`

Run a Phase 2 menu recommendation via the dialogue flow:

\`\`\`bash
python3 scripts/diet_dialogue.py --cuisine 日式 --location 餐廳 --meal 晚餐 --calories 1800
python3 scripts/diet_dialogue.py --cuisine any --location 超商 --meal 點心 --remaining-calories 250
python3 scripts/diet_dialogue.py --cuisine 台式
python3 scripts/diet_dialogue.py --cuisine 台式 --location 自助餐 --meal 午餐 --remaining-calories 600 --format json
\`\`\`

Run the Phase 7 smoke test:

\`\`\`bash
python3 scripts/integration_test.py
\`\`\`

Export or delete local user data:

\`\`\`bash
python3 scripts/privacy_manager.py preview --user-id <user_id>
python3 scripts/privacy_manager.py export --user-id <user_id> --output-dir ./exports
python3 scripts/privacy_manager.py delete --user-id <user_id> --confirm
\`\`\`

## Intake Payload

Minimum fields:

\`\`\`json
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
\`\`\`

Allowed values:

- \`gender\`: \`M\`, \`F\`, \`X\`
- \`activity_level\`: \`sedentary\`, \`light\`, \`moderate\`, \`active\`, \`very_active\`
- \`risk_flags\`: \`minor\`, \`pregnancy\`, \`chronic_disease\`, \`eating_disorder\`

## Safety Boundaries

HealthFit Advisor automatically constrains aggressive deficits or surpluses and flags high-risk contexts. If \`requires_professional_review\` is true, the result should not be presented as an actionable medical or nutrition plan.

## Phase Boundaries

Implemented (Phase 1-7):

- profile management
- calorie and macro target estimation
- SQLite schema and storage abstraction
- reusable intake flow
- active plan persistence
- user-facing plan formatter
- curated menu recommendation engine
- guided diet consultation dialogue tree
- vision-agnostic food image analysis helpers
- calorie tracking and history comparison
- daily and weekly scoring plus report generation
- exercise logging, GI guidance, menstrual tracking, health alerts, and weekly meal planning
- TTL food lookup cache
- privacy export/delete workflows
- end-to-end smoke test
- unit tests and skill validation

Deferred:

- full NIH/Hall dynamic solver
- JWT or full multi-user authentication / authorization
- richer cron orchestration around scheduled reports
- weekly scoring integration for GI / menstrual / exercise advanced dimensions

## Validation

\`\`\`bash
python3 -m unittest discover -s tests
python3 scripts/integration_test.py
python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py .
\`\`\`
