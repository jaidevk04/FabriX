"""Offline analyser for the robot core: which robot could check what, and why."""

from cognition.cores.base import build_report
from cognition.cores.robot.monitor import MODEL, monitor
from cognition.domain import CoreReport

TOOL_FOR_MODALITY = {"learning": "vibration_probe", "vision": "visual"}


def reference(platform, plant_id: str) -> CoreReport:
    base = monitor(platform, plant_id)
    state = platform.store.plant(plant_id)
    fleet = platform.fleet.state(plant_id)
    zones = {zone.id: zone for zone in fleet.zones}
    plan = []
    for need in base.assessment.get("inspection_needs", []):
        zone = next((z for z in zones.values() if need["equipment"] in z.equipment), None)
        plan.append(
            {
                "equipment": need["equipment"],
                "zone": zone.id if zone else None,
                "hot_zone": bool(zone and zone.kind == "hot"),
                "robot": next((r.name for r in fleet.robots if r.kind == "inspector"), None),
                "note": "Hot zones need a zone-clear and heat check before entry.",
            }
        )
    summary = base.summary + (f" {len(plan)} inspection(s) could be planned." if plan else "")
    return build_report(
        state,
        "robot",
        base.alerts,
        summary,
        base.assessment | {"plan": plan},
        source="reference",
        model=MODEL,
    )
