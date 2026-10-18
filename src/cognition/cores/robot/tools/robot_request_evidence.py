"""Ask a peer core for evidence through the core bus."""

from cognition.agentkit.tools import tool
from cognition.cores._shared.bus_tool import request_evidence
from cognition.cores.context import CoreContext


@tool("robot", "read")
def robot_request_evidence(
    ctx: CoreContext, to_core: str, kind: str, target: str, question: str
) -> dict:
    """Ask the learning or vision core for evidence about one piece of equipment.

    Use when you need signal or camera evidence before choosing what to inspect. Do not use
    to order anything: bus requests carry evidence only.

    Args:
        to_core: "learning" or "vision".
        kind: "read_signal_evidence" for learning or "read_detections" for vision.
        target: Equipment id such as "drive".
        question: One short question the answer should help with.
    Returns:
        The peer's evidence, or an error with a hint.
    """
    return request_evidence(ctx, to_core, kind, target, question)
