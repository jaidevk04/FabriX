"""Forecast one duty value on a twin copy."""

from cognition.agentkit.tools import tool, tool_error
from cognition.cores.context import CoreContext
from cognition.domain import Action
from cognition.simulation.thermal import simulate


@tool("optimization", "read")
def optimization_evaluate_candidate(ctx: CoreContext, value: float) -> dict:
    """Forecast one thermal-duty percentage on a twin copy and compare with doing nothing.

    Use when you must check an answer from the search or from reasoning. Do not use it to
    apply the value: it changes nothing.

    Args:
        value: Duty percent between 10 and 90, at most 20 away from the current duty.
    Returns:
        recovered, safe, final_error, and the baseline final_error without any change.
    """
    state = ctx.state
    try:
        forecast = simulate(state, Action(value=value))
    except ValueError as error:
        return tool_error(str(error), "Stay within 10 to 90 and 20 of the current duty.")
    baseline = simulate(state)
    return {
        "value": value,
        "recovered": forecast.recovered,
        "safe": forecast.safe,
        "final_error": round(forecast.final_error, 3),
        "baseline_final_error": round(baseline.final_error, 3),
        "improves": forecast.final_error < baseline.final_error,
    }
