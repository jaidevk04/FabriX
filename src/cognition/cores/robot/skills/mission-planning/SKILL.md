---
name: mission-planning
description: Plan an inspection or verification mission for suspect equipment. Use when evidence points at equipment and a physical check would settle the doubt.
---

# Mission planning

## Procedure

1. Call `robot_check_mission` for the candidate mission. Read the route and battery cost.
2. Choose the tool that can see the suspected problem: `vibration_probe` or `acoustic` for mechanical wear, `thermography` for heat, `visual` for surface problems.
3. For hot zones use `thermography`, `visual` or `gauge_read` only.
4. Run it with `robot_run_mission`. For a suspected fault pass its id in `expect` so the result says confirmed or not.
5. Report what the inspection found and what it could not see with that tool.

## Rules

- Only inspect, verify, sample, patrol and transport missions are yours to run. Repairs come as approved orders.
