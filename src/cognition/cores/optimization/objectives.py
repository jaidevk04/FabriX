"""Duty candidates scored on recovery, energy, CO2e, scrap and due dates. Never issues commands."""

from collections.abc import Callable

from cognition.business.metrics import metrics
from cognition.business.model import parameters
from cognition.domain import Action, Control, State
from cognition.industries import PACKS
from cognition.simulation.faults import active_effects
from cognition.simulation.thermal import advance, check_action, simulate

GOALS = ("recovery", "energy", "co2e", "scrap", "due_date", "balanced")
BALANCED_WEIGHTS = {"recovery": 0.3, "energy": 0.2, "co2e": 0.15, "scrap": 0.15, "due_date": 0.2}
NOT_EXECUTABLE = 1000.0  # candidates the Gateway would reject sort after every executable one


def golden_section(
    f: Callable[[float], float], low: float, high: float, tol: float = 0.25
) -> float:
    """Minimise a one-dimensional function that is unimodal on [low, high]."""
    ratio = (5**0.5 - 1) / 2
    a, b = low, high
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    while abs(b - a) > tol:
        if f(c) < f(d):
            b = d
        else:
            a = c
        c, d = b - ratio * (b - a), a + ratio * (b - a)
    return round((a + b) / 2, 1)


def recovery_ticks(trajectory: list[float], target: float, band: float) -> int | None:
    """First tick after which the trajectory stays inside the band, or None."""
    inside = [abs(t - target) <= band for t in trajectory]
    for index in range(len(inside)):
        if all(inside[index:]):
            return index
    return None


def predict(platform, state: State, value: float) -> dict:
    """Forecast one duty on a twin copy, with the business effects of the resulting state."""
    forecast = simulate(state, Action(value=value))
    shadow = state.model_copy(deep=True)
    shadow.duty = value
    final, trajectory = advance(shadow)
    pack = PACKS[state.spec.industry]
    events = platform.faults.events(state.spec.id)
    effects = active_effects(events, state.spec.industry, state.tick)
    ledger = platform.business.ledger(state)
    outcome = metrics(final, effects, parameters(state), ledger)
    ticks = recovery_ticks(trajectory, state.target, pack.band)
    baseline = simulate(state)
    return {
        "value": round(value, 1),
        "recovered": forecast.recovered,
        "safe": forecast.safe,
        "improves": forecast.final_error < baseline.final_error,
        "final_error": round(forecast.final_error, 3),
        "recovery_ticks": ticks,
        "fuel_gj_per_h": outcome.fuel_gj_per_h,
        "co2e_kg_per_h": outcome.co2e_kg_per_h,
        "energy_cost_per_h": outcome.energy_cost_per_h,
        "scrap_fraction": outcome.scrap_fraction,
        "good_rate_tph": outcome.good_rate_tph,
        "orders_at_risk": outcome.orders_at_risk,
    }


def score(candidate: dict, goal: str, reference: dict, weights: dict[str, float] | None = None):
    """Lower is better. Normalised against the no-change reference so goals can be blended."""
    penalty = (
        0.0
        if candidate["recovered"] and candidate["safe"] and candidate["improves"]
        else NOT_EXECUTABLE
    )
    ticks = candidate["recovery_ticks"]
    terms = {
        "recovery": (ticks if ticks is not None else 60) / 60 + candidate["final_error"] * 0.001,
        "energy": candidate["energy_cost_per_h"] / max(reference["energy_cost_per_h"], 1e-6),
        "co2e": candidate["co2e_kg_per_h"] / max(reference["co2e_kg_per_h"], 1e-6),
        "scrap": candidate["scrap_fraction"] / max(reference["scrap_fraction"], 0.01),
        "due_date": candidate["orders_at_risk"]
        + 1 / (1 + candidate["good_rate_tph"] / max(reference["good_rate_tph"], 1e-6)),
    }
    if goal == "balanced":
        chosen = weights or BALANCED_WEIGHTS
        total = sum(chosen.values()) or 1.0
        return penalty + sum(chosen.get(k, 0.0) * v for k, v in terms.items()) / total
    return penalty + terms[goal]


def tradeoffs(ranked: list[dict]) -> list[dict]:
    """Say, in plain numbers, what each runner-up gives up against the best candidate."""
    if not ranked:
        return []
    best, notes = ranked[0], []
    for other in ranked[1:3]:
        deltas = {
            "recovery_ticks": _diff(other["recovery_ticks"], best["recovery_ticks"]),
            "fuel_gj_per_h": round(other["fuel_gj_per_h"] - best["fuel_gj_per_h"], 3),
            "co2e_kg_per_h": round(other["co2e_kg_per_h"] - best["co2e_kg_per_h"], 1),
            "scrap_fraction": round(other["scrap_fraction"] - best["scrap_fraction"], 4),
            "good_rate_tph": round(other["good_rate_tph"] - best["good_rate_tph"], 2),
        }
        notes.append(
            {
                "value": other["value"],
                "versus": best["value"],
                "deltas": deltas,
                "summary": (
                    f"Duty {other['value']} versus {best['value']}: "
                    f"{deltas['fuel_gj_per_h']:+.2f} GJ/h fuel, "
                    f"{deltas['co2e_kg_per_h']:+.0f} kg/h CO2e, "
                    f"{deltas['scrap_fraction']:+.3f} scrap, "
                    f"{deltas['good_rate_tph']:+.1f} t/h good output."
                ),
            }
        )
    return notes


def _diff(a: int | None, b: int | None) -> int | None:
    return None if a is None or b is None else a - b


def optimize(
    platform,
    state: State,
    goal: str = "recovery",
    max_change: float = 20.0,
    weights: dict[str, float] | None = None,
) -> dict:
    """Grid search, then golden-section refinement around the best cell. Forecasts only."""
    limits = Control()
    span = min(max(max_change, 0.0), limits.max_change)
    reference = predict(platform, state, state.duty)
    candidates: dict[float, dict] = {}

    def evaluate(value: float) -> dict | None:
        value = round(value, 1)
        if abs(value - state.duty) > span + 1e-9:
            return None
        if value in candidates:
            return candidates[value]
        try:
            check_action(state, Action(value=value))
        except ValueError:
            return None
        candidates[value] = predict(platform, state, value)
        return candidates[value]

    value = state.duty - span
    while value <= state.duty + span + 1e-9:
        evaluate(value)
        value += 2.0

    def cost(x: float) -> float:
        found = evaluate(x)
        return score(found, goal, reference, weights) if found else 1e9

    ranked = sorted(candidates.values(), key=lambda c: score(c, goal, reference, weights))
    if ranked:
        centre = ranked[0]["value"]
        low, high = max(centre - 2.0, limits.minimum), min(centre + 2.0, limits.maximum)
        golden_section(cost, low, high)
    ranked = sorted(candidates.values(), key=lambda c: score(c, goal, reference, weights))
    top = [
        c | {"score": round(score(c, goal, reference, weights), 4), "executable": _executable(c)}
        for c in ranked[:5]
        if c["safe"]
    ]
    return {
        "goal": goal,
        "reference": reference,
        "candidates": top,
        "best": top[0] if top else None,
        "tradeoffs": tradeoffs(top),
        "basis": "Twin search with the simulated business model; placeholder factors. "
        "Forecasts only: the Gateway validates any action.",
    }


def _executable(candidate: dict) -> bool:
    return bool(candidate["recovered"] and candidate["safe"] and candidate["improves"])
