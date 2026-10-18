"""Optimization core monitor: it has no always-on watch; it runs when asked."""

from cognition.cores.base import build_report

MODEL = "optimization-idle"


def monitor(platform, plant_id: str):
    state = platform.store.plant(plant_id)
    return build_report(
        state,
        "optimization",
        [],
        "Idle. Runs when the main harness requests an optimization.",
        {"objectives": []},
        model=MODEL,
    )
