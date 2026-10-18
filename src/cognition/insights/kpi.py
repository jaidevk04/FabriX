"""KPI and sustainability views derived from the simulated business metrics."""

from cognition.domain import BusinessMetrics, BusinessState

BASIS = "Simulated model with placeholder factors; not plant accounting."


def kpis(metrics: BusinessMetrics, ledger: BusinessState) -> dict:
    availability = metrics.availability
    capacity = metrics.nominal_rate_tph * availability
    performance = round(metrics.production_rate_tph / capacity, 3) if capacity > 0 else 0.0
    quality = round(1 - metrics.scrap_fraction, 3)
    return {
        "oee": round(availability * performance * quality, 3),
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "orders_at_risk": metrics.orders_at_risk,
        "open_orders": metrics.open_orders,
        "raw_cover_hours": metrics.raw_cover_hours,
        "produced_t": round(ledger.produced_t, 2),
        "scrap_t": round(ledger.scrap_t, 2),
        "revenue": round(ledger.revenue, 2),
        "penalty_cost": round(ledger.penalty_cost, 2),
        "basis": BASIS,
    }


def sustainability(metrics: BusinessMetrics, ledger: BusinessState) -> dict:
    return {
        "rates": {
            "fuel_gj_per_h": metrics.fuel_gj_per_h,
            "electricity_kw": metrics.electricity_kw,
            "co2e_kg_per_h": metrics.co2e_kg_per_h,
            "specific_energy_gj_per_t": metrics.specific_energy_gj_per_t,
            "energy_cost_per_h": metrics.energy_cost_per_h,
            "tariff_multiplier": metrics.tariff_multiplier,
        },
        "cumulative": {
            "fuel_gj": round(ledger.fuel_gj, 2),
            "electricity_kwh": round(ledger.electricity_kwh, 2),
            "co2e_kg": round(ledger.co2e_kg, 1),
            "energy_cost": round(ledger.energy_cost, 2),
            "scrap_t": round(ledger.scrap_t, 2),
        },
        "basis": "Emission factors and tariffs are placeholders, not authoritative values.",
    }


KPI_EVERY = 5  # ticks between stored samples
KEEP_TICKS = 2000


def make_sample(state, metrics: BusinessMetrics, ledger: BusinessState):
    from cognition.domain import KpiSample

    k = kpis(metrics, ledger)
    return KpiSample(
        plant_id=state.spec.id,
        tick=state.tick,
        sim_seconds=state.sim_seconds,
        oee=k["oee"],
        availability=k["availability"],
        performance=k["performance"],
        quality=k["quality"],
        production_rate_tph=metrics.production_rate_tph,
        good_rate_tph=metrics.good_rate_tph,
        energy_cost_per_h=metrics.energy_cost_per_h,
        co2e_kg_per_h=metrics.co2e_kg_per_h,
        orders_at_risk=metrics.orders_at_risk,
        deviation=round(state.temperature - state.target, 3),
    )


def sample_key(plant_id: str, tick: int) -> str:
    return f"{plant_id}:{tick:08d}"


def history(platform, plant_id: str, limit: int = 200) -> list:
    from cognition.domain import KpiSample

    low, high = f"{plant_id}:", f"{plant_id};"
    with platform.store.lock:
        rows = platform.store.db.execute(
            "SELECT body FROM kpi_samples WHERE id >= ? AND id < ? ORDER BY id DESC LIMIT ?",
            (low, high, max(1, min(limit, 1000))),
        ).fetchall()
    return [KpiSample.model_validate_json(row[0]) for row in reversed(rows)]


def incident_timings(platform, incident) -> dict:
    """Detect, escalate, act and recover times in simulated seconds, where the audit has them."""
    from cognition.domain import SECONDS_PER_TICK

    events = platform.store.events(incident.id)
    started = next((e["body"].get("tick") for e in events if e["kind"] == "started"), None)
    verified = next((e["body"].get("tick") for e in events if e["kind"] == "verified"), None)
    order = platform.orders.for_incident(incident.id)
    acted = order.baseline.get("tick") if order else None
    fault_tick = alert_tick = None
    if started is not None:
        faults = [
            e
            for e in platform.faults.events(incident.plant_id)
            if e.domain == "fault" and e.started_tick <= started
        ]
        if faults:
            fault_tick = min(e.started_tick for e in faults)
            ticks = [
                e["body"].get("tick")
                for e in platform.store.events(f"cores:{incident.plant_id}")
                if e["kind"] == "core_alert"
                and e["body"].get("tick") is not None
                and fault_tick <= e["body"]["tick"] <= started
            ]
            alert_tick = min(ticks) if ticks else None

    def seconds(later, earlier):
        if later is None or earlier is None:
            return None
        return round((later - earlier) * SECONDS_PER_TICK, 1)

    return {
        "time_to_detect_s": seconds(alert_tick, fault_tick),
        "time_to_escalate_s": seconds(started, alert_tick),
        "time_to_act_s": seconds(acted, started),
        "time_to_recover_s": seconds(verified, fault_tick if fault_tick is not None else started),
        "basis": "Simulated process time (10 s per tick) from the audit log.",
    }


def plant_kpis(platform, plant_id: str) -> dict:
    """Current KPIs, totals and incident performance for one plant."""
    from cognition.domain import SECONDS_PER_TICK  # noqa: F401

    data = platform.business.read(plant_id)
    metrics, ledger = data["metrics"], data["ledger"]
    base = kpis(metrics, ledger)
    incidents = [i for i in platform.store.incidents() if i.plant_id == plant_id]
    timings = [incident_timings(platform, i) for i in incidents]

    def mean(key: str):
        values = [t[key] for t in timings if t[key] is not None]
        return round(sum(values) / len(values), 1) if values else None

    done = [w for w in platform.workorders.all(plant_id) if w.status == "completed"]
    maintenance_cost = sum(w.est_cost for w in done)
    produced_good = max(ledger.produced_t - ledger.scrap_t, 1e-6)
    return base | {
        "tick": data["tick"],
        "downtime_hours": round(ledger.downtime_ticks / 360, 2),
        "energy_per_t_gj": round(ledger.fuel_gj / produced_good, 3),
        "co2e_kg": round(ledger.co2e_kg, 1),
        "simulated_cost": round(ledger.energy_cost + ledger.penalty_cost + maintenance_cost, 2),
        "maintenance_cost": round(maintenance_cost, 2),
        "incidents": {
            "total": len(incidents),
            "resolved": sum(i.status == "resolved" for i in incidents),
            "escalated": sum(i.status == "escalated" for i in incidents),
            "failed": sum(i.status == "failed" for i in incidents),
            "mean_time_to_detect_s": mean("time_to_detect_s"),
            "mean_time_to_escalate_s": mean("time_to_escalate_s"),
            "mean_time_to_recover_s": mean("time_to_recover_s"),
        },
    }
