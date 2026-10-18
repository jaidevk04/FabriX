# Learning core

Reads sensor channels and fuses them through a simulated sensor language model.

## Authority

Evidence and monitor configuration only (mask a quiet channel for a limited time, set sensitivity). Never commands the plant.

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
| `learning_apply_monitor_config` | action | Apply the monitor configuration change that the platform approved for this order. |
| `learning_compare_baseline` | read | Compare a channel's current value with the healthy baseline of the simulated twin. |
| `learning_estimate_remaining_life` | read | Estimate degradation stage and remaining life from the fused sensor score. |
| `learning_list_channels` | read | List sensor channels and their latest values, optionally for one equipment item. |
| `learning_read_encoder_scores` | read | Read anomaly scores and tokens from the simulated sensor language model. |
| `learning_read_features` | read | Read RMS, kurtosis, crest factor and dominant frequency of a waveform channel. |
| `learning_request_evidence` | read | Ask the vision or robot core for evidence about one piece of equipment. |

## Skills

| Skill | Use |
|---|---|
| `condition-prognosis` | Estimate how far a degradation has progressed and how urgent it is. |
| `fault-diagnosis` | Work out which fault signature fits the deviating signals of one equipment item. |
| `signal-triage` | Rank which sensor channels and equipment deviate and decide what to look at first. |
| `core-report-writing`, `bus-requests` | shared by every core |

## Testing

- `pytest tests/cores` runs the monitor, reference analyser, tools and agent wiring offline.
- `tests/eval/learning/` holds the ADK eval set. The offline test replays it with a scripted model. Running it against a live model is done only with the owner's approval.
