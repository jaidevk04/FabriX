"""FleetGateway: the only writer of robot state. Tier T0 and T1 work runs here, automatically.

Repairs (tier T2) are not run here. They go through the plant Gateway as a maintenance
control; this gateway only provides the lock-out and unlock steps around them.
"""

from collections import deque

from cognition.control.gateway import Rejected
from cognition.domain import FleetState, Mission, Robot, State
from cognition.industries import catalogue
from cognition.persistence.store import Store
from cognition.sensing.fleet import Fleet
from cognition.simulation.faults import FaultEngine

KIND_ROBOT = {
    "inspect": ("inspector", "T0"),
    "verify": ("inspector", "T0"),
    "patrol": ("inspector", "T0"),
    "sample": ("carrier", "T0"),
    "transport": ("carrier", "T1"),
    "lockout": ("maintainer", "T2-prep"),
    "unlock": ("maintainer", "T2-prep"),
}
HOT_SAFE_TOOLS = {"thermography", "visual", "gauge_read"}
# Which kind of evidence each inspection tool can actually pick up.
TOOL_SEES = {
    "vibration_probe": "signal",
    "acoustic": "signal",
    "gauge_read": "signal",
    "thermography": "thermal",
    "visual": "camera",
}
HOP_COST, WORK_COST, RESERVE = 2.0, 3.0, 10.0


class Refused(Rejected):
    """A mission the fleet gateway will not run. Reported like any other rejection."""


