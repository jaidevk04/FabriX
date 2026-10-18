"""Offline analyser for the optimization core: duty options plus window and spare plans."""

from cognition.cores.base import build_report
from cognition.cores.optimization.monitor import MODEL
from cognition.cores.optimization.objectives import optimize
from cognition.cores.optimization.solvers import (
    assign_spares,
    diagnosed_repairs,
    plan_maintenance_window,
    spare_requests,
)


def reference(platform, plant_id: str):
    state = platform.store.plant(plant_id)
    assessment: dict = {}
    parts = []
    duty = optimize(platform, state, "balanced")
    if duty["best"] is not None and duty["best"]["executable"]:
        best = duty["best"]
        parts.append(f"Best balanced duty {best['value']} (final error {best['final_error']}).")
        assessment["duty"] = {"best": best, "tradeoffs": duty["tradeoffs"]}
    repairs = diagnosed_repairs(platform, plant_id, [])
    if repairs:
        plan = plan_maintenance_window(platform, state, repairs)
        stock = platform.business.read(plant_id)["spares_available"]
        spares = assign_spares(spare_requests(platform, state, repairs), stock)
        assessment["maintenance"] = {"best": plan["best"], "plans": plan["plans"]}
        assessment["spares"] = {
            "served": [s["id"] for s in spares["served"]],
            "unserved": [s["id"] for s in spares["unserved"]],
        }
        parts.append(
            f"Repair window: {plan['best']}. {len(spares['unserved'])} repair(s) lack spares."
        )
    summary = " ".join(parts) or "Idle. Plant is in band and no repairs are indicated."
    return build_report(
        state, "optimization", [], summary, assessment, source="reference", model=MODEL
    )
