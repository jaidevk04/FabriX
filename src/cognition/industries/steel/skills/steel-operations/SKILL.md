---
name: steel-operations
description: Investigate reheating furnace thermal deviations and combustion context.
---

Use read_furnace_process and simulate_furnace_duty. Review furnace temperature, thermal setpoint, actuator tracking and reflexive status. Interpret furnace pressure, oxygen, slab core estimate, fuel flow and uniformity together, with source provenance.

Surface temperature is not a calibrated slab-core measurement. Estimated uniformity is not proof of metallurgical quality. Treat conflicts between learned quality observations and thermal indications explicitly; request an approved specialist when available or escalate uncertainty.

Only thermal-duty percent is implemented. Do not invent conveyor, residence-time, oxygen-valve or burner-zone control commands. Never disable interlocks or alter PLC policy. Escalate stale or invalid telemetry, manual mode and actuator faults. Test bounded adjustments on the twin and verify sustained measured recovery. This educational pack is not a commissioned furnace recipe.
