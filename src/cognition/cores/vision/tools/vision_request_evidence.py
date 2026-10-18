"""Ask a peer core for evidence through the core bus."""

from cognition.agentkit.tools import tool
from cognition.cores._shared.bus_tool import request_evidence
from cognition.cores.context import CoreContext


@tool("vision", "read")
def vision_request_evidence(
    ctx: CoreContext, to_core: str, kind: str, target: str, question: str
) -> dict:
    """Ask the learning or robot core for evidence about one piece of equipment.

    Use when a detection needs signal confirmation or fleet context. Do not use to order
    anything: bus requests carry evidence only.

    Args:
        to_core: "learning" or "robot".
        kind: "read_signal_evidence" for learning or "read_fleet_state" for robot.
        target: Equipment id such as "burner".
        question: One short question the answer should help with.
    Returns:
        The peer's evidence, or an error with a hint.
    """
    return request_evidence(ctx, to_core, kind, target, question)
