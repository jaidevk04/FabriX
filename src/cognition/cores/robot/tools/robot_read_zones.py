"""Read the plant zone graph."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext


@tool("robot", "read")
def robot_read_zones(ctx: CoreContext, zone: str = "") -> dict:
    """Read zones with their kind (dock, safe, process, hot), equipment and neighbours.

    Use when planning a route or checking whether equipment is in a hot zone. Do not use it
    for robot positions; call robot_read_fleet.

    Args:
        zone: Zone id to read. Empty means every zone.
    Returns:
        Zones with id, name, kind, equipment and next_to.
    """
    zones = ctx.platform.fleet.state(ctx.plant_id).zones
    chosen = [z for z in zones if not zone or z.id == zone]
    if not chosen:
        return tool_error(f"Unknown zone '{zone}'", f"Zones: {', '.join(z.id for z in zones)}.")
    return {"zones": [z.model_dump(mode="json") for z in chosen]}
