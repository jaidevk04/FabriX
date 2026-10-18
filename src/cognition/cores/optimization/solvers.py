"""Small exact solvers in plain Python: spare allocation, robot assignment, maintenance window."""

from cognition.business.metrics import metrics
from cognition.business.model import parameters
from cognition.cores.learning.monitor import channel_scores, fuse, remaining_life_hours
from cognition.cores.learning.reference import diagnose
from cognition.domain import State
from cognition.industries import catalogue
from cognition.industries.base import FaultDef
from cognition.simulation.faults import active_effects

MAX_EXACT = 10  # brute force stays instant at this size


def assign_spares(requests: list[dict], stock: dict[str, int]) -> dict:
    """Pick the set of repairs the stock can serve that has the highest total priority."""
    if len(requests) > MAX_EXACT:
        requests = sorted(requests, key=lambda r: -r["priority"])[:MAX_EXACT]
    best: tuple[float, int, tuple[int, ...]] = (-1.0, 0, ())
    for mask in range(1 << len(requests)):
        chosen = [i for i in range(len(requests)) if mask >> i & 1]
        used: dict[str, int] = {}
        for i in chosen:
            part = requests[i]["part"]
            if part:
                used[part] = used.get(part, 0) + 1
        if any(count > stock.get(part, 0) for part, count in used.items()):
            continue
        total = sum(requests[i]["priority"] for i in chosen)
        if (total, -len(chosen)) > (best[0], -best[1]):
            best = (total, len(chosen), tuple(chosen))
    served = [requests[i] for i in best[2]]
    unserved = [r for i, r in enumerate(requests) if i not in best[2]]
    return {"served": served, "unserved": unserved, "total_priority": max(best[0], 0.0)}


def assign_robots(missions: list[dict], robots: list[dict], hops) -> dict:
    """Most missions covered first, then the lowest total travel cost. Role and battery apply."""
    usable = [r for r in robots if r["battery"] >= 20]

    def search(index: int, used: frozenset[str]) -> tuple[int, float, list[tuple[str, str]]]:
        if index == len(missions):
            return 0, 0.0, []
        mission = missions[index]
        best = search(index + 1, used)  # leave this mission unassigned
        for robot in usable:
            if robot["name"] in used or robot["kind"] != mission["role"]:
                continue
            cost = hops(robot["zone"], mission["zone"]) * 2.0 + 3.0
            covered, rest, pairs = search(index + 1, used | {robot["name"]})
            option = (covered + 1, cost + rest, [(mission["id"], robot["name"]), *pairs])
            if (option[0], -option[1]) > (best[0], -best[1]):
                best = option
        return best

    _, cost, pairs = search(0, frozenset())
    assigned = dict(pairs)
    return {
        "assignments": [{"mission": k, "robot": v} for k, v in assigned.items()],
        "unassigned": [m["id"] for m in missions if m["id"] not in assigned],
        "total_battery_cost": round(cost, 1),
    }


def diagnosed_repairs(
    platform, plant_id: str, equipment: list[str], min_match: float = 0.5
) -> list[dict]:
    """Repairs implied by sensor-derived diagnoses (never by hidden event labels)."""
    seen, repairs = set(), []
    fused = fuse(channel_scores(platform, plant_id))
    for found in diagnose(platform, plant_id):
        if found["match"] < min_match or found["equipment"] in seen:
            continue
        if equipment and found["equipment"] not in equipment:
            continue
        seen.add(found["equipment"])
        repairs.append(
            {
                "equipment": found["equipment"],
                "fault": found["fault"],
                "remedy": found["remedy"],
                "severity": round(min(1.0, found["strength"] + 0.2), 2),
                # Simulated prognosis curve from the fused sensor score; not a calibrated life.
                "life_hours": remaining_life_hours(
                    fused.get(found["equipment"], {}).get("score", 0.0)
                ),
            }
        )
    return repairs


def _fault_rate_loss(state: State, params, ledger, definition: FaultDef, severity: float) -> float:
    healthy = metrics(state, {}, params, ledger).good_rate_tph
    effects = {
        "business": {k: v * severity for k, v in definition.effects.get("business", {}).items()}
    }
    return max(0.0, healthy - metrics(state, effects, params, ledger).good_rate_tph)


