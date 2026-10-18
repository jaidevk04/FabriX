"""Read the follow-up state of an order."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext


@tool("optimization", "read")
def optimization_read_followup_status(ctx: CoreContext, incident_id: str) -> dict:
    """Read how many follow-up corrections an order has had and whether one is pending.

    Use when deciding whether another correction is justified. Do not use it to start one:
    follow-ups run only through the platform.

    Args:
        incident_id: Incident id that owns the order.
    Returns:
        Order status, follow-up count, pending approval and the envelope end time.
    """
    order = ctx.platform.orders.for_incident(incident_id)
    if order is None or order.plant_id != ctx.plant_id:
        return tool_error(f"No order for incident '{incident_id}'", "Check the incident id.")
    return {
        "order": order.id,
        "status": order.status,
        "followups": order.followups,
        "pending_followup": order.pending_followup is not None,
        "commands": order.command_ids,
        "envelope_ends": order.expires_at.isoformat(),
    }
