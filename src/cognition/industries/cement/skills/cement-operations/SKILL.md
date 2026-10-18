---
name: cement-operations
description: Investigate kiln thermal disturbances, draft, combustion and cooler context.
---

Use read_kiln_process to review the kiln context and simulate_kiln_duty to test permitted thermal-duty changes. Compare temperature, commanded duty, actual actuator position, telemetry quality and reflexive interlock status before interpreting oxygen, draft, meal feed, shell rotation or cooler estimates.

Consider conflicting combustion and cooling indicators. Derived indicators share the thermal model and are not independent corroboration. A vision or ML observation must include model identity, confidence, revision and freshness; do not treat low-confidence or contradictory evidence as control authority.

Heat-load disturbances may respond to a bounded duty reduction. A stuck actuator or bad sensor requires escalation. Never command fans, feed or kiln drives: those actuators are not implemented. Propose the smallest tested permitted adjustment and require sustained measured thermal recovery. Demo bands and instructions are not a commissioned plant SOP.
