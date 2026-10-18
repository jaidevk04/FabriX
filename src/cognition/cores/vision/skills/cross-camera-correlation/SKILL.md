---
name: cross-camera-correlation
description: Combine detections across cameras and with signal evidence. Use when more than one camera reports something or when a detection needs a second, independent source.
---

# Cross-camera correlation

## Procedure

1. List detections from all cameras and group them by equipment.
2. Two cameras on the same equipment agree more than one. Cameras on different equipment may be one cause with two effects, for example a flame problem showing in both flame and shell views.
3. Call `vision_request_evidence` for the learning core's signal evidence on the same equipment.
4. Report agreement and disagreement separately.

## Rules

- A camera and a vibration signal are independent. Two camera views of the same hotspot are less so.
