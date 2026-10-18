"""Business events shared by every industry; injected through the same API as faults."""

from cognition.industries.base import FaultDef


def _event(key: str, name: str, description: str, effect: dict[str, float], ramp: int = 0):
    return FaultDef(
        key, name, "plant", description, 0.0, {"business": effect}, "none", ramp, "business"
    )


BUSINESS_EVENTS = {
    "demand_surge": _event(
        "demand_surge",
        "Demand surge",
        "Extra customer orders arrive; severity sets how many.",
        {"demand": 1.0},
    ),
    "rush_order": _event(
        "rush_order",
        "Rush order",
        "One large high-priority order with a short due time.",
        {"rush": 1.0},
    ),
    "supplier_delay": _event(
        "supplier_delay",
        "Supplier delay",
        "Raw material deliveries stop while this is active.",
        {"supply": -1.0},
    ),
    "spare_shortage": _event(
        "spare_shortage",
        "Spare-part shortage",
        "Spares are unavailable while this is active; repairs needing a part cannot run.",
        {"spares": -1.0},
    ),
    "tariff_peak": _event(
        "tariff_peak",
        "Tariff peak",
        "Electricity price rises; severity scales the multiplier.",
        {"tariff": 1.2},
        ramp=5,
    ),
}
