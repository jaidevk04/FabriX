---
name: maintenance-procedures
description: Review and carry out an approved repair order. Use when an order for a maintenance action is bound to this run and you must decide whether to execute it.
---

# Maintenance procedures

## Procedure

1. Read the order in your prompt: equipment, remedy and the proposal summary.
2. Call `robot_read_fleet` and check the maintainer has battery and is available.
3. Call `robot_read_zones` for the equipment's zone and check the plant-safety-zones rules.
4. If everything is consistent, call `robot_execute_order` exactly once. It locks out, repairs through the Gateway and unlocks.
5. Report `executed` with the receipt, or `refused` with the reason.

## Rules

- You cannot change the equipment or remedy. If the order looks wrong, refuse it.
- Do not call the tool a second time after an error. Report the error.
