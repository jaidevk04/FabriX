"""Read the numbers an optimization problem is built from."""

from cognition.agentkit.tools import tool
from cognition.cores.context import CoreContext
from cognition.domain import Control
from cognition.industries import PACKS


@tool("optimization", "read")
def optimization_read_problem_context(ctx: CoreContext) -> dict:
    """Read temperature, target, band, duty limits and the business numbers that matter.

    Use when you formulate a problem and need to know the starting point and limits. Do not
    use it to find the answer; call optimization_search_duty for candidates.

    Returns:
        State, band and envelope, control limits, production, energy, CO2e and orders at risk.
    """
    state = ctx.state
    pack = PACKS[state.spec.industry]
    limits = Control()
    metrics = ctx.platform.business.read(ctx.plant_id)["metrics"]
    return {
        "revision": state.revision,
        "temperature": round(state.temperature, 2),
        "target": state.target,
        "deviation": round(state.temperature - state.target, 2),
        "band": pack.band,
        "envelope": pack.envelope,
        "duty": state.duty,
        "limits": {"min": limits.minimum, "max": limits.maximum, "max_change": limits.max_change},
        "business": {
            "production_rate_tph": metrics.production_rate_tph,
            "fuel_gj_per_h": metrics.fuel_gj_per_h,
            "co2e_kg_per_h": metrics.co2e_kg_per_h,
            "orders_at_risk": metrics.orders_at_risk,
        },
        "basis": "Simulated twin and placeholder business factors.",
    }
