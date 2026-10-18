"""Simulated robot fleet on a plant zone graph. Missions and writes arrive with FleetGateway."""

import sqlite3

from cognition.domain import FleetState, Robot, State, Zone
from cognition.industries import ZONES
from cognition.persistence.store import Store

TOOLS = {
    "inspector": ["thermography", "visual", "acoustic", "vibration_probe", "gauge_read"],
    "maintainer": ["local_reset", "valve", "lubrication", "sensor_swap", "bearing_swap"],
    "carrier": ["spares", "samples", "material"],
}
NAMES = {"inspector": "Scout-1", "maintainer": "Wrench-1", "carrier": "Hauler-1"}


def initial_fleet(state: State) -> FleetState:
    zones = [
        Zone(
            id=z.id, name=z.name, kind=z.kind, equipment=list(z.equipment), next_to=list(z.next_to)
        )
        for z in ZONES[state.spec.industry]
    ]
    robots = [
        Robot(
            id=f"{state.spec.id}-{kind}",
            name=NAMES[kind],
            kind=kind,  # type: ignore[arg-type]
            zone="dock",
            tools=tools,
        )
        for kind, tools in TOOLS.items()
    ]
    return FleetState(plant_id=state.spec.id, zones=zones, robots=robots)


class Fleet:
    """Read side of the fleet. Also a no-op WorldHook that clears fleet state on plant reset."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def state(self, plant_id: str) -> FleetState:
        plant = self.store.plant(plant_id)
        try:
            return FleetState.model_validate_json(self.store.get("missions", f"fleet:{plant_id}"))
        except KeyError:
            return initial_fleet(plant)

    def save(self, db: sqlite3.Connection, fleet: FleetState) -> None:
        db.execute(
            "INSERT INTO missions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (f"fleet:{fleet.plant_id}", fleet.model_dump_json()),
        )

    def apply(self, db: sqlite3.Connection, state: State) -> State:
        """Docked robots recharge each tick. Only an already-stored fleet changes."""
        try:
            fleet = FleetState.model_validate_json(
                self.store.get("missions", f"fleet:{state.spec.id}")
            )
        except KeyError:
            return state
        charging = [r for r in fleet.robots if r.status == "docked" and r.battery < 100]
        for robot in charging:
            robot.battery = min(100.0, robot.battery + 5)
        if charging:
            self.save(db, fleet)
        return state

    def offset(self, plant_id: str) -> float:
        return 0.0

    def reset(self, db: sqlite3.Connection, plant_id: str) -> None:
        db.execute("DELETE FROM missions WHERE id=?", (f"fleet:{plant_id}",))
