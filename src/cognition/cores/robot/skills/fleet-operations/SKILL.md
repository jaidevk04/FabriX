---
name: fleet-operations
description: Read fleet health and choose a robot and tool. Use when answering questions about robot availability, battery, positions or which robot can reach what.
---

# Fleet operations

## Procedure

1. Call `robot_read_fleet`. Note status, battery and zone for each robot.
2. A robot under 20 percent battery should charge before new work. Docked robots recharge each tick.
3. Use `robot_check_mission` to test a specific job before promising it.
4. Use `robot_read_mission_result` to recall an earlier result.

## Rules

- Report what the fleet can do now, not what it could do later.
