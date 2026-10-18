"""Order executors: the owning core carries out one approved order through its bound tool.

The reference executor is the offline stand-in for a core agent. It may refuse; it cannot
change the order's parameters and it has no way to write plant state.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from cognition.control.gateway import Rejected
from cognition.domain import ActionOrder, MaintenanceAction, Proposal

BoundTool = Callable[[], Awaitable[Any]]


class OrderRefused(Rejected):
    """The owning core declined the order. The incident ends escalated with this reason."""


class ReferenceExecutor:
    async def run(self, platform, order: ActionOrder, proposal: Proposal, bound: BoundTool) -> Any:
        action = proposal.action
        platform.store.audit(
            f"agent:{order.plant_id}:{order.core}",
            "reference_order",
            {"order": order.id, "control": order.control, "correlation_id": order.incident_id},
        )
        if isinstance(action, MaintenanceAction):
            return await run_repair(platform, order, proposal, action, bound)
        return await bound()


async def run_repair(
    platform, order: ActionOrder, proposal: Proposal, action: MaintenanceAction, bound: BoundTool
) -> Any:
    """The fixed repair procedure: check, lock out, Gateway repair, unlock. Not model-driven."""
    plant_id = order.plant_id
    # Check the static preconditions before any robot moves.
    platform.gateway.validate(proposal, plant_id, max_drift=platform.live_drift)
    fleet = platform.fleet_gateway
    fleet.run(plant_id, "lockout", action.equipment, correlation=order.id)
    try:
        return await bound()
    finally:
        try:
            fleet.run(plant_id, "unlock", action.equipment, correlation=order.id)
        except Rejected:
            pass  # nothing left to unlock


class AgentExecutor:
    """Hands the order to the owning core's ADK agent. No fallback after a failed run."""

    def __init__(self, agents) -> None:
        self.agents = agents

    async def run(self, platform, order: ActionOrder, proposal: Proposal, bound: BoundTool) -> Any:
        return await self.agents.execute_order(order, proposal, bound)


def executor_for(core: str, platform=None, plant_id: str = "") -> Any:
    """Agent when available; otherwise the reference executor, flagged as degraded."""
    agents = getattr(platform, "core_agents", None)
    if agents is not None and agents.enabled:
        ok, reason = agents.available()
        if ok:
            return AgentExecutor(agents)
        platform.store.audit(
            f"cores:{plant_id}", "core_degraded", {"core": core, "reason": reason[:200]}
        )
    return ReferenceExecutor()
