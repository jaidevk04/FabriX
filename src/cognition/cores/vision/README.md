# Vision core

Reads camera feeds through a simulated detector on generated placeholder frames.

## Authority

Evidence and sensitivity changes only. Never commands the plant.

## Escalation

An `escalate` alert publishes an anomaly observation, which starts a main-harness investigation.

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
| `vision_apply_monitor_config` | action | Apply the vision monitor configuration change that the platform approved. |
| `vision_compare_reference` | read | Compare what a camera shows now with its healthy reference view. |
| `vision_list_cameras` | read | List cameras with the equipment and zone each one watches. |
| `vision_measure_defect` | read | Measure a detection's size as a share of the frame and rate its extent. |
| `vision_read_detections` | read | Read the simulated detector's current detections with confidence and severity. |
| `vision_request_evidence` | read | Ask the learning or robot core for evidence about one piece of equipment. |

## Skills

| Skill | Use |
|---|---|
| `camera-baseline` | Judge whether a camera view deviates from normal at all. |
| `cross-camera-correlation` | Combine detections across cameras and with signal evidence. |
| `defect-triage` | Classify and size what the cameras report. |
| `core-report-writing`, `bus-requests` | shared by every core |

## Testing

- `pytest tests/cores` runs the monitor, reference analyser, tools and agent wiring offline.
- `tests/eval/vision/` holds the ADK eval set. The offline test replays it with a scripted model. Running it against a live model is done only with the owner's approval.
