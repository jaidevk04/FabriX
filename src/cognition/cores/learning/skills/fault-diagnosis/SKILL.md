---
name: fault-diagnosis
description: Work out which fault signature fits the deviating signals of one equipment item. Use after triage when an equipment group scores above the watch level and a cause is needed.
---

# Fault diagnosis

## Procedure

1. For each deviating waveform channel call `learning_read_features` with `response_format` set to `detailed`. Compare RMS and kurtosis with the baseline.
2. Rising RMS with rising kurtosis points to a localized mechanical problem such as a bearing. Rising RMS with unchanged kurtosis points to a level change such as imbalance or load.
3. Check scalar channels on the same equipment with `learning_compare_baseline`. Current rising with vibration supports a mechanical cause.
4. If a camera may show the same equipment, call `learning_request_evidence` for vision detections. A matching detection is independent corroboration.
5. State the best signature and the second-best, and say what would separate them.

## Limits

- Signal patterns suggest, they do not prove. Mark single-modality diagnoses as such.
- The sensor model is simulated. Do not claim it is trained or calibrated.
