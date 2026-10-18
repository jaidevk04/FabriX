"""Maintenance control preconditions and effect. Used only by Gateway; never by an agent."""

import json
import sqlite3

from cognition.business.model import BusinessModel, parameters
from cognition.control.gateway import Rejected
from cognition.domain import MaintenanceAction, State, WorldEvent, now
from cognition.industries import catalogue
from cognition.sensing.fleet import Fleet
from cognition.simulation.faults import FaultEngine
from cognition.simulation.thermal import advance, simulate

COOLDOWN_TICKS = 30


class MaintenanceDesk:
    def __init__(self, faults: FaultEngine, business: BusinessModel, fleet: Fleet) -> None:
        self.faults, self.business, self.fleet = faults, business, fleet

    def check(self, state: State, action: MaintenanceAction, *, executing: bool) -> WorldEvent:
        """Return the fault this repair would clear, or raise Rejected with the reason."""
        fleet = self.fleet.state(state.spec.id)
        zone = next((z for z in fleet.zones if action.equipment in z.equipment), None)
        if zone is None:
            raise Rejected(f"Unknown equipment '{action.equipment}' for this plant")
        if state.interlock:
            raise Rejected("Reflexive interlock blocks maintenance work")
        event = self._matching_fault(state, action)
        # Expected effect on the twin: removing the fault's heat load must not make things worse.
        repaired = state.model_copy(update={"disturbance": state.disturbance - event.applied})
        if simulate(repaired).final_error > simulate(state).final_error + 1e-9:
            raise Rejected("Twin forecast does not show the repair helping")
        params = parameters(state)
        if action.remedy not in params.remedy_spare:
            raise Rejected(f"Unknown remedy '{action.remedy}'")
        part = params.remedy_spare[action.remedy]
        if part is not None:
            events = self.faults.events(state.spec.id)
            ledger = self.business.ledger(state)
            if self.business.spares_available(ledger, events).get(part, 0) <= 0:
                lead = params.spares[part][1]
                raise Rejected(f"Spare '{part}' is not in inventory (lead time {lead:.0f} h)")
        last = fleet.last_maintenance.get(action.equipment)
        if last is not None and state.tick - last < COOLDOWN_TICKS:
            raise Rejected(f"{action.equipment} is in its maintenance cooldown")
        if executing:
            if action.equipment not in fleet.lockouts:
                raise Rejected(f"Lock-out step required on {action.equipment} before repair")
            crew = [r for r in fleet.robots if r.zone == zone.id]
            if not any(r.kind == "maintainer" for r in crew) or len(crew) != 1:
                raise Rejected(f"Zone {zone.id} is not clear: only the maintainer may be present")
        return event

    def _matching_fault(self, state: State, action: MaintenanceAction) -> WorldEvent:
        known = catalogue(state.spec.industry)
        for event in self.faults.events(state.spec.id, include_cleared=False):
            definition = known.get(event.kind)
            if (
                definition is not None
                and event.domain == "fault"
                and definition.equipment == action.equipment
                and definition.remedy == action.remedy
            ):
                return event
        raise Rejected(
            f"No active fault on {action.equipment} is cleared by remedy '{action.remedy}'"
        )

    def apply(
        self, db: sqlite3.Connection, state: State, action: MaintenanceAction, *, live: bool
    ) -> tuple[State, list[float], dict]:
        """Clear the fault, use the spare, record cooldown. Runs inside the Gateway transaction."""
        event = self._matching_fault(state, action)
        params = parameters(state)
        part = params.remedy_spare[action.remedy]
        removed = self.faults.remedy_in(db, event, state.tick)
        self.business.record_repair(db, state, part, params.repair_hours.get(action.remedy, 0.0))
        fleet = self.fleet.state(state.spec.id)
        fleet.last_maintenance[action.equipment] = state.tick
        self.fleet.save(db, fleet)
        final = state.model_copy(deep=True)
        final.disturbance -= removed
        final.revision += 1
        final.sampled_at = now()
        trajectory = [final.temperature]
        if not live:
            final, trajectory = advance(final)
        details = {
            "control": "maintenance",
            "equipment": action.equipment,
            "remedy": action.remedy,
            "fault": event.kind,
            "fault_event": event.id,
            "spare_used": part,
            "downtime_hours": params.repair_hours.get(action.remedy, 0.0),
            "disturbance_removed": round(removed, 3),
            "temperature_before": state.temperature,
            "temperature_after": final.temperature,
            "transport": "gateway",
            "revision": final.revision,
        }
        return final, trajectory, details

    @staticmethod
    def audit(db: sqlite3.Connection, command_id: str, details: dict) -> None:
        db.execute(
            "INSERT INTO audit(incident_id,kind,body,time) VALUES (?,?,?,?)",
            (command_id, "maintenance_applied", json.dumps(details), now().isoformat()),
        )
