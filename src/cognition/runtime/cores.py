"""CoreRuntime: runs the monitors after each sample and acts only on transitions."""

from datetime import timedelta

from cognition.control.gateway import Rejected
from cognition.cores.base import RANK
from cognition.cores.bus import CoreBus
from cognition.cores.registry import SPECS
from cognition.cores.robot.monitor import monitor as robot_monitor
from cognition.cores.runs import CoreBusy, RunStopped
from cognition.domain import CoreAlert, CoreReport, now
from cognition.industries import catalogue
from cognition.layers.perceptual.service import Observation

SOURCE = {"learning": "signal", "vision": "vision", "robot": "robot"}
DEBOUNCE = 3  # consecutive lower evaluations before an alert level may drop


class CoreRuntime:
    def __init__(self, platform) -> None:
        self.platform = platform
        self.bus = CoreBus(platform)
        # (plant, alert id) -> [effective level, consecutive lower count]
        self.levels: dict[tuple[str, str], list] = {}

    def live(self, plant_id: str, core: str, *, reference: bool = False) -> CoreReport:
        spec = SPECS[core]
        return (spec.reference if reference else spec.monitor)(self.platform, plant_id)

    async def analyse(self, plant_id: str, core: str, question: str = "") -> CoreReport:
        """Deeper analysis for ask_core. Offline reference analyser until an agent is attached."""
        self.platform.store.audit(
            f"cores:{plant_id}", "core_query", {"core": core, "question": question[:200]}
        )
        agents = self.platform.core_agents
        degraded = ""
        if agents.enabled:
            ok, reason = agents.available()
            if ok:
                try:
                    return await agents.analyse(plant_id, core, question)
                except RunStopped:
                    raise
                except CoreBusy:
                    # The core is already answering (a woken analysis or an earlier question).
                    # The harness still gets a prompt, deterministic answer instead of an error.
                    degraded = f"The {core} core agent was busy; reference analyser used."
                except Exception as error:
                    degraded = (
                        f"Agent run failed ({type(error).__name__}); reference analyser used."
                    )
            else:
                degraded = reason
        report = self.live(plant_id, core, reference=True)
        self.platform.store.audit(
            f"agent:{plant_id}:{core}",
            "reference_answer",
            {
                "status": report.status,
                "summary": report.summary[:400],
                "alerts": len(report.alerts),
            },
        )
        if core == "robot":
            report.assessment["verification"] = self.verify_suspicions(report)
        if degraded:
            report.degraded = True
            report.assessment["degraded_reason"] = degraded
        return report

    def verify_suspicions(self, report: CoreReport) -> list[dict]:
        """T0 verification: send the inspector to equipment other cores suspect (FleetGateway)."""
        results = []
        for need in report.assessment.get("inspection_needs", [])[:2]:
            equipment = need["equipment"]
            zone = next(
                (
                    z
                    for z in self.platform.fleet.state(report.plant_id).zones
                    if equipment in z.equipment
                ),
                None,
            )
            tools = (
                ["thermography"]
                if zone is not None and zone.kind == "hot"
                else ["vibration_probe", "visual"]
            )
            entry: dict = {"equipment": equipment, "findings": []}
            for tool in tools:
                try:
                    mission = self.platform.fleet_gateway.run(
                        report.plant_id,
                        "verify",
                        equipment,
                        tool=tool,
                        correlation=f"verify-{equipment}",
                    )
                except Rejected as error:
                    entry["refused"] = str(error)
                    break
                entry |= {"tool": tool, "mission": mission.id}
                entry["findings"] = mission.result["findings"]
                if entry["findings"]:
                    break
            results.append(entry)
        return results

    def reports(self, plant_id: str) -> list[CoreReport]:
        return [self.live(plant_id, core) for core in SPECS]

    def step(self, plant_id: str) -> None:
        """Evaluate monitors on the fresh sample; audit and publish on transitions only."""
        self.platform.signals.record(plant_id)
        learning = self.live(plant_id, "learning")
        vision = self.live(plant_id, "vision")
        robot = robot_monitor(self.platform, plant_id, [learning, vision])
        for report in (learning, vision, robot):
            self._transitions(report)

    def _transitions(self, report: CoreReport) -> None:
        plant_id, current = report.plant_id, {a.id: a for a in report.alerts}
        changed = False
        known = [
            key for key in self.levels if key[0] == plant_id and key[1].startswith(report.core)
        ]
        for key in known:
            if key[1] not in current:
                previous = self.levels[key][0]
                level = self.levels[key]
                level[1] += 1
                if level[1] >= DEBOUNCE:
                    del self.levels[key]
                    changed = True
                    self._audit(report, key[1], "core_alert_cleared", {"previous": previous})
        for alert in report.alerts:
            key = (plant_id, alert.id)
            entry = self.levels.get(key)
            if entry is None:
                self.levels[key] = [alert.level, 0]
                changed = True
                self._audit(report, alert.id, "core_alert", self._body(alert))
                self._wake(report, alert)
            elif RANK[alert.level] > RANK[entry[0]]:
                entry[0], entry[1] = alert.level, 0
                changed = True
                self._audit(report, alert.id, "core_alert", self._body(alert))
                self._wake(report, alert)
            elif RANK[alert.level] < RANK[entry[0]]:
                entry[1] += 1
                if entry[1] >= DEBOUNCE:
                    entry[0], entry[1] = alert.level, 0
                    changed = True
                    self._audit(report, alert.id, "core_alert", self._body(alert))
            else:
                entry[1] = 0
            if self.levels.get(key, [alert.level])[0] == "escalate":
                self._publish(report, alert, first=changed)
        if changed:
            self.platform.store.put("core_reports", f"{plant_id}:{report.core}", report)

    def _draft(self, report: CoreReport, alert: CoreAlert) -> None:
        try:
            self.platform.workorders.draft_from_alert(report, alert)
        except Exception as exc:
            self.platform.store.audit(
                f"cores:{report.plant_id}", "work_order_failed", {"type": type(exc).__name__}
            )

    def _wake(self, report: CoreReport, alert: CoreAlert) -> None:
        self._draft(report, alert)
        if RANK[alert.level] >= RANK["notify"] and self.platform.core_agents.enabled:
            self.platform.core_agents.wake(report, alert)

    @staticmethod
    def _body(alert: CoreAlert) -> dict:
        return {
            "alert": alert.id,
            "level": alert.level,
            "title": alert.title,
            "confidence": alert.confidence,
            "equipment": alert.equipment,
            "tick": alert.tick,
        }

    def _audit(self, report: CoreReport, alert_id: str, kind: str, body: dict) -> None:
        state = self.platform.store.plant(report.plant_id)
        known = catalogue(state.spec.industry)
        body = body | {
            "core": report.core,
            "correlation_id": self._correlation(report, alert_id, known),
        }
        self.platform.store.audit(f"cores:{report.plant_id}", kind, body)

    def _correlation(self, report: CoreReport, alert_id: str, known) -> str:
        """Link to the injected event on the same equipment so a chain can be followed in audit."""
        alert = next((a for a in report.alerts if a.id == alert_id), None)
        equipment = alert.equipment if alert else None
        for event in self.platform.faults.events(report.plant_id, include_cleared=False):
            if event.kind in known and known[event.kind].equipment == equipment:
                return event.id
        return alert_id

    def _publish(self, report: CoreReport, alert: CoreAlert, *, first: bool) -> None:
        state = self.platform.store.plant(report.plant_id)
        stamp = now()
        observation = Observation(
            id=f"{alert.id}"[:63],
            plant_id=report.plant_id,
            revision=state.revision,
            observed_at=stamp,
            expires_at=stamp + timedelta(seconds=30),
            source=SOURCE[report.core],  # type: ignore[arg-type]
            model=report.model,
            label=alert.title[:120],
            status="anomaly",
            confidence=alert.confidence,
            summary=alert.summary[:1200],
        )
        self.platform.perception.publish(state, observation, record=first)
