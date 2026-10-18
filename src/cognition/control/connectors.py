"""Connector seam; only the twin connector is implemented in this base release."""

import sqlite3
from typing import Protocol

from cognition.domain import Action, State
from cognition.persistence.store import Store
from cognition.simulation.thermal import Scenario, advance, inject, onboard


class ReadConnector(Protocol):
    def snapshot(self, plant_id: str) -> State: ...


class CommandConnector(ReadConnector, Protocol):
    def dispatch(
        self, state: State, action: Action, *, live: bool = False
    ) -> tuple[State, list[float]]: ...


class WorldHooks(Protocol):
    """Live-world effects applied inside the connector's own transactions (never commands)."""

    def apply(self, db: sqlite3.Connection, state: State) -> State: ...

    def offset(self, plant_id: str) -> float: ...

    def reset(self, db: sqlite3.Connection, plant_id: str) -> None: ...


class TwinConnector:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.world: WorldHooks | None = None

    def snapshot(self, plant_id: str) -> State:
        return self.store.plant(plant_id)

    def dispatch(
        self, state: State, action: Action, *, live: bool = False
    ) -> tuple[State, list[float]]:
        """Prepare an authorized command; gateway owns its transaction and receipt."""
        result = state.model_copy(deep=True)
        result.duty = action.value
        result.revision += 1
        return (result, [result.temperature]) if live else advance(result)

    def tick(self, plant_id: str, steps: int = 1) -> State:
        """Generate a fresh simulator sample independently of browser polling."""
        with self.store.transaction() as db:
            current = self.snapshot(plant_id)
            if self.world is not None:
                current = self.world.apply(db, current)
            state, _ = advance(current, steps)
            db.execute("UPDATE plants SET body=? WHERE id=?", (state.model_dump_json(), plant_id))
        return state

    def disturb(self, plant_id: str, scenario: Scenario) -> State:
        with self.store.transaction() as db:
            state = inject(self.snapshot(plant_id), scenario)
            if self.world is not None:
                state.disturbance += self.world.offset(plant_id)
            db.execute("UPDATE plants SET body=? WHERE id=?", (state.model_dump_json(), plant_id))
        return state

    def reset(self, plant_id: str) -> State:
        with self.store.transaction() as db:
            current = self.snapshot(plant_id)
            if self.world is not None:
                self.world.reset(db, plant_id)
            state = onboard(current.spec)
            state.revision = current.revision + 1
            db.execute("UPDATE plants SET body=? WHERE id=?", (state.model_dump_json(), plant_id))
        return state
