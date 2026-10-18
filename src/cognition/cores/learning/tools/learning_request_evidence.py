"""Ask a peer core for evidence through the core bus."""

from cognition.agentkit.tools import tool
from cognition.cores._shared.bus_tool import request_evidence
from cognition.cores.context import CoreContext


@tool("learning", "read")
def learning_request_evidence(
    ctx: CoreContext, to_core: str, kind: str, target: str, question: str
) -> dict:
    """Ask the vision or robot core for evidence about one piece of equipment.

    Use when signals alone cannot settle a diagnosis and cameras or the fleet may help. Do not
    use to order anything: bus requests carry evidence only.

    Args:
        to_core: "vision" or "robot".
        kind: "read_detections" for vision or "read_fleet_state" for robot.
        target: Equipment id such as "burner".
        question: One short question the answer should help with.
    Returns:
        The peer's evidence, or an error with a hint.
    """
    return request_evidence(ctx, to_core, kind, target, question)
