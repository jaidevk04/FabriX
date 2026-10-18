"""Search the twin for thermal-duty candidates."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext
from cognition.cores.optimization.objectives import GOALS, optimize


@tool("optimization", "read")
def optimization_search_duty(
    ctx: CoreContext, goal: str = "recovery", max_duty_change: float = 20.0
) -> dict:
    """Rank safe thermal-duty values on a twin copy for a goal, with trade-offs.

    Use when the main harness asks for options to recover, save energy or CO2e, cut scrap, meet
    due dates, or balance them. Do not use it to apply anything: it issues no command and the
    Gateway still validates.

    Args:
        goal: recovery, energy, co2e, scrap, due_date or balanced.
        max_duty_change: Largest change from the current duty to consider, up to 20.
    Returns:
        Up to five candidates with recovery ticks, final error, fuel, CO2e, scrap, good output
        and orders at risk, the best one, and what each runner-up gives up.
    """
    if goal not in GOALS:
        return tool_error(f"Unknown goal '{goal}'", f"Use one of: {', '.join(GOALS)}.")
    return optimize(ctx.platform, ctx.state, goal, max(0.0, max_duty_change))
