"""Recommendations ranked by expected value and urgency. Advisory: nothing here acts."""

from cognition.business.model import parameters
from cognition.cores.optimization.objectives import optimize
from cognition.cores.optimization.solvers import (
    _fault_rate_loss,
    assign_spares,
    diagnosed_repairs,
    plan_maintenance_window,
    spare_requests,
)
from cognition.domain import Recommendation
from cognition.industries import catalogue

HORIZON_HOURS = 8.0


def _scored(items: list[Recommendation]) -> list[Recommendation]:
    top = max((abs(i.expected_value) for i in items), default=1.0) or 1.0
    for item in items:
        item.score = round(
            min(1.0, 0.6 * item.urgency + 0.4 * min(1.0, abs(item.expected_value) / top)), 3
        )
    return sorted(items, key=lambda i: -i.score)


def recommendations(platform, plant_id: str) -> list[Recommendation]:
    state = platform.store.plant(plant_id)
    data = platform.business.read(plant_id)
    metrics, ledger = data["metrics"], data["ledger"]
    params, known = parameters(state), catalogue(state.spec.industry)
    stock = data["spares_available"]
    repairs = diagnosed_repairs(platform, plant_id, [], min_match=0.6)
    items: list[Recommendation] = []
    plan = plan_maintenance_window(platform, state, repairs) if repairs else None
    unserved = (
        {
            s["id"]
            for s in assign_spares(spare_requests(platform, state, repairs), stock)["unserved"]
        }
        if repairs
        else set()
    )
    for repair in repairs:
        definition = known.get(repair["fault"])
        loss = (
            _fault_rate_loss(state, params, ledger, definition, repair["severity"])
            if definition
            else 0.0
        )
        hours = params.repair_hours.get(repair["remedy"], 0.0)
        part = params.remedy_spare.get(repair["remedy"])
        cost = params.part_cost.get(part or "", 0.0)
        life = repair["life_hours"]
        price, rate = params.price_per_t, metrics.nominal_rate_tph
        restored = loss * price * (HORIZON_HOURS - hours)
        # A repair done in time also avoids the simulated breakdown that would stop the plant.
        breakdown = rate * price * (HORIZON_HOURS - life) if life < HORIZON_HOURS else 0.0
        value = restored + breakdown - rate * price * hours - cost
        blocked = ""
        if repair["equipment"] in unserved and part:
            blocked = f"Spare '{part}' is not in stock (lead time {params.spares[part][1]:.0f} h)."
        items.append(
            Recommendation(
                id=f"{plant_id}:repair:{repair['equipment']}",
                plant_id=plant_id,
                kind="repair",
                title=f"Repair {repair['equipment']} ({repair['remedy'].replace('_', ' ')})",
                rationale=(
                    f"Sensor evidence matches {repair['fault']}. Simulated remaining life "
                    f"{life:.0f} h; the repair costs {hours} h of downtime."
                ),
                expected_value=round(value, 1),
                urgency=round(1 - min(1.0, life / 24), 3),
                score=0,
                actions=[
                    "Create work order",
                    f"Propose {repair['remedy']} on {repair['equipment']}",
                ],
                evidence=[
                    f"fault signature: {repair['fault']}",
                    f"severity estimate {repair['severity']}",
                ]
                + ([f"best window: {plan['best']}"] if plan else []),
                blocked=blocked,
                tick=state.tick,
            )
        )
        if blocked and part:
            items.append(
                Recommendation(
                    id=f"{plant_id}:spare_reorder:{part}",
                    plant_id=plant_id,
                    kind="spare_reorder",
                    title=f"Order spare '{part}'",
                    rationale=f"{blocked} It blocks the {repair['equipment']} repair.",
                    expected_value=round(max(value, 0.0), 1),
                    urgency=round(1 - min(1.0, params.spares[part][1] / 168), 3),
                    score=0,
                    actions=[f"Reorder {part}"],
                    evidence=[
                        f"stock {stock.get(part, 0)}",
                        f"lead time {params.spares[part][1]:.0f} h",
                    ],
                    tick=state.tick,
                )
            )
    if metrics.orders_at_risk:
        late = [o for o in ledger.orders if o.status != "fulfilled"][: metrics.orders_at_risk]
        exposure = sum((o.quantity_t - o.filled_t) * o.penalty_per_t for o in late)
        soonest = min((o.due_sim_seconds - state.sim_seconds) / 3600 for o in late) if late else 1.0
        items.append(
            Recommendation(
                id=f"{plant_id}:orders_at_risk:all",
                plant_id=plant_id,
                kind="orders_at_risk",
                title=f"{metrics.orders_at_risk} order(s) at risk of missing their due time",
                rationale="Current good output cannot cover the open orders in time.",
                expected_value=round(exposure, 1),
                urgency=round(1 - min(1.0, max(soonest, 0.0) / 4), 3),
                score=0,
                actions=["Prioritise the earliest orders", "Restore throughput"],
                evidence=[f"good rate {metrics.good_rate_tph} t/h of {metrics.nominal_rate_tph}"],
                tick=state.tick,
            )
        )
    best = optimize(platform, state, "energy")["best"]
    ref = optimize(platform, state, "recovery")["reference"]
    if best and best["executable"] and ref["energy_cost_per_h"] > 0:
        saving = ref["energy_cost_per_h"] - best["energy_cost_per_h"]
        if saving / ref["energy_cost_per_h"] >= 0.02:
            items.append(
                Recommendation(
                    id=f"{plant_id}:energy_saving:duty",
                    plant_id=plant_id,
                    kind="energy_saving",
                    title=f"Run duty {best['value']} for lower energy cost",
                    rationale="A tested duty recovers the band with lower fuel cost.",
                    expected_value=round(saving * 4, 1),
                    urgency=round(min(1.0, (metrics.tariff_multiplier - 1) / 1.2 + 0.1), 3),
                    score=0,
                    actions=[f"Propose thermal duty {best['value']}"],
                    evidence=[f"saves {saving:.1f} per hour in the twin forecast"],
                    tick=state.tick,
                )
            )
    decided = {v["id"] for v in platform.store.records("recommendations")}
    return _scored([i for i in items if i.id not in decided])
