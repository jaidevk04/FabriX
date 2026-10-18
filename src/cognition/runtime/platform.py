"""Incident lifecycle owned by the platform, not the agent framework."""

import asyncio
import os
from datetime import timedelta
from typing import Any

from cognition.business.model import BusinessModel
from cognition.capabilities.registry import Manifest, Registry, default_manifest
from cognition.control.connectors import TwinConnector
from cognition.control.fleet_gateway import FleetGateway
from cognition.control.gateway import Gateway, Rejected
from cognition.control.maintenance import MaintenanceDesk
from cognition.cores.agents import CoreAgents
from cognition.cores.config import CoreConfigDesk
from cognition.cores.runs import RunStopped
from cognition.domain import (
    Incident,
    MonitorConfigAction,
    PlantSpec,
    Proposal,
    Receipt,
    Request,
    now,
)
from cognition.harnesses.base import Harness
from cognition.harnesses.errors import HarnessFailure
from cognition.insights import impact
from cognition.insights.workorders import WorkOrders
from cognition.layers.cognitive.tools import Tools
from cognition.layers.perceptual.service import Observation, Perception
from cognition.persistence.store import Store
from cognition.runtime.cores import CoreRuntime
from cognition.runtime.orders import OrderService
from cognition.runtime.world import WorldClock, WorldEffects
from cognition.sensing.cameras import CameraBank
from cognition.sensing.fleet import Fleet
from cognition.sensing.signals import SignalBus
from cognition.simulation.faults import FaultEngine
from cognition.simulation.thermal import onboard

PROPOSAL_WINDOW_SECONDS = 120  # how long a proposal stays valid once it has arrived


