"""List the cameras of one plant."""

from cognition.agentkit.tools import tool
from cognition.cores.context import CoreContext


@tool("vision", "read")
def vision_list_cameras(ctx: CoreContext) -> dict:
    """List cameras with the equipment and zone each one watches.

    Use when you need to know which cameras exist before reading detections. Do not use it
    to see defects; call vision_read_detections.

    Returns:
        Cameras with id, name, equipment, zone and the labels the detector can report.
    """
    cameras = ctx.platform.cameras.definitions(ctx.plant_id)
    return {
        "cameras": [
            {
                "camera": c.id,
                "name": c.name,
                "equipment": c.equipment,
                "zone": c.zone,
                "labels": sorted(c.detects.values()),
            }
            for c in cameras
        ],
        "source": "generated placeholder frames with a simulated detector",
    }
