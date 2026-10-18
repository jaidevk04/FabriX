"""Read current detections for one camera or all of them."""

from cognition.agentkit.tools import tool, tool_error, truncate
from cognition.cores.context import CoreContext


@tool("vision", "read")
def vision_read_detections(ctx: CoreContext, camera: str = "", limit: int = 10) -> dict:
    """Read the simulated detector's current detections with confidence and severity.

    Use when a vision alert fired or you need to know what a camera sees. Do not use the
    confidence as a calibrated probability: the detector is simulated and untrained.

    Args:
        camera: Camera id from vision_list_cameras. Empty means every camera.
        limit: Maximum detections to return.
    Returns:
        Detections with camera, label, confidence, severity and a box in frame fractions.
    """
    bank = ctx.platform.cameras
    try:
        ids = [camera] if camera else [c.id for c in bank.definitions(ctx.plant_id)]
        found = [
            d.model_dump(mode="json") for cid in ids for d in bank.detections(ctx.plant_id, cid)
        ]
    except KeyError:
        return tool_error(f"Unknown camera '{camera}'", "Call vision_list_cameras first.")
    return truncate(found, limit, "Pass a camera id to narrow the list.")
