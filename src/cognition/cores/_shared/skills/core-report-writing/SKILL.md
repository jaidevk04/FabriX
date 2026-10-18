---
name: core-report-writing
description: Write the structured result of a core analysis run. Use before returning a finding so the summary, status, confidence and evidence are consistent and honest about simulated models.
---

# Writing a core report

## Procedure

1. Start from the monitor report you were given. State what changed since it was made.
2. Write one `summary` sentence a plant operator can read in five seconds.
3. Set `status`: `alert` only when evidence points at a specific equipment problem, `watch` when it is unclear, `normal` when nothing deviates.
4. Add one finding per piece of equipment. Each finding cites the tool results it relies on, with names and units.
5. Set `confidence` from the evidence, not from the monitor score alone. Two independent sources justify more than one.
6. List `next_checks` only for things that would settle a real doubt.

## Rules

- Say when a model is simulated or untrained. Never present a score as a calibrated probability.
- Report disagreement between sources. Do not average it away.
- Do not name an action to take. Reports give evidence. The main harness decides.
