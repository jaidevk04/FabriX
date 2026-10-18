---
name: maintenance-windows
description: Decide when to repair, who gets scarce spares and which robot goes first. Use when diagnoses exist and the question is about timing against orders, parts or the fleet.
---

# Maintenance windows

## Procedure

1. Call `optimization_solve_assignment` with `problem` set to `maintenance_window`. Read the plans: repair now, after a named order, or no repair within the horizon.
2. Compare late orders, late tonnes and net value. A repair has downtime, so repairing now is not always best when a rush order is close.
3. Call it again with `spares` if stock is short. Report which repairs are served and which wait, and the lead time for the part.
4. Call it with `robots` when several checks are needed at once.

## Rules

- The plan uses sensor-derived diagnoses only. If none exist, ask the learning core first.
- Prices, downtimes and rates are placeholders. Say the plan is a simulated comparison.
- You recommend a window. The main harness proposes, and the Gateway validates.
