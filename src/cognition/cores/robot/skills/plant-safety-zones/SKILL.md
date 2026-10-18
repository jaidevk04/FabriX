---
name: plant-safety-zones
description: Apply zone, interlock and lock-out rules to robot work. Use before any mission into a hot zone and when reviewing a repair order.
---

# Plant safety zones

## Rules

- Hot zones are blocked while the reflexive interlock is active.
- Only safe tools enter hot zones: thermography, visual and gauge read.
- A repair needs the equipment locked out and only the maintainer in its zone.
- A repair needs a matching fault, a spare in stock and the equipment out of its cooldown. The Gateway checks all of this again.

## Procedure

1. Read zones with `robot_read_zones` and the fleet with `robot_read_fleet`.
2. Confirm the target zone kind and that no other robot is there.
3. If a rule blocks the work, say which rule and stop. Do not look for a way around it.
