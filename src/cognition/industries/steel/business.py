"""Steel business parameters. Every number is a placeholder, not an authoritative factor."""

from cognition.industries.base import BusinessParameters

PARAMETERS = BusinessParameters(
    product="Reheated billets",
    nominal_rate_tph=120,
    raw_per_t=1.0,
    fuel_gj_per_t=1.4,
    kwh_per_t=25,
    fuel_ef_kg_per_gj=56,
    process_ef_kg_per_t=0,
    price_per_t=650,
    fuel_cost_per_gj=9,
    tariff_per_kwh=0.11,
    penalty_per_t=90,
    spares={"roller_bearing": (2, 96), "burner_nozzle": (2, 48), "roller_shaft": (1, 168)},
    repair_hours={
        "bearing_swap": 0.4,
        "burner_relight": 0.1,
        "billet_reject": 0.05,
        "roller_realign": 0.3,
    },
    part_cost={"roller_bearing": 3800, "burner_nozzle": 1200, "roller_shaft": 7000},
    remedy_spare={
        "bearing_swap": "roller_bearing",
        "burner_relight": None,
        "billet_reject": None,
        "roller_realign": None,
    },
)
