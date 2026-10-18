"""Solve a small assignment or scheduling problem on the current evidence."""

from cognition.agentkit.tools import tool, tool_error
from cognition.control.fleet_gateway import FleetGateway
from cognition.cores.context import CoreContext
from cognition.cores.optimization.solvers import (
    assign_robots,
    assign_spares,
    diagnosed_repairs,
    plan_maintenance_window,
    robot_missions,
    spare_requests,
)

PROBLEMS = ("maintenance_window", "spares", "robots")


@tool("optimization", "read")
def optimization_solve_assignment(
    ctx: CoreContext, problem: str, equipment: str = "", horizon_hours: float = 6.0
) -> dict:
    """Solve a small exact problem: when to repair, who gets the spares, or which robot goes.

    Use when sensor-derived diagnoses exist and the trade-off is about time, parts or robots.
    Do not use it to apply anything: it plans on the twin and issues no command.

    Args:
        problem: maintenance_window, spares or robots.
        equipment: Comma-separated equipment ids to include. Empty means all diagnosed equipment.
        horizon_hours: Planning horizon for maintenance_window, 1 to 12 simulated hours.
    Returns:
        The repairs considered and the plan: window options with late orders and net value,
        spare assignments with what is left unserved, or robot assignments with battery cost.
    """
    if problem not in PROBLEMS:
        return tool_error(f"Unknown problem '{problem}'", f"Use one of: {', '.join(PROBLEMS)}.")
    state = ctx.state
    wanted = [e.strip() for e in equipment.split(",") if e.strip()]
    repairs = diagnosed_repairs(ctx.platform, ctx.plant_id, wanted)
    if not repairs:
        return tool_error(
            "No sensor-derived diagnosis to plan around",
            "Ask the learning core to analyse first, or name equipment that is alerting.",
        )
    if problem == "maintenance_window":
        horizon = min(max(horizon_hours, 1.0), 12.0)
        return plan_maintenance_window(ctx.platform, state, repairs, horizon)
    if problem == "spares":
        stock = ctx.platform.business.read(ctx.plant_id)["spares_available"]
        result = assign_spares(spare_requests(ctx.platform, state, repairs), stock)
        return result | {"stock": stock}
    missions, robots = robot_missions(ctx.platform, ctx.plant_id, repairs)
    fleet = ctx.platform.fleet.state(ctx.plant_id)

    def hops(a: str, b: str) -> int:
        return len(FleetGateway.route(fleet, a, b)) - 1

    return assign_robots(missions, robots, hops)
