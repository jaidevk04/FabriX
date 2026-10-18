"""Measure the size and extent of a detected defect."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext


@tool("vision", "read")
def vision_measure_defect(ctx: CoreContext, camera: str, label: str) -> dict:
    """Measure a detection's size as a share of the frame and rate its extent.

    Use when you need to say how large a defect or hotspot is. Do not use it to decide a
    cause; pair it with signal evidence from the learning core.

    Args:
        camera: Camera id from vision_list_cameras.
        label: Detection label such as "flame instability".
    Returns:
        Area share of the frame, severity and an extent rating (small, moderate, large).
    """
    try:
        found = ctx.platform.cameras.detections(ctx.plant_id, camera)
    except KeyError:
        return tool_error(f"Unknown camera '{camera}'", "Call vision_list_cameras first.")
    match = next((d for d in found if d.label == label), None)
    if match is None:
        labels = ", ".join(d.label for d in found) or "none"
        return tool_error(f"No '{label}' detection on {camera}", f"Current labels: {labels}.")
    area = round(match.box[2] * match.box[3], 4)
    extent = "large" if match.severity >= 0.7 else "moderate" if match.severity >= 0.4 else "small"
    return {
        "camera": camera,
        "label": label,
        "area_share": area,
        "severity": match.severity,
        "extent": extent,
        "basis": "Simulated detector on a placeholder frame.",
    }
