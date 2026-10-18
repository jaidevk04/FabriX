"""Estimate the stage and remaining life of one equipment item (simulated prognosis)."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext
from cognition.cores.learning.monitor import (
    channel_scores,
    fuse,
    remaining_life_hours,
    stage_of,
)


@tool("learning", "read")
def learning_estimate_remaining_life(ctx: CoreContext, equipment: str) -> dict:
    """Estimate degradation stage and remaining life from the fused sensor score.

    Use when a diagnosis is likely and the main harness needs urgency. Do not quote the hours
    as a prediction of a real machine: the prognosis model is a simulated curve.

    Args:
        equipment: Equipment id such as "drive".
    Returns:
        Fused score, stage (early, developing, advanced) and simulated remaining hours.
    """
    fused = fuse(channel_scores(ctx.platform, ctx.plant_id))
    if equipment not in fused:
        return tool_error(
            f"No monitored channels for '{equipment}'", f"Known equipment: {', '.join(fused)}."
        )
    score = fused[equipment]["score"]
    return {
        "equipment": equipment,
        "score": score,
        "stage": stage_of(score),
        "remaining_life_hours": remaining_life_hours(score),
        "basis": "Simulated prognosis curve; not calibrated.",
    }
