"""Pure metric formulas: production, quality, energy, CO2e and orders at risk."""

from cognition.domain import BusinessMetrics, BusinessState, State
from cognition.industries.base import BusinessParameters
from cognition.simulation.thermal import PACKS


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def metrics(
    state: State,
    effects: dict[str, dict[str, float]],
    params: BusinessParameters,
    ledger: BusinessState,
) -> BusinessMetrics:
    pack = PACKS[state.spec.industry]
    biz = effects.get("business", {})
    deviation = abs(state.temperature - state.target)
    if state.interlock:
        in_band = 0.0
    elif deviation <= pack.band:
        in_band = 1.0
    else:
        in_band = max(0.3, 1 - (deviation - pack.band) / pack.envelope)
    availability = clamp(1 + biz.get("availability", 0.0), 0.3, 1.0)
    if ledger.raw_material_t <= 0 or state.tick < ledger.downtime_until_tick:
        availability = 0.0
    throughput = clamp(1 + biz.get("throughput", 0.0), 0.2, 1.2)
    rate = params.nominal_rate_tph * availability * in_band * throughput
    scrap = clamp(biz.get("scrap", 0.0) + min(0.15, deviation / pack.envelope * 0.2), 0, 0.6)
    good = rate * (1 - scrap)
    fuel_factor = 1 + biz.get("fuel_use", 0.0) + biz.get("energy_use", 0.0)
    fuel_factor += (state.actuator - 50) / 100 * 0.4
    fuel = params.fuel_gj_per_t * rate * max(0.0, fuel_factor)
    kw = params.kwh_per_t * rate
    co2e = fuel * params.fuel_ef_kg_per_gj + rate * params.process_ef_kg_per_t
    co2e *= 1 + biz.get("emissions", 0.0)
    tariff = 1 + biz.get("tariff", 0.0)
    cost = fuel * params.fuel_cost_per_gj + kw * params.tariff_per_kwh * tariff
    burn = rate * params.raw_per_t
    cover = ledger.raw_material_t / burn if burn > 0 else float("inf")
    return BusinessMetrics(
        nominal_rate_tph=params.nominal_rate_tph,
        production_rate_tph=round(rate, 3),
        good_rate_tph=round(good, 3),
        availability=round(availability, 3),
        in_band_factor=round(in_band, 3),
        scrap_fraction=round(scrap, 4),
        fuel_gj_per_h=round(fuel, 3),
        electricity_kw=round(kw, 3),
        co2e_kg_per_h=round(co2e, 3),
        specific_energy_gj_per_t=round(fuel / good, 3) if good > 0 else 0.0,
        tariff_multiplier=round(tariff, 3),
        energy_cost_per_h=round(cost, 3),
        raw_cover_hours=round(min(cover, 9999.0), 2),
        orders_at_risk=at_risk(state, ledger, good),
        open_orders=sum(1 for order in ledger.orders if order.status != "fulfilled"),
    )


def at_risk(state: State, ledger: BusinessState, good_rate_tph: float) -> int:
    """Open orders (by due time) that the current good rate cannot finish in time."""
    backlog = -ledger.finished_goods_t
    count = 0
    for order in sorted(ledger.orders, key=lambda o: o.due_sim_seconds):
        if order.status == "fulfilled":
            continue
        backlog += order.quantity_t - order.filled_t
        hours_left = (order.due_sim_seconds - state.sim_seconds) / 3600
        needed = backlog / good_rate_tph if good_rate_tph > 0 else float("inf")
        if order.status == "late" or needed > max(hours_left, 0):
            count += 1
    return count
