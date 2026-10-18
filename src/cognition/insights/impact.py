"""Impact ledger: what an action achieved against the twin's no-action forecast."""

from cognition.business.model import HOURS_PER_TICK, parameters
from cognition.domain import ActionOrder, ImpactRecord, Incident, MaintenanceAction, Proposal
from cognition.industries import PACKS
from cognition.simulation.thermal import simulate

TERMINAL = ("resolved", "escalated", "failed", "interrupted")
TOTALS = ("produced_t", "scrap_t", "fuel_gj", "co2e_kg", "energy_cost", "penalty_cost")


def totals(ledger) -> dict:
    return {key: getattr(ledger, key) for key in TOTALS} | {"downtime_ticks": ledger.downtime_ticks}


def baseline(platform, plant_id: str, proposal: Proposal | None = None) -> dict:
    """Snapshot taken just before an order runs: state, rates, totals and the no-action forecast."""
    state = platform.store.plant(plant_id)
    data = platform.business.read(plant_id)
    metrics, ledger = data["metrics"], data["ledger"]
    forecast = simulate(state)
    band = PACKS[state.spec.industry].band
    out = sum(abs(t - state.target) > band for t in forecast.trajectory)
    result = {
        "tick": state.tick,
        "ledger_tick": ledger.last_tick,
        "deviation": round(state.temperature - state.target, 2),
        "no_action_recovers": forecast.recovered,
        "no_action_out_of_band_ticks": out,
        "no_action_final_error": round(forecast.final_error, 3),
        "rates": {
            "good_tph": metrics.good_rate_tph,
            "produced_tph": metrics.production_rate_tph,
            "scrap_tph": round(metrics.production_rate_tph * metrics.scrap_fraction, 4),
            "fuel_gj_per_h": metrics.fuel_gj_per_h,
            "co2e_kg_per_h": metrics.co2e_kg_per_h,
            "energy_cost_per_h": metrics.energy_cost_per_h,
        },
        "orders_at_risk": metrics.orders_at_risk,
        "totals": totals(ledger),
    }
    action = proposal.action if proposal else None
    if isinstance(action, MaintenanceAction):
        from cognition.cores.optimization.solvers import diagnosed_repairs, plan_maintenance_window

        repairs = diagnosed_repairs(platform, plant_id, [action.equipment])
        if repairs:
            plan = plan_maintenance_window(platform, state, repairs)
            by = {p["plan"]: p for p in plan["plans"]}
            result["projection"] = {
                "horizon_hours": 6.0,
                "repair_now_net": by["repair_now"]["net_value"],
                "no_repair_net": by["no_repair"]["net_value"],
                "advantage": round(by["repair_now"]["net_value"] - by["no_repair"]["net_value"], 1),
                "breakdown_avoided_hours": by["no_repair"]["breakdown_at_hours"],
            }
    return result


def close(platform, incident: Incident) -> ImpactRecord | None:
    """Write the impact record once an incident with an order reaches a final status."""
    if incident.status not in TERMINAL:
        return None
    order: ActionOrder | None = platform.orders.for_incident(incident.id)
    if order is None or not order.baseline:
        return None
    try:
        platform.store.get("impact_ledger", incident.id)
        return None
    except KeyError:
        pass
    state = platform.store.plant(incident.plant_id)
    data = platform.business.read(incident.plant_id)
    ledger, base = data["ledger"], order.baseline
    params = parameters(state)
    elapsed = max(0, state.tick - base["tick"])
    hours = elapsed * HOURS_PER_TICK
    band = PACKS[state.spec.industry].band
    actual_out = sum(abs(t - state.target) > band for t in incident.trajectory)
    expected_out = (
        elapsed if not base["no_action_recovers"] else base["no_action_out_of_band_ticks"]
    )
    deltas: dict = {
        "excursion_ticks_avoided": expected_out - actual_out
        if order.control == "thermal_duty"
        else None,
        "orders_at_risk": data["metrics"].orders_at_risk - base["orders_at_risk"],
    }
    actual: dict = {"out_of_band_ticks": actual_out, "elapsed_ticks": elapsed}
    start, rates = base["totals"], base["rates"]
    moved = any(getattr(ledger, k) != start[k] for k in TOTALS)
    if moved or ledger.downtime_ticks != start["downtime_ticks"]:
        spent = {k: getattr(ledger, k) - start[k] for k in TOTALS}
        expected = {
            "produced_t": rates["produced_tph"] * hours,
            "scrap_t": rates["scrap_tph"] * hours,
            "fuel_gj": rates["fuel_gj_per_h"] * hours,
            "co2e_kg": rates["co2e_kg_per_h"] * hours,
            "energy_cost": rates["energy_cost_per_h"] * hours,
        }
        actual |= {k: round(v, 3) for k, v in spent.items()}
        for key, value in expected.items():
            deltas[key] = round(spent[key] - value, 3)
        good = (spent["produced_t"] - spent["scrap_t"]) - (
            expected["produced_t"] - expected["scrap_t"]
        )
        deltas["value"] = round(good * params.price_per_t - deltas["energy_cost"], 2)
        deltas["downtime_hours"] = round((ledger.downtime_ticks - start["downtime_ticks"]) / 360, 2)
    else:
        deltas["note"] = "No live business samples between action and close (manual run)."
    record = ImpactRecord(
        id=incident.id,
        plant_id=incident.plant_id,
        control=order.control,
        outcome=incident.status,  # type: ignore[arg-type]
        started_tick=base["tick"],
        ended_tick=state.tick,
        elapsed_ticks=elapsed,
        baseline={k: v for k, v in base.items() if k not in ("totals", "projection")},
        actual=actual,
        deltas=deltas,
        projected=base.get("projection"),
    )
    platform.store.put("impact_ledger", incident.id, record)
    platform.store.audit(
        f"cores:{incident.plant_id}",
        "impact_recorded",
        {"correlation_id": incident.id, "outcome": record.outcome},
    )
    return record


def records(platform, plant_id: str) -> list[ImpactRecord]:
    found = [
        ImpactRecord.model_validate(v)
        for v in platform.store.records("impact_ledger")
        if v["plant_id"] == plant_id
    ]
    return sorted(found, key=lambda r: r.created_at)


def summary(platform, plant_id: str) -> dict:
    rows = records(platform, plant_id)
    resolved = [r for r in rows if r.outcome == "resolved"]
    return {
        "records": len(rows),
        "resolved": len(resolved),
        "value": round(sum(r.deltas.get("value") or 0 for r in resolved), 2),
        "projected_advantage": round(
            sum((r.projected or {}).get("advantage", 0) for r in resolved), 1
        ),
        "excursion_ticks_avoided": sum(
            r.deltas.get("excursion_ticks_avoided") or 0 for r in resolved
        ),
        "co2e_kg_delta": round(sum(r.deltas.get("co2e_kg") or 0 for r in resolved), 1),
        "basis": "Against the twin's no-action forecast; simulated, placeholder prices.",
    }