def plan_maintenance_window(
    platform, state: State, repairs: list[dict], horizon_hours: float = 6.0
) -> dict:
    """Compare doing the repairs now with doing them after each open order is covered."""
    params = parameters(state)
    ledger = platform.business.ledger(state)
    known = catalogue(state.spec.industry)
    healthy = metrics(state, {}, params, ledger).good_rate_tph
    current = metrics(
        state,
        active_effects(platform.faults.events(state.spec.id), state.spec.industry, state.tick),
        params,
        ledger,
    ).good_rate_tph
    downtime = sum(params.repair_hours.get(r["remedy"], 0.0) for r in repairs)
    restore = sum(
        _fault_rate_loss(state, params, ledger, known[r["fault"]], r["severity"])
        for r in repairs
        if r["fault"] in known
    )
    parts = sum(
        params.part_cost.get(params.remedy_spare.get(r["remedy"]) or "", 0.0) for r in repairs
    )
    orders = sorted(
        (o for o in ledger.orders if o.status != "fulfilled"), key=lambda o: o.due_sim_seconds
    )
    step = 0.05

    def simulate_plan(start: float | None) -> dict:
        produced, t, late_t = ledger.finished_goods_t, 0.0, 0.0
        timeline = []
        # A repair that comes after the simulated remaining life means a breakdown first.
        fails = [r["life_hours"] for r in repairs if start is None or start > r["life_hours"]]
        failure = min(fails) if fails else None
        while t < horizon_hours:
            if start is not None and start <= t < start + downtime:
                rate = 0.0
            elif start is not None and t >= start + downtime:
                rate = min(healthy, current + restore)
            else:
                rate = current
            if failure is not None and t >= failure and (start is None or t < start + downtime):
                rate = 0.0
            produced += rate * step
            timeline.append((t + step, produced))
            t += step
        need, late_orders = 0.0, 0
        for order in orders:
            need += order.quantity_t - order.filled_t
            due = max((order.due_sim_seconds - state.sim_seconds) / 3600, 0.0)
            made = next((p for hour, p in timeline if hour >= min(due, horizon_hours)), produced)
            if made < need:
                late_orders += 1
                late_t += min(need - made, order.quantity_t)
        penalty = late_t * params.penalty_per_t
        revenue = (produced - ledger.finished_goods_t) * params.price_per_t
        cost = parts if start is not None else 0.0
        return {
            "late_orders": late_orders,
            "late_tonnes": round(late_t, 1),
            "penalty_cost": round(penalty, 1),
            "produced_t": round(produced - ledger.finished_goods_t, 1),
            "net_value": round(revenue - penalty - cost, 1),
            "breakdown_at_hours": round(failure, 1) if failure is not None else None,
        }

    plans = [{"plan": "no_repair", "start_hours": None} | simulate_plan(None)]
    starts = {"repair_now": 0.0}
    cumulative = 0.0
    for order in orders[:4]:
        cumulative += order.quantity_t - order.filled_t
        hours = cumulative / max(current, 1e-6)
        if hours + downtime < horizon_hours:
            starts[f"after_{order.id}"] = round(hours, 2)
    for name, start in starts.items():
        plans.append({"plan": name, "start_hours": start} | simulate_plan(start))
    best = max(plans, key=lambda p: (p["net_value"], -p["late_orders"]))
    return {
        "repairs": repairs,
        "downtime_hours": round(downtime, 2),
        "rate_restored_tph": round(restore, 2),
        "parts_cost": parts,
        "plans": plans,
        "best": best["plan"],
        "basis": "Simulated production against open orders; placeholder prices and downtimes.",
    }


def spare_requests(platform, state: State, repairs: list[dict]) -> list[dict]:
    params = parameters(state)
    known = catalogue(state.spec.industry)
    requests = []
    for repair in repairs:
        loss = (
            _fault_rate_loss(
                state,
                params,
                platform.business.ledger(state),
                known[repair["fault"]],
                repair["severity"],
            )
            if repair["fault"] in known
            else 0.0
        )
        requests.append(
            {
                "id": repair["equipment"],
                "remedy": repair["remedy"],
                "part": params.remedy_spare.get(repair["remedy"]),
                "priority": round(repair["severity"] * 10 + loss, 2),
            }
        )
    return requests


def robot_missions(platform, plant_id: str, repairs: list[dict]) -> tuple[list[dict], list[dict]]:
    fleet = platform.fleet.state(plant_id)
    zone_of = {item: z.id for z in fleet.zones for item in z.equipment}
    missions = [
        {
            "id": f"verify-{r['equipment']}",
            "role": "inspector",
            "zone": zone_of.get(r["equipment"], "dock"),
        }
        for r in repairs
    ]
    robots = [
        {"name": r.name, "kind": r.kind, "zone": r.zone, "battery": r.battery}
        for r in fleet.robots
        if r.status in ("docked", "idle")
    ]
    return missions, robots


__all__ = [
    "assign_robots",
    "assign_spares",
    "diagnosed_repairs",
    "plan_maintenance_window",
    "robot_missions",
    "spare_requests",
]
