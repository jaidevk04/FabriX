---
name: defect-triage
description: Classify and size what the cameras report. Use at the start of every vision analysis, or when a vision alert fired and you must say what was seen and how bad it is.
---

# Defect triage

## Procedure

1. Call `vision_read_detections` with no camera to see every current detection.
2. For each detection call `vision_measure_defect` to get its size share and extent.
3. Rank by severity times confidence. Report the top detection first.
4. If nothing is detected, say the cameras show no deviation. Do not invent a finding.

## Rules

- Detections come from a simulated detector on placeholder frames. Say so.
- Confidence is not a calibrated probability.
