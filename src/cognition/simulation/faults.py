"""Live fault engine: events become the thermal disturbance term; thermal.py is untouched."""

import json
import sqlite3

from cognition.domain import State, WorldEvent, now
from cognition.industries import PACKS, catalogue
from cognition.persistence.store import Store

MAX_ACTIVE = 10


def contribution(event: WorldEvent, thermal: float, gain: float, tick: int) -> float:
    """Disturbance an event adds at a tick: catalogue size x severity x ramp factor."""
    if event.state == "cleared":
        return 0.0
    if event.ramp_ticks == 0:
        factor = 1.0
    else:
        factor = min(1.0, max(0, tick - event.started_tick) / event.ramp_ticks)
    return thermal * gain * event.severity * factor


def active_effects(events: list[WorldEvent], industry, tick: int) -> dict[str, dict[str, float]]:
    """Sum catalogue effects by layer, scaled by severity and ramp, for non-cleared events."""
    known = catalogue(industry)
    totals: dict[str, dict[str, float]] = {}
    for event in events:
        if event.state == "cleared" or event.kind not in known:
            continue
        factor = (
            1.0
            if event.ramp_ticks == 0
            else min(1.0, max(0, tick - event.started_tick) / event.ramp_ticks)
        )
        for layer, values in known[event.kind].effects.items():
            for key, magnitude in values.items():
                layer_totals = totals.setdefault(layer, {})
                layer_totals[key] = layer_totals.get(key, 0.0) + magnitude * event.severity * factor
    return totals


def _save(db: sqlite3.Connection, event: WorldEvent) -> None:
    db.execute(
        "INSERT INTO world_events VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
        (event.id, event.model_dump_json()),
    )


def _audit(db: sqlite3.Connection, plant_id: str, kind: str, body: dict) -> None:
    db.execute(
        "INSERT INTO audit(incident_id,kind,body,time) VALUES (?,?,?,?)",
        (f"world:{plant_id}", kind, json.dumps(body), now().isoformat()),
    )


class FaultEngine:
    """Owns the lifecycle of injected events. Implements the connector's WorldHooks."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def events(self, plant_id: str, *, include_cleared: bool = True) -> list[WorldEvent]:
        found = [
            WorldEvent.model_validate(value)
            for value in self.store.records("world_events")
            if value["plant_id"] == plant_id
        ]
        found.sort(key=lambda event: event.created_at)
        return found if include_cleared else [e for e in found if e.state != "cleared"]

    def inject(
        self,
        plant_id: str,
        kind: str,
        *,
        severity: float = 0.7,
        ramp_ticks: int | None = None,
        duration_ticks: int | None = None,
    ) -> WorldEvent:
        state = self.store.plant(plant_id)
        definition = catalogue(state.spec.industry).get(kind)
        if definition is None:
            known = ", ".join(sorted(catalogue(state.spec.industry)))
            raise ValueError(f"Unknown event kind '{kind}'. Available: {known}")
        active = self.events(plant_id, include_cleared=False)
        if any(event.kind == kind for event in active):
            raise ValueError(f"'{kind}' is already active on this plant")
        if len(active) >= MAX_ACTIVE:
            raise ValueError("Too many active events; clear one first")
        event = WorldEvent(
            plant_id=plant_id,
            kind=kind,
            domain=definition.domain,
            severity=severity,
            ramp_ticks=definition.ramp_ticks if ramp_ticks is None else ramp_ticks,
            duration_ticks=duration_ticks,
            state="active"
            if (definition.ramp_ticks if ramp_ticks is None else ramp_ticks) == 0
            else "ramping",
            started_tick=state.tick,
        )
        with self.store.transaction() as db:
            _save(db, event)
            _audit(db, plant_id, f"{definition.domain}_injected", self._summary(event))
        return event

    def clear(self, plant_id: str, event_id: str, *, by: str = "operator") -> WorldEvent:
        """Operator or demo removal of an injected condition. Physical repair is `remedy`."""
        if by not in ("operator", "remedy"):
            raise ValueError("Invalid clear source")
        event = self._find(plant_id, event_id)
        if event.state == "cleared":
            return event
        tick = self.store.plant(plant_id).tick
        event.state, event.cleared_tick, event.cleared_by = "cleared", tick, by  # type: ignore[assignment]
        with self.store.transaction() as db:
            _save(db, event)
            _audit(db, plant_id, f"{event.domain}_cleared", self._summary(event))
        return event

    def remedy_in(self, db: sqlite3.Connection, event: WorldEvent, tick: int) -> float:
        """Apply a physical remedy inside the caller's transaction and return the disturbance
        it removed. Only the Gateway maintenance path may call this."""
        removed = event.applied
        event.state, event.cleared_tick, event.cleared_by = "cleared", tick, "remedy"  # type: ignore[assignment]
        event.applied = 0
        _save(db, event)
        _audit(db, event.plant_id, f"{event.domain}_cleared", self._summary(event))
        return removed

    def _find(self, plant_id: str, event_id: str) -> WorldEvent:
        for event in self.events(plant_id):
            if event.id == event_id:
                return event
        raise KeyError(event_id)

    @staticmethod
    def _summary(event: WorldEvent) -> dict:
        return {
            "correlation_id": event.id,
            "kind": event.kind,
            "severity": event.severity,
            "state": event.state,
            "cleared_by": event.cleared_by,
        }

    # WorldHooks: called by TwinConnector inside its own transaction.

    def apply(self, db: sqlite3.Connection, state: State) -> State:
        result = state.model_copy(deep=True)
        gain = PACKS[state.spec.industry].gain
        known = catalogue(state.spec.industry)
        for event in self.events(state.spec.id):
            thermal = known[event.kind].thermal if event.kind in known else 0.0
            before = event.model_copy()
            if event.state != "cleared" and event.duration_ticks is not None:
                if state.tick - event.started_tick >= event.duration_ticks:
                    event.state, event.cleared_tick, event.cleared_by = (  # type: ignore[assignment]
                        "cleared",
                        state.tick,
                        "duration",
                    )
            if event.state != "cleared":
                ramped = (
                    event.ramp_ticks == 0 or state.tick - event.started_tick >= event.ramp_ticks
                )
                event.state = "active" if ramped else "ramping"
            target = contribution(event, thermal, gain, state.tick)
            result.disturbance += target - event.applied
            event.applied = target
            if event != before:
                _save(db, event)
                if event.state != before.state:
                    _audit(db, state.spec.id, f"{event.domain}_{event.state}", self._summary(event))
        return result

    def offset(self, plant_id: str) -> float:
        return sum(event.applied for event in self.events(plant_id))

    def reset(self, db: sqlite3.Connection, plant_id: str) -> None:
        tick = self.store.plant(plant_id).tick
        for event in self.events(plant_id, include_cleared=False):
            event.state, event.cleared_tick, event.cleared_by = "cleared", tick, "reset"  # type: ignore[assignment]
            event.applied = 0
            _save(db, event)
            _audit(db, plant_id, f"{event.domain}_cleared", self._summary(event))
        for event in self.events(plant_id):
            if event.applied:
                event.applied = 0
                _save(db, event)
