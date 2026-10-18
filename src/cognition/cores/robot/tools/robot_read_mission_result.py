"""Read the result of an earlier mission."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext
from cognition.domain import Mission


@tool("robot", "read")
def robot_read_mission_result(ctx: CoreContext, mission_id: str) -> dict:
    """Read the stored result of a mission by id.

    Use when you need an earlier inspection result again. Do not use it to start work.

    Args:
        mission_id: Mission id returned by robot_run_mission, such as "mis-abc123".
    Returns:
        The mission with tool, target, steps and result.
    """
    try:
        mission = Mission.model_validate_json(ctx.platform.store.get("missions", mission_id))
    except (KeyError, ValueError):
        return tool_error(f"Unknown mission '{mission_id}'", "Use an id from robot_run_mission.")
    if mission.plant_id != ctx.plant_id:
        return tool_error("Mission belongs to another plant", "Use a mission from this plant.")
    return mission.model_dump(mode="json")
