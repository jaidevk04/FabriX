"""Compare a camera's current view with its healthy reference."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext


@tool("vision", "read")
def vision_compare_reference(ctx: CoreContext, camera: str) -> dict:
    """Compare what a camera shows now with its healthy reference view.

    Use when you need to know whether a camera deviates from normal at all. Do not use it to
    name the cause of a deviation.

    Args:
        camera: Camera id from vision_list_cameras.
    Returns:
        A deviation index from 0 to 1 and the labels that contribute to it.
    """
    try:
        found = ctx.platform.cameras.detections(ctx.plant_id, camera)
    except KeyError:
        return tool_error(f"Unknown camera '{camera}'", "Call vision_list_cameras first.")
    index = max((d.severity * d.confidence for d in found), default=0.0)
    return {
        "camera": camera,
        "deviation_index": round(index, 3),
        "labels": [d.label for d in found],
        "reference": "healthy simulated view (no active events)",
    }
