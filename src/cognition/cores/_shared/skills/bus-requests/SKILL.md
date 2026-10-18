---
name: bus-requests
description: Ask another core for evidence through the core bus. Use when your own tools cannot settle a question and a peer core holds the missing signal, camera or fleet data.
---

# Bus requests

## Procedure

1. Decide what evidence is missing and which core owns it: learning for signals, vision for cameras, robot for fleet and zones.
2. Call your `request_evidence` tool with `to_core`, the matching `kind`, the equipment id and one short question.
3. Read the answer as evidence with its own limits. It may be old by the time you use it.

## Rules

- Requests are for evidence only. You cannot order another core to act.
- A request that would loop back to a core already in the chain is refused. Do not retry it with new wording.
- Ask once per question. If the answer is an error, use the hint or continue without it.
