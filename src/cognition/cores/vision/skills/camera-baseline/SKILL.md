---
name: camera-baseline
description: Judge whether a camera view deviates from normal at all. Use when a single camera gives an ambiguous result or when deciding whether a deviation is new.
---

# Camera baseline

## Procedure

1. Call `vision_compare_reference` for the camera.
2. A deviation index under 0.1 is normal for this prototype. Above 0.45 is a clear deviation.
3. Check `vision_read_detections` for the labels behind the index.

## Rules

- The reference is the healthy simulated view. It does not know about maintenance history or lighting changes.
