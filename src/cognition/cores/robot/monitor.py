"""Robot core monitor: fleet health and inspection needs (no missions are issued here)."""

from cognition.cores.base import RANK, build_report, level_for
from cognition.domain import CoreAlert, CoreReport

MODEL = "simulated-fleet-monitor-v0"


def inspection_needs(peers: list[CoreReport]) -> list[dict]:
    """Equipment that other cores' evidence says deserves a physical look. No hidden labels."""
    needs: dict[str, float] = {}
    for report in peers:
        for alert in report.alerts:
            if alert.equipment and RANK[alert.level] >= RANK["notify"]:
                needs[alert.equipment] = max(needs.get(alert.equipment, 0.0), alert.confidence)
    return [{"equipment": e, "priority": round(p, 3)} for e, p in sorted(needs.items())]


def monitor(platform, plant_id: str, peers: list[CoreReport] | None = None) -> CoreReport:
    from cognition.cores.learning.monitor import monitor as learning
    from cognition.cores.vision.monitor import monitor as vision

    state = platform.store.plant(plant_id)
    if peers is None:
        peers = [learning(platform, plant_id), vision(platform, plant_id)]
    fleet = platform.fleet.state(plant_id)
    alerts: list[CoreAlert] = []

    def add(alert_id: str, score: float, title: str, summary: str, equipment: str | None = None):
        level = level_for(score)
        if level == "info":
            return
        alerts.append(
            CoreAlert(
                id=alert_id,
                plant_id=plant_id,
                core="robot",
                # The robot core never escalates to the main harness by itself.
                level="notify" if level == "escalate" else level,
                title=title,
                summary=summary,
                confidence=0.7,
                equipment=equipment,
                evidence=[summary],
                revision=state.revision,
                tick=state.tick,
            )
        )

    for robot in fleet.robots:
        if robot.status == "fault":
            add(f"robot-fault-{robot.kind}", 0.55, f"{robot.name} fault", f"{robot.name} fault.")
        elif robot.battery < 20 and robot.status != "charging":
            add(
                f"robot-battery-{robot.kind}",
                0.3,
                f"{robot.name} battery low",
                f"{robot.name} at {robot.battery:.0f}%.",
            )
    needs = inspection_needs(peers)
    for need in needs:
        add(
            f"robot-inspect-{need['equipment']}",
            0.5,
            f"Inspection recommended: {need['equipment']}",
            f"Signal or vision evidence suggests a physical check of {need['equipment']}.",
            need["equipment"],
        )
    ready = [r.name for r in fleet.robots if r.status in ("docked", "idle") and r.battery >= 20]
    summary = (
        f"Fleet ready: {', '.join(ready) or 'none'}."
        if not alerts
        else f"{len(alerts)} fleet or inspection item(s) need attention."
    )
    return build_report(
        state,
        "robot",
        alerts,
        summary,
        {"ready": ready, "inspection_needs": needs},
        model=MODEL,
    )