class FleetGateway:
    def __init__(self, store: Store, fleet: Fleet, faults: FaultEngine) -> None:
        self.store, self.fleet, self.faults = store, fleet, faults

    @staticmethod
    def route(fleet: FleetState, start: str, goal: str) -> list[str]:
        graph = {zone.id: zone.next_to for zone in fleet.zones}
        queue, seen = deque([[start]]), {start}
        while queue:
            path = queue.popleft()
            if path[-1] == goal:
                return path
            for step in graph.get(path[-1], []):
                if step not in seen:
                    seen.add(step)
                    queue.append([*path, step])
        raise Refused(f"No route from {start} to {goal}")

    def run(
        self,
        plant_id: str,
        kind: str,
        target: str,
        *,
        tool: str = "",
        expect: str = "",
        correlation: str = "",
    ) -> Mission:
        try:
            mission = self._run(plant_id, kind, target, tool, expect)
        except Refused as error:
            self.store.audit(
                f"cores:{plant_id}",
                "mission_refused",
                {"correlation_id": correlation or kind, "kind": kind, "reason": str(error)},
            )
            raise
        self.store.audit(
            f"cores:{plant_id}",
            "mission_completed",
            {
                "correlation_id": correlation or mission.id,
                "mission": mission.id,
                "kind": kind,
                "tier": mission.tier,
                "target": target,
                "robot": mission.robot_id,
            },
        )
        return mission

    def _pick(self, fleet: FleetState, role: str, *, working: bool = False) -> Robot:
        ready = ("docked", "idle", "working") if working else ("docked", "idle")
        for robot in fleet.robots:
            if robot.kind == role and robot.status in ready:
                return robot
        raise Refused(f"No available {role} robot")

    def check(self, plant_id: str, kind: str, target: str, tool: str = "") -> dict:
        """Dry run of the same rules. Writes nothing."""
        try:
            _state, _fleet, robot, zone, path, cost = self._plan(plant_id, kind, target, tool)
        except Refused as error:
            return {"allowed": False, "reason": str(error)}
        return {
            "allowed": True,
            "robot": robot.name,
            "zone": zone.id,
            "route": path,
            "battery_cost": round(cost, 1),
            "tier": KIND_ROBOT[kind][1],
        }

    def recall(self, plant_id: str) -> dict:
        """Send every robot to the dock and release lock-outs. Used when automation stops."""
        fleet = self.fleet.state(plant_id)
        moved = [r.name for r in fleet.robots if r.zone != "dock" or r.status != "docked"]
        released = list(fleet.lockouts)
        for robot in fleet.robots:
            robot.zone, robot.status, robot.mission_id = "dock", "docked", None
        fleet.lockouts = []
        with self.store.transaction() as db:
            self.fleet.save(db, fleet)
        if moved or released:
            self.store.audit(
                f"cores:{plant_id}",
                "fleet_recalled",
                {"correlation_id": f"recall-{plant_id}", "robots": moved, "released": released},
            )
        return {"robots": moved, "released": released}

    def _plan(self, plant_id: str, kind: str, target: str, tool: str):
        if kind not in KIND_ROBOT:
            raise Refused(f"Unknown mission kind '{kind}'")
        role, tier = KIND_ROBOT[kind]
        state = self.store.plant(plant_id)
        fleet = self.fleet.state(plant_id)
        zone = next((z for z in fleet.zones if target in z.equipment), None)
        if kind == "patrol":
            zone = next(z for z in fleet.zones if z.id == "control")
        if zone is None:
            raise Refused(f"Unknown equipment '{target}' for this plant")
        if kind == "lockout" and target in fleet.lockouts:
            raise Refused(f"{target} is already locked out")
        if kind == "unlock" and target not in fleet.lockouts:
            raise Refused(f"{target} is not locked out")
        robot = self._pick(fleet, role, working=kind == "unlock")
        needs_tool = kind in ("inspect", "verify", "sample", "transport")
        if needs_tool and tool not in robot.tools:
            raise Refused(f"{robot.name} has no tool '{tool}'. Available: {', '.join(robot.tools)}")
        if zone.kind == "hot":
            if state.interlock:
                raise Refused("Hot zone entry is blocked while the reflexive interlock is active")
            if needs_tool and tool not in HOT_SAFE_TOOLS and kind in ("inspect", "verify"):
                raise Refused(f"Tool '{tool}' is not allowed in a hot zone")
        path = self.route(fleet, robot.zone, zone.id)
        cost = HOP_COST * (len(path) - 1) * (1 if kind in ("lockout", "unlock") else 2) + WORK_COST
        if robot.battery - cost < RESERVE:
            raise Refused(f"{robot.name} battery too low for this mission ({robot.battery:.0f}%)")
        return state, fleet, robot, zone, path, cost

    def _run(self, plant_id: str, kind: str, target: str, tool: str, expect: str) -> Mission:
        state, fleet, robot, zone, path, cost = self._plan(plant_id, kind, target, tool)
        tier = KIND_ROBOT[kind][1]
        steps = [f"move {' -> '.join(path)}"] if len(path) > 1 else []
        result = self._work(state, kind, target, tool, expect, steps)
        robot.battery = round(robot.battery - cost, 1)
        if kind == "lockout":
            fleet.lockouts.append(target)
            robot.zone, robot.status = zone.id, "working"
            steps.append(f"lock out {target}; stay in {zone.id}")
        else:
            if kind == "unlock":
                fleet.lockouts.remove(target)
            robot.zone, robot.status = "dock", "docked"
            steps.append("return to dock")
        mission = Mission(
            plant_id=plant_id,
            robot_id=robot.id,
            kind=kind,  # type: ignore[arg-type]
            tier=tier,  # type: ignore[arg-type]
            tool=tool,
            target=target,
            zone=zone.id,
            steps=steps,
            result=result,
            tick=state.tick,
            battery_used=round(cost, 1),
        )
        with self.store.transaction() as db:
            self.fleet.save(db, fleet)
            db.execute("INSERT INTO missions VALUES (?,?)", (mission.id, mission.model_dump_json()))
        return mission

    def _work(
        self, state: State, kind: str, target: str, tool: str, expect: str, steps: list[str]
    ) -> dict:
        if kind in ("inspect", "verify"):
            steps.append(f"{kind} {target} with {tool}")
            return self._inspect(state, target, tool, expect)
        if kind == "sample":
            steps.append(f"take {tool} from {target}; deliver to lab")
            return {"sample": f"{target}-{state.tick}", "delivered_to": "lab"}
        if kind == "transport":
            steps.append(f"carry {tool} to {target}")
            return {"delivered": tool, "to": target}
        if kind == "patrol":
            steps.append("zone-clear, gas and heat check")
            return {"zones_clear": True, "basis": "Simulated safety patrol."}
        return {}

    def _inspect(self, state: State, target: str, tool: str, expect: str) -> dict:
        """A physical look reveals what is really wrong on the equipment, if the tool can see it."""
        known = catalogue(state.spec.industry)
        sees = TOOL_SEES.get(tool, "")
        findings = []
        for event in self.faults.events(state.spec.id, include_cleared=False):
            definition = known.get(event.kind)
            if definition is None or definition.equipment != target or event.domain != "fault":
                continue
            visible = (
                bool(definition.effects.get("signal"))
                if sees == "signal"
                else bool(definition.effects.get("camera"))
                if sees == "camera"
                else definition.thermal > 0 or bool(definition.effects.get("camera"))
            )
            if visible:
                findings.append(
                    {
                        "fault": definition.id,
                        "name": definition.name,
                        "severity": round(event.severity, 2),
                        "remedy": definition.remedy,
                    }
                )
        result: dict = {
            "equipment": target,
            "tool": tool,
            "findings": findings,
            "normal": not findings,
            "basis": "Simulated inspection by a simulated robot; no physical equipment.",
        }
        if expect:
            result["confirmed"] = any(f["fault"] == expect for f in findings)
        return result
