"""List the sensor channels of one plant with their latest readings."""

from cognition.agentkit.tools import tool, truncate
from cognition.cores.context import CoreContext


@tool("learning", "read")
def learning_list_channels(ctx: CoreContext, equipment: str = "", limit: int = 20) -> dict:
    """List sensor channels and their latest values, optionally for one equipment item.

    Use when you need to know which channels exist or which ones look off. Do not use to
    get waveform detail; call learning_read_features for that.

    Args:
        equipment: Equipment id such as "drive" or "burner". Empty means all equipment.
        limit: Maximum channels to return.
    Returns:
        Channels with name, unit, value, nominal and status (normal, high or low).
    """
    readings = ctx.platform.signals.read_all(ctx.plant_id)
    rows = [
        {
            "channel": r.channel,
            "equipment": r.equipment,
            "unit": r.unit,
            "value": r.value,
            "nominal": r.nominal,
            "status": r.status,
            "modality": r.modality,
        }
        for r in readings
        if not equipment or r.equipment == equipment
    ]
    return truncate(rows, limit, "Pass an equipment id to narrow the list.")
