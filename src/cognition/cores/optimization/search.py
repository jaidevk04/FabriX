"""Twin search for thermal duty candidates. Pure math; it never issues a command."""

from cognition.domain import Action, Control, State
from cognition.industries import PACKS
from cognition.simulation.thermal import check_action, simulate

GOALS = ("recovery", "energy", "scrap")


def search_duty(state: State, goal: str = "recovery", max_change: float = 20.0) -> list[dict]:
    """Grid-search duty values on a twin copy and rank them for the goal."""
    limits, envelope = Control(), PACKS[state.spec.industry].envelope
    candidates = []
    step = 2.0
    delta = -min(max_change, limits.max_change)
    while delta <= min(max_change, limits.max_change):
        value = state.duty + delta
        delta += step
        action = Action(value=value)
        try:
            check_action(state, action)
        except ValueError:
            continue
        result = simulate(state, action)
        candidates.append(
            {
                "value": round(value, 1),
                "recovered": result.recovered,
                "safe": result.safe,
                "final_error": round(result.final_error, 3),
                # Placeholder proxies: fuel follows actuator position, scrap follows residual error.
                "fuel_factor": round(1 + (value - 50) / 100 * 0.4, 3),
                "scrap_proxy": round(min(0.15, result.final_error / envelope * 0.2), 4),
            }
        )
    usable = [c for c in candidates if c["safe"]]
    keys = {
        "recovery": lambda c: (not c["recovered"], c["final_error"]),
        "energy": lambda c: (not c["recovered"], c["fuel_factor"], c["final_error"]),
        "scrap": lambda c: (not c["recovered"], c["scrap_proxy"], c["final_error"]),
    }
    return sorted(usable, key=keys[goal])[:5]
