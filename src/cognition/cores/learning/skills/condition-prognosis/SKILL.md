---
name: condition-prognosis
description: Estimate how far a degradation has progressed and how urgent it is. Use when a diagnosis exists and the main harness needs a stage and a time scale for the equipment.
---

# Condition prognosis

## Procedure

1. Call `learning_estimate_remaining_life` for the equipment.
2. Report the stage (early, developing or advanced) and the simulated remaining hours together.
3. Compare the stage with how fast scores moved between your reads. A fast rise shortens the practical window even if the hours look long.

## Rules

- The hours come from a simulated curve. Say "simulated" whenever you quote them.
- Do not recommend an action. Give urgency and let the main harness decide.
