# Robot core

Knows the simulated fleet, zones and safety rules. Plans and runs inspection and verification, and carries out approved repairs.

## Authority

Runs T0 and T1 missions through the fleet gateway automatically. Repairs run only as an approved order, and the plant Gateway validates them again.

## Escalation

Never escalates by itself. Its alerts are fleet health and inspection recommendations built from the other cores' evidence.

## Files

| File | Role |
|---|---|
| `instruction.md` | identity, boundaries, output contract |
| `agent.py` | assembles the ADK agent only |
| `schemas.py` | structured outputs |
| `monitor.py` | always-on deterministic simulated model, no LLM |
| `reference.py` | offline analyser with the same output as the agent |
| `tools/` | one tool per file |
| `skills/` | procedures (Agent Skills spec) |

## Tools

| Tool | Kind | What it does |
|---|---|---|
| `robot_check_mission` | read | Check whether a mission would be allowed, without running it. |
| `robot_execute_order` | action | Carry out the repair the platform approved: lock out, repair through the Gateway, unlock. |
| `robot_read_fleet` | read | Read each robot's zone, battery, status and tools, plus active lock-outs. |
| `robot_read_mission_result` | read | Read the stored result of a mission by id. |
| `robot_read_zones` | read | Read zones with their kind (dock, safe, process, hot), equipment and neighbours. |
| `robot_request_evidence` | read | Ask the learning or vision core for evidence about one piece of equipment. |
| `robot_run_mission` | fleet | Send a robot on an inspection, verification, sampling, patrol or transport mission. |

## Skills

| Skill | Use |
|---|---|
| `fleet-operations` | Read fleet health and choose a robot and tool. |
| `maintenance-procedures` | Review and carry out an approved repair order. |
| `mission-planning` | Plan an inspection or verification mission for suspect equipment. |
| `plant-safety-zones` | Apply zone, interlock and lock-out rules to robot work. |
| `core-report-writing`, `bus-requests` | shared by every core |

## Testing

- `pytest tests/cores` runs the monitor, reference analyser, tools and agent wiring offline.
- `tests/eval/robot/` holds the ADK eval set. The offline test replays it with a scripted model. Running it against a live model is done only with the owner's approval.
