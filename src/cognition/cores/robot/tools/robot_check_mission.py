"""Dry-run a mission against the fleet gateway rules."""

from cognition.agentkit.tools import tool
from cognition.cores.context import CoreContext


@tool("robot", "read")
def robot_check_mission(ctx: CoreContext, kind: str, target: str, tool_name: str = "") -> dict:
    """Check whether a mission would be allowed, without running it.

    Use when you want to know if a robot can reach and inspect some equipment. Do not use it
    as a substitute for robot_run_mission: nothing is moved or recorded.

    Args:
        kind: inspect, verify, sample, patrol or transport.
        target: Equipment id such as "drive".
        tool_name: Robot tool such as "vibration_probe" or "thermography".
    Returns:
        allowed, and the robot, route and battery cost, or the reason it would be refused.
    """
    return ctx.platform.fleet_gateway.check(ctx.plant_id, kind, target, tool_name)
