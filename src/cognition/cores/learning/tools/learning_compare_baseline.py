"""Compare one channel with its healthy simulated baseline."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext


@tool("learning", "read")
def learning_compare_baseline(ctx: CoreContext, channel: str) -> dict:
    """Compare a channel's current value with the healthy baseline of the simulated twin.

    Use when you want the size of a deviation in the channel's own unit. Do not use it to
    decide a diagnosis; combine it with other channels first.

    Args:
        channel: Channel id from learning_list_channels.
    Returns:
        Current value, baseline value, absolute and relative deviation, and status.
    """
    bus = ctx.platform.signals
    try:
        now = bus.read_one(ctx.plant_id, channel)
        base = bus.baseline(ctx.plant_id, channel)
    except KeyError:
        return tool_error(f"Unknown channel '{channel}'", "Call learning_list_channels first.")
    deviation = now.value - base.value
    return {
        "channel": channel,
        "unit": now.unit,
        "current": now.value,
        "baseline": base.value,
        "deviation": round(deviation, 4),
        "relative": round(deviation / base.value, 4) if base.value else None,
        "status": now.status,
    }
