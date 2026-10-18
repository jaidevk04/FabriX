"""Chemical business parameters. Every number is a placeholder, not an authoritative factor."""

from cognition.industries.base import BusinessParameters

PARAMETERS = BusinessParameters(
    product="Batch product",
    nominal_rate_tph=12,
    raw_per_t=1.1,
    fuel_gj_per_t=2.2,
    kwh_per_t=180,
    fuel_ef_kg_per_gj=56,
    process_ef_kg_per_t=0,
    price_per_t=900,
    fuel_cost_per_gj=9,
    tariff_per_kwh=0.11,
    penalty_per_t=110,
    spares={"pump_seal": (2, 48), "gasket_set": (4, 24), "agitator_bearing": (1, 120)},
    repair_hours={
        "agitator_rebalance": 0.3,
        "jacket_flush": 0.5,
        "pipe_seal": 0.2,
        "pump_service": 0.4,
    },
    part_cost={"pump_seal": 900, "gasket_set": 150, "agitator_bearing": 2800},
    remedy_spare={
        "agitator_rebalance": None,
        "jacket_flush": None,
        "pipe_seal": "gasket_set",
        "pump_service": "pump_seal",
    },
)
