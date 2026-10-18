"""Apply the approved thermal-duty order (bound, no arguments)."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext


@tool("optimization", "action")
async def optimization_execute_order(ctx: CoreContext) -> dict:
    """Apply the thermal-duty change the platform approved, through the Gateway.

    Use when you are handed an order. The platform already re-sized it from the live state and the
    Gateway checks it again. Do not use more than once, and do not refuse only because the plant
    moved since the order was written; refuse when the Gateway rejects it.

    Returns:
        The receipt id and verification state, or the Gateway's reason for rejecting it.
    """
    if ctx.bound is None or ctx.order is None:
        return tool_error("No duty order is bound", "Report your decision.")
    if ctx.called:
        return tool_error("The order was already executed", "Report your decision.")
    ctx.called = True
    try:
        ctx.outcome = await ctx.bound()
    except Exception as error:
        ctx.error = error
        return tool_error(str(error), "The order was rejected. Report it as refused.")
    return {
        "status": "executed",
        "command": ctx.outcome.command_id,
        "verification": ctx.outcome.verification,
    }
