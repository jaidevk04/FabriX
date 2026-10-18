---
name: problem-formulation
description: Turn a request into an objective, constraints and a starting point. Use at the start of every optimization analysis, before searching for candidates.
---

# Problem formulation

## Procedure

1. Call `optimization_read_problem_context` for the state, band, limits and business numbers.
2. Name the objective: recovery, energy or scrap. If the request mixes them, say which comes first.
3. List constraints: duty 10 to 90, at most 20 per command, the plant must stay inside its envelope.
4. If the request depends on equipment condition or fleet, call `optimization_request_evidence`.

## Rules

- Only thermal duty is a control you can recommend. Say so if the goal needs another control.
