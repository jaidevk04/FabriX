"""Carry out the approved repair order (bound, no arguments)."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext
from cognition.cores.executors import run_repair
from cognition.domain import MaintenanceAction


@tool("robot", "action")
async def robot_execute_order(ctx: CoreContext) -> dict:
    """Carry out the repair the platform approved: lock out, repair through the Gateway, unlock.

    Use when you have checked the fleet and zones and the order still looks safe. Do not use
    more than once, and refuse instead if anything looks wrong: the Gateway also re-checks.

    Returns:
        The receipt id and verification state, or the Gateway's reason for rejecting it.
    """
    proposal = ctx.proposal
    action = proposal.action if proposal else None
    if (
        proposal is None
        or ctx.bound is None
        or ctx.order is None
        or not isinstance(action, MaintenanceAction)
    ):
        return tool_error("No repair order is bound", "Report your decision.")
    if ctx.called:
        return tool_error("The order was already executed", "Report your decision.")
    ctx.called = True
    try:
        ctx.outcome = await run_repair(ctx.platform, ctx.order, proposal, action, ctx.bound)
    except Exception as error:
        ctx.error = error
        return tool_error(str(error), "The order was rejected. Report it as refused.")
    return {
        "status": "executed",
        "command": ctx.outcome.command_id,
        "verification": ctx.outcome.verification,
    }
