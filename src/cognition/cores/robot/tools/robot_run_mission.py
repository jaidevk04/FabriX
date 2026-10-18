"""Run an automatic T0 or T1 mission through the fleet gateway."""

from cognition.agentkit.tools import tool, tool_error
from cognition.control.gateway import Rejected
from cognition.cores.context import CoreContext

ALLOWED = ("inspect", "verify", "sample", "patrol", "transport")


@tool("robot", "fleet")
def robot_run_mission(
    ctx: CoreContext, kind: str, target: str, tool_name: str = "", expect: str = ""
) -> dict:
    """Send a robot on an inspection, verification, sampling, patrol or transport mission.

    Use when evidence needs a physical look. Do not use for repairs or lock-outs: those run
    only through an approved maintenance order.

    Args:
        kind: inspect, verify, sample, patrol or transport.
        target: Equipment id such as "drive".
        tool_name: Robot tool such as "vibration_probe", "visual", "thermography".
        expect: For verify, the fault id you suspect, so the result says confirmed or not.
    Returns:
        Mission id, tier, steps and the inspection result, or the reason it was refused.
    """
    if kind not in ALLOWED:
        return tool_error(
            f"'{kind}' is not a T0 or T1 mission", f"Use one of: {', '.join(ALLOWED)}."
        )
    try:
        mission = ctx.platform.fleet_gateway.run(
            ctx.plant_id,
            kind,
            target,
            tool=tool_name,
            expect=expect,
            correlation=ctx.correlation_id,
        )
    except Rejected as error:
        return tool_error(str(error), "Use robot_check_mission to see what is allowed.")
    return {
        "mission": mission.id,
        "tier": mission.tier,
        "robot": mission.robot_id,
        "steps": mission.steps,
        "result": mission.result,
    }
