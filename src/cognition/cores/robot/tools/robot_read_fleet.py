"""Read the state of the robot fleet."""

from cognition.agentkit.tools import tool
from cognition.cores.context import CoreContext


@tool("robot", "read")
def robot_read_fleet(ctx: CoreContext) -> dict:
    """Read each robot's zone, battery, status and tools, plus active lock-outs.

    Use when you need to know which robot could do a job. Do not use it to start a mission;
    call robot_run_mission for that.

    Returns:
        Robots with name, kind, zone, battery, status and tools, and the locked-out equipment.
    """
    fleet = ctx.platform.fleet.state(ctx.plant_id)
    return {
        "robots": [
            {
                "name": r.name,
                "kind": r.kind,
                "zone": r.zone,
                "battery": r.battery,
                "status": r.status,
                "tools": r.tools,
            }
            for r in fleet.robots
        ],
        "lockouts": fleet.lockouts,
        "basis": fleet.basis,
    }