class Platform:
    def __init__(self, store: Store, timeout: float = 120) -> None:
        self.store = store
        self.connector = TwinConnector(store)
        self.gateway = Gateway(store, self.connector)
        self.registry = Registry(store)
        self.timeout = timeout
        self.busy: set[str] = set()
        self.investigations: dict[
            str, asyncio.Task
        ] = {}  # running resolve() per plant, for the kill switch
        self.automation: Any = None  # set by Automation, so the kill switch can stop it
        # Strict mode keeps the old behaviour: investigations freeze sampling, no revision drift.
        self.strict = os.getenv("COGNITION_STRICT_MODE", "").lower() in ("1", "true", "yes")
        self.live_drift = 0 if self.strict else int(os.getenv("COGNITION_LIVE_DRIFT", "300"))
        self.perception = Perception(store)
        self.faults = FaultEngine(store)
        self.business = BusinessModel(store, self.faults)
        self.signals = SignalBus(store, self.faults)
        self.cameras = CameraBank(store, self.faults)
        self.fleet = Fleet(store)
        self.connector.world = WorldEffects(self.faults, self.business, self.fleet)
        self.world = WorldClock(self)
        self.config_desk = CoreConfigDesk(store)
        self.fleet_gateway = FleetGateway(store, self.fleet, self.faults)
        self.gateway.maintenance = MaintenanceDesk(self.faults, self.business, self.fleet)
        self.core_agents = CoreAgents(self)
        self.cores = CoreRuntime(self)
        self.orders = OrderService(self)
        self.workorders = WorkOrders(self)

    def validate_action(self, proposal: Proposal, plant_id: str, *, live: bool) -> None:
        """Validate before approval. Plant commands go to the Gateway; config to its desk."""
        action = proposal.action
        if isinstance(action, MonitorConfigAction):
            if proposal.plant_id != plant_id:
                raise Rejected("Plant is outside incident scope")
            if proposal.expires_at <= now():
                raise Rejected("Proposal expired")
            self.config_desk.validate(self, plant_id, action)
            return
        self.gateway.validate(proposal, plant_id, max_drift=self.live_drift if live else 0)

    def sample(self, plant_id: str):
        """Advance one tick, then let the core monitors react. Monitor faults never stop it."""
        state = self.connector.tick(plant_id)
        try:
            self.cores.step(plant_id)
        except Exception as exc:
            self.store.audit(
                f"cores:{plant_id}", "core_runtime_error", {"type": type(exc).__name__}
            )
        return state

    def reset(self, plant_id: str):
        """Return a plant to its baseline and clear every injected event."""
        state = self.connector.reset(plant_id)
        self.signals.clear(plant_id)
        self.world.tripped.pop(plant_id, None)
        if self.automation is not None:
            self.automation.clear_finished(plant_id)
        self.store.audit(f"world:{plant_id}", "plant_reset", {"revision": state.revision})
        return state

    def onboard(self, spec: PlantSpec) -> None:
        self.store.put("plants", spec.id, onboard(spec), create=True)
        self.registry.register(default_manifest(spec))

    def onboard_manifest(self, manifest: Manifest) -> None:
        self.store.put("plants", manifest.plant.id, onboard(manifest.plant), create=True)
        self.registry.register(manifest)

    def disturb(self, plant_id, scenario):
        state = self.connector.disturb(
            plant_id, "heat_load" if scenario == "perception_conflict" else scenario
        )
        if scenario == "perception_conflict":
            self.perception.publish(
                state,
                Observation(
                    id="demo-conflict",
                    plant_id=plant_id,
                    revision=state.revision,
                    observed_at=now(),
                    expires_at=now() + timedelta(seconds=120),
                    source="demo",
                    model="demo-quality-detector",
                    label="Conflicting quality assessment",
                    status="normal",
                    confidence=0.85,
                    summary=(
                        "Synthetic test evidence reports normal operation while thermal readings "
                        "show a disturbance. This is not a trained model result."
                    ),
                ),
            )
        return state

    def reconcile(self) -> None:
        """Recover receipts after a crash; never blindly repeat an investigation."""
        for incident in self.store.incidents():
            if incident.status not in ("investigating", "verifying", "awaiting_approval"):
                continue
            try:
                receipt = Receipt.model_validate_json(self.store.get("commands", incident.id))
            except KeyError:
                incident.status = "interrupted"
                incident.reason = "Start a new investigation from current state."
            else:
                incident.status = "resolved" if receipt.recovered else "escalated"
                incident.trajectory = receipt.trajectory
                incident.reason = "Reconciled from committed simulation receipt."
            self.store.put("incidents", incident.id, incident)
            self.store.audit(incident.id, "reconciled", {"status": incident.status})

    async def resolve(
        self,
        plant_id: str,
        harness: Harness,
        *,
        incident_id: str | None = None,
        live: bool = False,
        approval_required: bool = False,
    ) -> Incident:
        if plant_id in self.busy:
            raise ValueError("An investigation is already active for this plant")
        self.busy.add(plant_id)
        current = asyncio.current_task()
        if current is not None:
            self.investigations[plant_id] = current
        try:
            return await self._resolve(
                plant_id,
                harness,
                incident_id=incident_id,
                live=live,
                approval_required=approval_required,
            )
        finally:
            self.busy.discard(plant_id)
            self.investigations.pop(plant_id, None)

    async def kill(self, plant_id: str, after_seconds: float) -> None:
        """Kill switch: stop the world clock, automation, core agents, robots and any investigation.

        Plant commands already applied stay in effect. Runs end `interrupted`, nothing is retried,
        and the plant can be reset and started again.
        """
        self.world.tripped[plant_id] = {"after_seconds": after_seconds, "at": now().isoformat()}
        self.store.audit(
            f"world:{plant_id}", "kill_switch_tripped", {"after_seconds": after_seconds}
        )
        await self.world.stop(plant_id)
        if self.automation is not None:
            await self.automation.disable(plant_id)
            state = self.automation.state(plant_id)
            state.reason = (
                f"Kill switch tripped after {after_seconds:g} s. Reset or start a new run."
            )
            self.automation.save(state)
        else:
            await self.core_agents.stop_all_and_wait(plant_id)
            self.fleet_gateway.recall(plant_id)
        task = self.investigations.get(plant_id)
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _adopt_replan(self, incident: Incident) -> None:
        """Show the plan actually applied when the order was re-sized from the live state."""
        order = self.orders.for_incident(incident.id)
        if order is not None and order.replanned is not None:
            incident.proposal = order.replanned

    async def _resolve(
        self,
        plant_id: str,
        harness: Harness,
        *,
        incident_id: str | None,
        live: bool,
        approval_required: bool,
    ) -> Incident:
        snapshot = self.connector.snapshot(plant_id)
        incident = Incident(
            plant_id=plant_id,
            harness=harness.capabilities().name,
            status="investigating",
            origin="automation" if live else "manual",
        )
        if incident_id is not None:
            incident.id = incident_id
        self.store.put("incidents", incident.id, incident, create=True)
        self.store.audit(
            incident.id, "started", {"revision": snapshot.revision, "tick": snapshot.tick}
        )
        request = Request(incident_id=incident.id, snapshot=snapshot)
        try:
            raw = await asyncio.wait_for(
                harness.propose(
                    request,
                    Tools(
                        request,
                        self.store,
                        perceptual=self.perception.assess(snapshot),
                        services=self,
                    ),
                ),
                timeout=self.timeout,
            )
            proposal = Proposal.model_validate(raw)
            if proposal.plant_id != plant_id or proposal.revision != snapshot.revision:
                raise Rejected("Proposal does not match incident scope or snapshot")
            if proposal.action is not None:
                # The window starts when the proposal arrives. A model's own expiry can already be
                # in the past after a long investigation, which wasted whole runs.
                proposal = proposal.model_copy(
                    update={"expires_at": now() + timedelta(seconds=PROPOSAL_WINDOW_SECONDS)}
                )
            incident.proposal = proposal
            self.store.audit(incident.id, "proposed", proposal.model_dump(mode="json"))
            if proposal.action is None:
                incident.status = "escalated"
                incident.reason = proposal.escalation or "Operator review required."
            elif approval_required:
                self.validate_action(proposal, plant_id, live=live)
                incident.status = "awaiting_approval"
                incident.reason = "Validated proposal awaits local operator approval."
                self.store.audit(incident.id, "approval_requested", {})
            else:
                outcome = await self.orders.execute(
                    incident.id,
                    proposal,
                    incident.id,
                    plant_id,
                    live=live,
                    max_drift=self.live_drift if live else 0,
                )
                self._adopt_replan(incident)
                if isinstance(outcome, Receipt):
                    incident.status = (
                        "verifying" if live else "resolved" if outcome.recovered else "escalated"
                    )
                    incident.trajectory = outcome.trajectory
                    incident.reason = (
                        "Command applied; waiting for fresh simulator measurements."
                        if live
                        else "Measured sustained recovery."
                        if outcome.recovered
                        else "Recovery failed."
                    )
                else:
                    incident.status = "resolved"
                    incident.reason = "Monitor configuration applied."
        except RunStopped:
            # The operator pressed Stop on a core run. The incident ends interrupted.
            incident.status = "interrupted"
            incident.reason = "A core run was stopped by the operator."
            self.store.audit(incident.id, "cancelled", {"source": "core-stop"})
        except asyncio.CancelledError:
            incident.status = "interrupted"
            incident.reason = "Investigation cancelled."
            self.store.put("incidents", incident.id, incident)
            self.store.audit(incident.id, "cancelled", {})
            raise
        except Rejected as exc:
            self._adopt_replan(incident)
            incident.status = "escalated"
            incident.reason = str(exc)
        except HarnessFailure as exc:
            incident.status = "failed"
            incident.reason = f"{exc} No automatic retry."
        except Exception as exc:
            # SDK error strings can contain request headers/credentials: do not persist them.
            incident.status = "failed"
            incident.reason = f"Harness failure ({type(exc).__name__}); no automatic retry."
        self.store.put("incidents", incident.id, incident)
        self.store.audit(incident.id, "completed", {"status": incident.status})
        self.close_impact(incident)
        return incident

    def close_impact(self, incident: Incident) -> None:
        """Record the impact once an incident with an order is final. Never blocks the flow."""
        try:
            impact.close(self, incident)
        except Exception as exc:
            self.store.audit(incident.id, "impact_failed", {"type": type(exc).__name__})

    async def approve(
        self, incident_id: str, *, accepted: bool, actor: str = "local-operator"
    ) -> Incident:
        incident = Incident.model_validate_json(self.store.get("incidents", incident_id))
        if incident.status != "awaiting_approval":
            raise ValueError("Incident is not awaiting approval")
        self.store.audit(incident.id, "approval_decided", {"actor": actor, "accepted": accepted})
        if not accepted:
            incident.status, incident.reason = (
                "escalated",
                (
                    "Approval window expired."
                    if actor == "expiry-policy"
                    else "Operator rejected the proposed action."
                ),
            )
        else:
            assert incident.proposal is not None
            try:
                outcome = await self.orders.execute(
                    incident.id,
                    incident.proposal,
                    incident.id,
                    incident.plant_id,
                    live=True,
                    max_drift=self.live_drift,
                )
                self._adopt_replan(incident)
                if isinstance(outcome, Receipt):
                    incident.status = "verifying"
                    incident.reason = "Approved command applied; waiting for fresh measurements."
                    incident.trajectory = outcome.trajectory
                else:
                    incident.status = "resolved"
                    incident.reason = "Monitor configuration applied."
            except Rejected as error:
                self._adopt_replan(incident)
                incident.status, incident.reason = "escalated", str(error)
        self.store.put("incidents", incident.id, incident)
        self.store.audit(incident.id, "approval_outcome", {"status": incident.status})
        return incident
