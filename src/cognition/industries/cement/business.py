"""Cement business parameters. Every number is a placeholder, not an authoritative factor."""

from cognition.industries.base import BusinessParameters

PARAMETERS = BusinessParameters(
    product="Clinker",
    nominal_rate_tph=150,
    raw_per_t=1.55,
    fuel_gj_per_t=3.4,
    kwh_per_t=110,
    fuel_ef_kg_per_gj=95,
    process_ef_kg_per_t=525,
    price_per_t=80,
    fuel_cost_per_gj=4,
    tariff_per_kwh=0.11,
    penalty_per_t=18,
    spares={"bearing_set": (2, 72), "refractory_kit": (1, 120), "burner_tip": (2, 48)},
    repair_hours={"bearing_swap": 0.4, "burner_retune": 0.1, "ring_clearing": 0.5},
    part_cost={"bearing_set": 4200, "refractory_kit": 9000, "burner_tip": 1500},
    remedy_spare={
        "bearing_swap": "bearing_set",
        "burner_retune": None,
        "ring_clearing": None,
    },
)
