# Exercise Eat-Back Policy

This skill uses a deliberately conservative exercise "eat-back" rule in \`scripts/exercise_tracker.py\`:

- \`loss\`: 50% of estimated exercise calories
- \`maintain\`: 75%
- \`gain\`: 100%

## Why these ratios exist

1. MET-based calorie burn is an estimate, not a direct measurement.
2. Users often overestimate exercise burn and then overeat against it.
3. Weight-loss plans need a buffer so the intended deficit does not disappear after a single workout.
4. Maintenance and gain goals should support recovery more aggressively than fat-loss plans.

## User-facing interpretation

- \`loss 50%\` does **not** mean the other 50% is forbidden forever.
- It means the *automatic quota adjustment* is conservative by default.
- If a user reports unusual hunger, back-to-back long sessions, or athletic training volume, the agent should explain that the ratio is a default heuristic and can be overridden manually.

## Important limitation

Because this skill estimates burn from MET tables, the eat-back policy should be treated as a coaching heuristic, not a physiological truth.
