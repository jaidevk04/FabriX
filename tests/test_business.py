import pytest
from fastapi.testclient import TestClient

from cognition.api import create_app
from cognition.domain import Industry, PlantSpec


def run(platform, ticks, plant="kiln"):
    for _ in range(ticks):
        platform.connector.tick(plant)
    return platform.business.read(plant)


def test_baseline_plant_produces_and_is_deterministic(platform):
    first = run(platform, 30)
    assert first["metrics"].production_rate_tph == pytest.approx(150, rel=0.05)
    assert first["ledger"].produced_t > 0 and first["ledger"].co2e_kg > 0
    assert first["metrics"].specific_energy_gj_per_t > 3
    assert len(first["ledger"].orders) == 3
    other = Industry.CEMENT
    platform.onboard(PlantSpec(id="twin", name="Twin", industry=other))
    assert [
        o.quantity_t for o in platform.business.ledger(platform.store.plant("twin")).orders
    ] != [o.quantity_t for o in first["ledger"].orders]


def test_faults_degrade_throughput_quality_energy_and_emissions(platform):
    healthy = run(platform, 5)["metrics"]
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    platform.faults.inject("kiln", "coating_ring", severity=1.0, ramp_ticks=0)
    hurt = run(platform, 3)["metrics"]
    assert hurt.production_rate_tph < healthy.production_rate_tph
    assert hurt.fuel_gj_per_h / max(hurt.production_rate_tph, 1) > healthy.fuel_gj_per_h / 150
    assert hurt.scrap_fraction >= healthy.scrap_fraction


def test_business_events_create_orders_once_and_shift_risk(platform):
    before = run(platform, 3)
    platform.faults.inject("kiln", "demand_surge", severity=1.0)
    platform.faults.inject("kiln", "rush_order", severity=1.0)
    after = run(platform, 5)
    sources = [o.source for o in after["ledger"].orders]
    assert sources.count("demand_surge") == 6 and sources.count("rush_order") == 1
    assert after["metrics"].open_orders > before["metrics"].open_orders
    assert after["metrics"].orders_at_risk >= 1
    again = run(platform, 5)
    assert [o.source for o in again["ledger"].orders].count("demand_surge") == 6


def test_tariff_peak_raises_cost_and_supplier_delay_starves_the_plant(platform):
    base = run(platform, 3)["metrics"]
    platform.faults.inject("kiln", "tariff_peak", severity=1.0, ramp_ticks=0)
    peak = run(platform, 3)["metrics"]
    assert peak.tariff_multiplier > base.tariff_multiplier
    assert peak.energy_cost_per_h > base.energy_cost_per_h
    platform.faults.inject("kiln", "supplier_delay")
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.raw_material_t = 0.5
    platform.store.put("business_state", "kiln", ledger)
    starved = run(platform, 5)
    assert starved["metrics"].production_rate_tph == 0
    assert starved["metrics"].availability == 0


def test_spare_shortage_hides_spares_and_reset_restarts_the_ledger(platform):
    assert platform.business.read("kiln")["spares_available"]["bearing_set"] == 2
    platform.faults.inject("kiln", "spare_shortage")
    assert set(run(platform, 1)["spares_available"].values()) == {0}
    platform.reset("kiln")
    fresh = platform.business.read("kiln")
    assert fresh["ledger"].produced_t == 0 and fresh["spares_available"]["bearing_set"] == 2


def test_every_industry_has_consistent_parameters():
    from cognition.industries import BUSINESS, catalogue

    for industry in Industry:
        params = BUSINESS[industry]
        remedies = {d.remedy for d in catalogue(industry).values() if d.domain == "fault"}
        assert remedies <= set(params.remedy_spare)
        assert {p for p in params.remedy_spare.values() if p} <= set(params.spares)


def test_business_api():
    with TestClient(create_app(":memory:")) as client:
        result = client.get("/api/plants/chemical-demo/business").json()
        assert result["metrics"]["nominal_rate_tph"] == 12
        assert "placeholder" in result["metrics"]["basis"]
        assert client.get("/api/plants/missing/business").status_code == 404
