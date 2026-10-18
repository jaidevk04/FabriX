"""Sole command writer. Simulation atomicity is not an OT exactly-once guarantee."""

import hashlib
import json
from typing import Any

from cognition.control.connectors import CommandConnector, TwinConnector
from cognition.domain import Action, MaintenanceAction, Proposal, Receipt, State, now
from cognition.layers.reflexive import assess
from cognition.persistence.store import Store
from cognition.simulation.thermal import check_action, recovered, simulate


class Rejected(ValueError):
    pass


class Gateway:
    def __init__(self, store: Store, connector: CommandConnector | None = None) -> None:
        self.store = store
        self.connector = connector or TwinConnector(store)
        # Set by the platform once world services exist (MaintenanceDesk).
        self.maintenance: Any = None

    def validate(
        self,
        proposal: Proposal,
        allowed_plant: str,
        *,
        max_drift: int = 0,
        executing: bool = False,
    ) -> State:
        if proposal.plant_id != allowed_plant:
            raise Rejected("Plant is outside incident scope")
        state = self.connector.snapshot(allowed_plant)
        # Strict by default. Live mode allows bounded drift; the forecast below still runs on the
        # current state, and the expiry check keeps the window short.
        if not 0 <= state.revision - proposal.revision <= max_drift:
            raise Rejected("Plant state changed during investigation")
        if proposal.expires_at <= now():
            raise Rejected("Proposal expired")
        if not 0 <= (now() - state.sampled_at).total_seconds() <= 300:
            raise Rejected("Telemetry is stale or future-dated")
        action = proposal.action
        maintenance = isinstance(action, MaintenanceAction)
        if state.quality != "good" or (not maintenance and state.mode != "automatic"):
            raise Rejected("Valid telemetry and automatic mode required")
        if isinstance(action, MaintenanceAction):
            self._maintenance().check(state, action, executing=executing)
            return state
        if not assess(state)["cognitive_control_permitted"]:
            raise Rejected("Reflexive interlock or actuator fault blocks cognitive control")
        if action is None:
            raise Rejected("Escalation has no executable action")
        if not isinstance(action, Action):
            raise Rejected("This action is not a plant command")
        try:
            check_action(state, action)
        except ValueError as exc:
            raise Rejected(str(exc)) from exc
        forecast, baseline = simulate(state, action), simulate(state)
        if not forecast.safe or not forecast.recovered:
            raise Rejected("Simulation did not predict sustained safe recovery")
        if forecast.final_error >= baseline.final_error:
            raise Rejected("Action does not improve the baseline")
        return state

    def _maintenance(self) -> Any:
        if self.maintenance is None:
            raise Rejected("Maintenance control is not configured")
        return self.maintenance

    def execute(
        self,
        proposal: Proposal,
        command_id: str,
        allowed_plant: str,
        *,
        live: bool = False,
        max_drift: int = 0,
    ) -> Receipt:
        digest = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()
        with self.store.transaction() as db:
            try:
                receipt = Receipt.model_validate_json(self.store.get("commands", command_id))
            except KeyError:
                receipt = None
            if receipt is not None:
                if receipt.digest != digest or receipt.plant_id != allowed_plant:
                    raise Rejected("Command ID conflicts with an existing request")
                return receipt
            state = self.validate(proposal, allowed_plant, max_drift=max_drift, executing=True)
            action = proposal.action
            details: dict | None = None
            if isinstance(action, MaintenanceAction):
                final, trajectory, details = self._maintenance().apply(db, state, action, live=live)
            else:
                assert isinstance(action, Action)
                final, trajectory = self.connector.dispatch(state, action, live=live)
            receipt = Receipt(
                command_id=command_id,
                plant_id=allowed_plant,
                digest=digest,
                revision=final.revision,
                recovered=False if live else recovered(final, trajectory),
                trajectory=trajectory,
                verification="pending" if live else "completed",
            )
            db.execute(
                "UPDATE plants SET body=? WHERE id=?", (final.model_dump_json(), allowed_plant)
            )
            db.execute("INSERT INTO commands VALUES (?,?)", (command_id, receipt.model_dump_json()))
            db.execute(
                "INSERT INTO audit(incident_id,kind,body,time) VALUES (?,?,?,?)",
                (command_id, "command_committed", receipt.model_dump_json(), now().isoformat()),
            )
            if details is not None:
                self._maintenance().audit(db, command_id, details)
            else:
                assert isinstance(action, Action)
                self._record_effect(db, command_id, state, final, action)
            return receipt

    @staticmethod
    def _record_effect(db, command_id, before, after, action):
        db.execute(
            "INSERT INTO audit(incident_id,kind,body,time) VALUES (?,?,?,?)",
            (
                command_id,
                "action_applied",
                json.dumps(
                    {
                        "control": action.control,
                        "unit": action.unit,
                        "previous_value": before.duty,
                        "commanded_value": after.duty,
                        "actuator_before": before.actuator,
                        "actuator_after": after.actuator,
                        "temperature_before": before.temperature,
                        "temperature_after": after.temperature,
                        "transport": "gateway",
                        "revision": after.revision,
                    }
                ),
                now().isoformat(),
            ),
        )
