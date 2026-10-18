"""Vision core monitor: per-camera defect and baseline-deviation detection (simulated)."""

from cognition.cores.base import build_report, confidence_for, level_for
from cognition.domain import CoreAlert, CoreReport

MODEL = "simulated-detector-v0"


def monitor(platform, plant_id: str) -> CoreReport:
    state = platform.store.plant(plant_id)
    alerts, cameras = [], {}
    for camera in platform.cameras.definitions(plant_id):
        found = platform.cameras.detections(plant_id, camera.id)
        score = max((d.severity * d.confidence for d in found), default=0.0)
        score = min(1.0, score * platform.config_desk.get(plant_id, "vision").sensitivity)
        cameras[camera.id] = {"detections": len(found), "score": round(score, 3)}
        level = level_for(score)
        if level == "info":
            continue
        alerts.append(
            CoreAlert(
                id=f"vision-{camera.id.replace('_', '-')}",
                plant_id=plant_id,
                core="vision",
                level=level,
                title=f"{camera.name}: {found[0].label}",
                summary="; ".join(
                    f"{d.label} (confidence {d.confidence}, severity {d.severity})" for d in found
                ),
                confidence=confidence_for(score),
                equipment=camera.equipment,
                evidence=[
                    f"{camera.id}: {d.label} box={d.box} confidence={d.confidence}" for d in found
                ][:10],
                revision=state.revision,
                tick=state.tick,
            )
        )
    summary = (
        "No defects or baseline deviations detected on any camera."
        if not alerts
        else f"{len(alerts)} camera(s) report detections."
    )
    return build_report(state, "vision", alerts, summary, {"cameras": cameras}, model=MODEL)
