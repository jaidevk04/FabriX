---
name: proposal-and-escalation
description: Shape the final Proposal as exactly one action or one escalation with cited evidence. Read before returning a result, especially when choosing between a duty change and escalating to the operator.
---

# Proposal and escalation

## Procedure

1. Decide whether a tested, permitted action exists. If the reflexive layer blocks cognitive control, escalate.
2. If acting on a process or thermal deviation, choose the smallest change that the twin forecasts as safe and recovering. Confirm with `simulate_action`.
3. If acting on a mechanical equipment fault (e.g. bearing wear), propose `MaintenanceAction(equipment, remedy)` when verified by the robot core and the spare is in stock in `read_business`.
4. If escalating, say what is unresolved, what each source showed, and what the operator should check first.
5. Copy `plant_id` and `revision` from the snapshot. Use an expiry within 120 seconds.
6. Cite concise evidence: tool name, key value, and the revision or age of any core result.

## Never

- Propose more than one action, or an action and an escalation together.
- Assume a core report has the authority to act. Only the gateway commits commands.
- Hide a disagreement between sources to make the proposal cleaner.
