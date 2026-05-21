# Contributing

## Development

Run the test suite before sending changes:

```bash
python3 -m unittest discover -s tests
```

For OpenClaw skill structure validation:

```bash
python3 /home/node/.openclaw/agents/main/agent/codex-home/skills/.system/skill-creator/scripts/quick_validate.py .
```

## Safety Rules

- Do not present Phase 1 calorie targets as medical advice.
- Keep `requires_professional_review` behavior intact for high-risk contexts.
- Add tests for calculator, intake, or persistence changes.
- Keep public repo content inside this skill directory. Internal planning notes belong in `projects/healthfit-advisor/`.
