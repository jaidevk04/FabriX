"""Read the sensor language model's per-channel anomaly scores."""

from cognition.agentkit.tools import tool, truncate
from cognition.cores.context import CoreContext
from cognition.cores.learning.monitor import channel_scores


@tool("learning", "read")
def learning_read_encoder_scores(ctx: CoreContext, equipment: str = "", limit: int = 10) -> dict:
    """Read anomaly scores and tokens from the simulated sensor language model.

    Use when you want to rank which channels deviate most. Do not treat scores as calibrated
    probabilities: the model is simulated and untrained.

    Args:
        equipment: Equipment id to filter on. Empty means all equipment.
        limit: Maximum channels to return, highest score first.
    Returns:
        Channels with token, score and a one-line detail, highest first.
    """
    scores = [
        s
        for s in channel_scores(ctx.platform, ctx.plant_id)
        if not equipment or s["equipment"] == equipment
    ]
    scores.sort(key=lambda s: -s["score"])
    result = truncate(scores, limit, "Pass an equipment id to narrow the list.")
    result["model"] = "simulated-sensor-lm-v0 (trained_model: false)"
    return result
