# Core report fields

| Field | Meaning |
|---|---|
| `status` | `normal`, `watch` or `alert`, the worst alert level in the report |
| `alerts[].level` | `watch` is visible only, `notify` is queued, `escalate` can start an investigation |
| `alerts[].confidence` | the simulated model's confidence; not a calibrated probability |
| `stamp.revisions_behind` | how many plant revisions have passed since the report was made |
| `stamp.source` | `monitor`, `reference` or `agent` |
| `assessment` | core-specific detail; stage and remaining life for learning, candidates for vision |

All core models in this prototype are simulated and untrained. Say so when you cite them.
