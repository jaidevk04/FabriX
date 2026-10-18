"""Action orders: hand an approved proposal to the owning core and track it end to end."""

import asyncio
from datetime import timedelta
from typing import Any

from cognition.control.gateway import Rejected
from cognition.cores.executors import executor_for
from cognition.cores.optimization.search import search_duty
from cognition.domain import (
    Action,
    ActionOrder,
    CoreName,
    MaintenanceAction,
    MonitorConfigAction,
    Proposal,
    Receipt,
    now,
)
from cognition.insights import impact
from cognition.mcp.control import execute_authorized
from cognition.simulation.thermal import PACKS

ORDER_WINDOW_SECONDS = 600
REPLAN_WINDOW_SECONDS = 60
# Gateway reasons that mean "the plan was right for an older plant state", not "never allowed".
STALE_REASONS = (
    "Plant state changed",
    "Proposal expired",
    "Simulation did not predict",
    "Action does not improve",
)


def owner_of(proposal: Proposal) -> CoreName:
    action = proposal.action
    if isinstance(action, MonitorConfigAction):
        return action.core
    return "robot" if action is not None and action.control == "maintenance" else "optimization"


class OrderService:
    def __init__(self, platform) -> None:
        self.platform = platform

    def save(self, order: ActionOrder) -> None:
        self.platform.store.put("action_orders", order.id, order)

    def all(self, plant_id: str | None = None) -> list[ActionOrder]:
        found = [
            ActionOrder.model_validate(v) for v in self.platform.store.records("action_orders")
        ]
        found = [o for o in found if plant_id is None or o.plant_id == plant_id]
        return sorted(found, key=lambda o: o.created_at)

    def get(self, order_id: str) -> ActionOrder:
        return ActionOrder.model_validate_json(self.platform.store.get("action_orders", order_id))

    def audit(self, order: ActionOrder, kind: str, body: dict | None = None) -> None:
        self.platform.store.audit(
            f"cores:{order.plant_id}",
            kind,
            {"correlation_id": order.incident_id, "order": order.id, "core": order.core}
            | (body or {}),
        )

    def _bound(self, proposal: Proposal, command_id: str, plant_id: str, live: bool, drift: int):
        action = proposal.action

        async def bound() -> Any:
            if isinstance(action, MonitorConfigAction):
                return self.platform.config_desk.apply(self.platform, plant_id, action)
            return await execute_authorized(
                self.platform.gateway, proposal, command_id, plant_id, live=live, max_drift=drift
            )

        return bound

    def replan(self, proposal: Proposal, plant_id: str, drift: int) -> Proposal | None:
        """Re-size a thermal-duty plan that went stale while the agents worked.

        Investigations take minutes while the live plant keeps moving, so a duty sized for the
        snapshot can no longer recover the plant by the time it is applied. If the Gateway would
        refuse the plan for that reason, search the twin again from the live state and return a
        fresh proposal with the same control and limits. The Gateway still validates and is the
        only writer. Returns None when the plan is fine as it is or no safe duty recovers.
        """
        if not isinstance(proposal.action, Action):
            return None
        gateway = self.platform.gateway
        try:
            gateway.validate(proposal, plant_id, max_drift=drift)
            return None
        except Rejected as error:
            if not str(error).startswith(STALE_REASONS):
                return None
        state = self.platform.connector.snapshot(plant_id)
        for candidate in search_duty(state, "recovery", 20):
            if not candidate["recovered"]:
                break
            fresh = Proposal(
                plant_id=plant_id,
                revision=state.revision,
                expires_at=now() + timedelta(seconds=REPLAN_WINDOW_SECONDS),
                summary=(
                    f"Re-planned from the live state (r{proposal.revision} to r{state.revision}): "
                    f"duty {proposal.action.value:g}% -> {candidate['value']:g}%. "
                    f"Original plan: {proposal.summary}"
                )[:2000],
                evidence=[
                    *proposal.evidence[:18],
                    f"twin search on the live state: duty {candidate['value']}, "
                    f"final error {candidate['final_error']}",
                ],
                action=Action(value=candidate["value"]),
            )
            try:
                gateway.validate(fresh, plant_id, max_drift=drift)
            except Rejected:
                continue
            return fresh
        return None

    async def execute(
        self,
        incident_id: str,
        proposal: Proposal,
        command_id: str,
        plant_id: str,
        *,
        live: bool,
        max_drift: int = 0,
    ) -> Receipt | Any:
        assert proposal.action is not None
        order = ActionOrder(
            incident_id=incident_id,
            plant_id=plant_id,
            core=owner_of(proposal),
            control=proposal.action.control,
            objective=proposal.summary[:300],
            expires_at=now() + timedelta(seconds=ORDER_WINDOW_SECONDS),
            baseline=impact.baseline(self.platform, plant_id, proposal),
        )
        self.save(order)
        if isinstance(proposal.action, MaintenanceAction):
            self.platform.workorders.start(order, proposal.action)
        self.audit(order, "order_created", {"control": order.control})
        if live:
            fresh = self.replan(proposal, plant_id, max_drift)
            if fresh is not None:
                order.replanned = fresh
                self.save(order)
                self.audit(
                    order,
                    "order_replanned",
                    {
                        "from": proposal.action.value,  # type: ignore[union-attr]
                        "to": fresh.action.value,  # type: ignore[union-attr]
                        "revisions_behind": fresh.revision - proposal.revision,
                    },
                )
                proposal = fresh
        return await self._run(order, proposal, command_id, live, max_drift)

    async def _run(
        self, order: ActionOrder, proposal: Proposal, command_id: str, live: bool, drift: int
    ) -> Any:
        bound = self._bound(proposal, command_id, order.plant_id, live, drift)
        try:
            executor = executor_for(order.core, self.platform, order.plant_id)
            outcome = await executor.run(self.platform, order, proposal, bound)
        except asyncio.CancelledError:
            order.status = "interrupted"
            self.save(order)
            self.audit(order, "order_interrupted")
            self._release(order, proposal, "interrupted")
            raise
        except Rejected as error:
            order.status, order.result = "refused", str(error)
            self.save(order)
            self.audit(order, "order_refused", {"reason": str(error)})
            self._release(order, proposal, str(error))
            raise
        except Exception as error:
            order.status, order.result = "failed", type(error).__name__
            self.save(order)
            self.audit(order, "order_failed", {"type": type(error).__name__})
            self._release(order, proposal, type(error).__name__)
            raise
        order.status = "completed"
        if isinstance(outcome, Receipt):
            order.command_ids.append(outcome.command_id)
            order.result = f"Command {outcome.command_id} committed."
            self.audit(order, "order_receipt", {"command": outcome.command_id})
        else:
            order.result = "Monitor configuration applied."
            self.audit(order, "order_receipt", {"config": True})
        self.save(order)
        if isinstance(proposal.action, MaintenanceAction) and isinstance(outcome, Receipt):
            self.platform.workorders.finish(order, proposal.action)
        return outcome

    def _release(self, order: ActionOrder, proposal: Proposal, reason: str) -> None:
        if isinstance(proposal.action, MaintenanceAction):
            self.platform.workorders.release(order, proposal.action, reason)

    # Follow-up corrections: separate Gateway-validated commands inside the order envelope.

    def for_incident(self, incident_id: str) -> ActionOrder | None:
        found = [o for o in self.all() if o.incident_id == incident_id]
        return found[-1] if found else None

    def propose_followup(self, order: ActionOrder) -> Proposal | None:
        state = self.platform.connector.snapshot(order.plant_id)
        if abs(state.temperature - state.target) <= PACKS[state.spec.industry].band:
            return None
        for candidate in search_duty(state, "recovery", 20):
            if candidate["recovered"] and abs(candidate["value"] - state.duty) >= 1:
                return Proposal(
                    plant_id=order.plant_id,
                    revision=state.revision,
                    expires_at=now() + timedelta(seconds=60),
                    summary="Follow-up correction: still out of band after the first command.",
                    evidence=[
                        f"twin search: duty {candidate['value']}, error {candidate['final_error']}"
                    ],
                    action=Action(value=candidate["value"]),
                )
        return None

    async def followup(self, incident_id: str, *, autonomous: bool) -> ActionOrder | None:
        order = self.for_incident(incident_id)
        if (
            order is None
            or order.control != "thermal_duty"
            or order.status != "completed"
            or order.pending_followup is not None
            or order.expires_at <= now()
        ):
            return None
        proposal = self.propose_followup(order)
        if proposal is None:
            return None
        if not autonomous:
            order.pending_followup = proposal
            self.save(order)
            self.audit(order, "followup_pending", {"value": proposal.action.value})  # type: ignore[union-attr]
            return order
        return await self._run_followup(order, proposal)

    async def _run_followup(self, order: ActionOrder, proposal: Proposal) -> ActionOrder:
        number = order.followups + 1
        command_id = f"{order.incident_id}:f{number}"
        try:
            await self._run(order, proposal, command_id, True, self.platform.live_drift)
        except Rejected as error:
            order.status, order.result = "completed", f"Follow-up {number} rejected: {error}"
            self.audit(order, "followup_rejected", {"reason": str(error)})
        else:
            order.followups = number
            self.audit(order, "followup_executed", {"command": command_id})
        order.status = "completed"
        order.pending_followup = None
        self.save(order)
        return order

    async def decide_followup(self, order_id: str, *, accepted: bool) -> ActionOrder:
        order = self.get(order_id)
        proposal = order.pending_followup
        if proposal is None:
            raise ValueError("No follow-up is waiting for approval")
        if not accepted:
            order.pending_followup = None
            self.save(order)
            self.audit(order, "followup_declined")
            return order
        return await self._run_followup(order, proposal)
