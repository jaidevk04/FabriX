"""Offline analyser for the vision core: classify detections and correlate across cameras."""

from cognition.cores.base import build_report
from cognition.cores.vision.monitor import MODEL, monitor
from cognition.domain import CoreReport
from cognition.industries import catalogue


def reference(platform, plant_id: str) -> CoreReport:
    base = monitor(platform, plant_id)
    state = platform.store.plant(plant_id)
    labels: dict[str, list[str]] = {}
    for camera in platform.cameras.definitions(plant_id):
        for key, label in camera.detects.items():
            if any(d.label == label for d in platform.cameras.detections(plant_id, camera.id)):
                labels.setdefault(key, []).append(camera.id)
    candidates = []
    for fault in catalogue(state.spec.industry).values():
        keys = set(fault.effects.get("camera", {}))
        seen = sorted(keys & set(labels))
        if seen:
            cameras = sorted({c for key in seen for c in labels[key]})
            candidates.append(
                {
                    "fault": fault.id,
                    "equipment": fault.equipment,
                    "match": round(len(seen) / len(keys), 2),
                    "cameras": cameras,
                    "remedy": fault.remedy,
                }
            )
    candidates.sort(key=lambda c: (-c["match"], -len(c["cameras"])))
    summary = base.summary
    if candidates:
        summary += f" Visual signature points to {candidates[0]['fault']}."
    return build_report(
        state,
        "vision",
        base.alerts,
        summary,
        base.assessment | {"candidates": candidates[:3]},
        source="reference",
        model=MODEL,
    )
