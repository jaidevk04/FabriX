---
name: chemical-operations
description: Investigate jacketed-reactor thermal deviations with pressure and mixing context.
---

Use read_reactor_process and simulate_reactor_duty. Review thermal measurements, actuator lag, telemetry quality and reflexive status before interpreting pressure, inventory, agitation, conversion and circulation estimates.

The demo does not model reaction kinetics, relief-system capacity or runaway chemistry. Conversion and pressure estimates are illustrative and cannot establish process safety. Compare qualified ML or vision observations by confidence and freshness; report conflicts and escalate uncertain recovery rather than assuming a safe reaction state.

Only thermal-duty percent is implemented. Never invent dosing, vent, pressure, mixing or coolant controls; never bypass interlocks. Test the permitted adjustment, prefer minimal change and require sustained fresh in-band measurements. Escalate sensor faults, stuck actuators or manual operation. This skill is not a certified chemical-plant SOP.
