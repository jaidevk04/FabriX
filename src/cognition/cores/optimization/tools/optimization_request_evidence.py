"""Ask a peer core for evidence through the core bus."""

from cognition.agentkit.tools import tool
from cognition.cores._shared.bus_tool import request_evidence
from cognition.cores.context import CoreContext


@tool("optimization", "read")
def optimization_request_evidence(
    ctx: CoreContext, to_core: str, kind: str, target: str, question: str
) -> dict:
    """Ask the learning, vision or robot core for evidence relevant to an objective.

    Use when a trade-off depends on equipment condition or fleet availability. Do not use to
    order anything: bus requests carry evidence only.

    Args:
        to_core: "learning", "vision" or "robot".
        kind: read_signal_evidence, read_detections or read_fleet_state to match to_core.
        target: Equipment id such as "burner".
        question: One short question the answer should help with.
    Returns:
        The peer's evidence, or an error with a hint.
    """
    return request_evidence(ctx, to_core, kind, target, question)
