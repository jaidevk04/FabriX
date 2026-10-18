"""Apply the approved monitor configuration order (bound, no arguments)."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext


@tool("learning", "action")
async def learning_apply_monitor_config(ctx: CoreContext) -> dict:
    """Apply the monitor configuration change that the platform approved for this order.

    Use when you have reviewed the order and it is consistent with current evidence. Do not use
    more than once, and do not use if you think the order is unsafe: refuse instead.

    Returns:
        The resulting masks and sensitivity, or an error if the order was already applied.
    """
    if ctx.bound is None or ctx.called:
        return tool_error("No order to apply, or it was already applied", "Report your decision.")
    ctx.called = True
    try:
        ctx.outcome = await ctx.bound()
    except Exception as error:
        ctx.error = error
        return tool_error(str(error), "The order was rejected. Report it as refused.")
    return {"status": "applied", "config": ctx.outcome.model_dump(mode="json")}
