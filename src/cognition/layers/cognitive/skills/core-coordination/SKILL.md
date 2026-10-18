---
name: core-coordination
description: Use the learning, vision, robot and optimization cores during an incident. Read when core tools are listed, a core alert triggered the investigation, or signal, camera or fleet evidence is needed beyond the thermal readings.
---

# Core coordination

The cores are specialist watchers. They give evidence and candidates. They never act and never change your scope.

## Procedure

1. Call `read_core_reports` first. It shows what each core believed when the incident began, with revision and age.
2. Call `read_core_live` for any core whose report is old or whose status is not normal. It is fast and uses no model.
3. Use `ask_core` only for one focused question the live state cannot answer, for example which fault signature fits a vibration pattern. Name the equipment in the question.
4. When two cores disagree, or one core disagrees with the thermal readings, ask each for the evidence behind its view before choosing.
5. For a duty change, call `request_optimization` and compare candidates with `simulate_action` before proposing.
6. Read `read_business`, `read_kpis` or `read_sustainability` when the choice affects orders, energy or CO2e.
7. For mechanical equipment anomalies (e.g. drive vibration, bearing wear), call `ask_core` with `core="robot"` to verify the equipment in person, and call `read_business` to verify the required spare part is in stock. If confirmed and in stock, propose a `MaintenanceAction(equipment, remedy)`. If the spare is out of stock or verification fails, escalate with the reason.

## Reading results

- Check `stamp.revisions_behind` and `age_seconds`. Treat old results as history.
- `source: reference` means an offline rule-based analyser answered, not a model.
- Derived estimates from one core are not independent confirmation of each other. A vision alert and a vibration alert on the same equipment are independent. Two outputs built from the same signal are not.

See `references/core-reports.md` for field meanings.
