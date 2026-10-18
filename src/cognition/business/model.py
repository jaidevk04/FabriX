"""Business ledger: seeded orders, inventory and per-tick integration inside the world hook."""

import random
import sqlite3

from cognition.business.metrics import metrics
from cognition.domain import SECONDS_PER_TICK, BusinessState, Order, State
from cognition.industries import BUSINESS
from cognition.industries.base import BusinessParameters
from cognition.insights.kpi import KEEP_TICKS, KPI_EVERY, make_sample, sample_key
from cognition.persistence.store import Store
from cognition.simulation.faults import FaultEngine, active_effects

HOURS_PER_TICK = SECONDS_PER_TICK / 3600
DELIVERY_EVERY_TICKS = 360
NEW_ORDER_EVERY_TICKS = 120
MAX_OPEN_ORDERS = 8


def parameters(state: State) -> BusinessParameters:
    return BUSINESS[state.spec.industry]


def new_order(
    ledger: BusinessState,
    params: BusinessParameters,
    now_s: float,
    *,
    source="baseline",
    scale=1.0,
    hours=None,
    priority=2,
) -> Order:
    """Deterministic order sized against nominal capacity so degradation shows as risk."""
    rng = random.Random(f"{ledger.plant_id}:{ledger.order_seq}")
    due_hours = hours if hours is not None else rng.uniform(1.0, 2.0)
    quantity = params.nominal_rate_tph * due_hours * rng.uniform(0.55, 0.75) * scale
    ledger.order_seq += 1
    return Order(
        id=f"ord-{ledger.order_seq:03d}",
        product=params.product,
        quantity_t=round(quantity, 1),
        due_sim_seconds=now_s + due_hours * 3600,
        priority=priority,
        penalty_per_t=params.penalty_per_t,
        source=source,
    )


def initial_ledger(state: State) -> BusinessState:
    params = parameters(state)
    ledger = BusinessState(
        plant_id=state.spec.id,
        last_tick=state.tick,
        raw_material_t=round(params.nominal_rate_tph * params.raw_per_t * 2, 1),
        spares={part: qty for part, (qty, _lead) in params.spares.items()},
        next_delivery_tick=state.tick + DELIVERY_EVERY_TICKS,
    )
    for _ in range(3):
        ledger.orders.append(new_order(ledger, params, state.sim_seconds))
    return ledger


class BusinessModel:
    """Implements the business half of the connector's WorldHooks."""

    def __init__(self, store: Store, faults: FaultEngine) -> None:
        self.store = store
        self.faults = faults

    def ledger(self, state: State) -> BusinessState:
        try:
            return BusinessState.model_validate_json(
                self.store.get("business_state", state.spec.id)
            )
        except KeyError:
            return initial_ledger(state)

    def read(self, plant_id: str) -> dict:
        state = self.store.plant(plant_id)
        ledger = self.ledger(state)
        events = self.faults.events(plant_id)
        effects = active_effects(events, state.spec.industry, state.tick)
        params = parameters(state)
        current = metrics(state, effects, params, ledger)
        return {
            "plant_id": plant_id,
            "tick": state.tick,
            "sim_seconds": state.sim_seconds,
            "metrics": current,
            "ledger": ledger,
            "spares_available": self.spares_available(ledger, events),
            "spare_lead_hours": {part: lead for part, (_q, lead) in params.spares.items()},
            "remedy_spare": params.remedy_spare,
            "pending_spares": ledger.pending_spares,
            "business_events": [
                e for e in events if e.domain == "business" and e.state != "cleared"
            ],
        }

    def order_spare(self, plant_id: str, part: str, lead_ticks: int = 25) -> int:
        state = self.store.plant(plant_id)
        ledger = self.ledger(state)
        due_tick = state.tick + max(5, lead_ticks)
        ledger.pending_spares[part] = due_tick
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO business_state VALUES (?,?) "
                "ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (ledger.plant_id, ledger.model_dump_json()),
            )
        self.store.audit(
            f"business:{plant_id}",
            "spare_ordered",
            {"part": part, "ordered_tick": state.tick, "due_tick": due_tick},
        )
        return due_tick

    def record_repair(
        self, db: sqlite3.Connection, state: State, part: str | None, hours: float
    ) -> None:
        """Use a spare and start the repair downtime, in the caller's transaction (Gateway only)."""
        ledger = self.ledger(state)
        if part is not None:
            if ledger.spares.get(part, 0) <= 0:
                raise ValueError(f"No spare '{part}' in inventory")
            ledger.spares[part] -= 1
        ledger.downtime_until_tick = max(
            ledger.downtime_until_tick, state.tick + round(hours / HOURS_PER_TICK)
        )
        db.execute(
            "INSERT INTO business_state VALUES (?,?) "
            "ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (ledger.plant_id, ledger.model_dump_json()),
        )

    @staticmethod
    def spares_available(ledger: BusinessState, events) -> dict[str, int]:
        short = any(e.kind == "spare_shortage" and e.state != "cleared" for e in events)
        return {part: 0 if short else qty for part, qty in ledger.spares.items()}

    # WorldHooks

    def apply(self, db: sqlite3.Connection, state: State) -> State:
        ledger = self.ledger(state)
        events = self.faults.events(state.spec.id)
        params = parameters(state)
        arrived = []
        for part, due_tick in list(ledger.pending_spares.items()):
            if state.tick >= due_tick:
                ledger.spares[part] = ledger.spares.get(part, 0) + 1
                del ledger.pending_spares[part]
                arrived.append(part)
        if arrived:
            for event in self.faults.events(state.spec.id):
                if event.kind == "spare_shortage" and event.state != "cleared":
                    self.faults.clear(state.spec.id, event.id)
            self.store.audit(
                f"business:{state.spec.id}",
                "spare_delivered",
                {"parts": arrived, "spares": ledger.spares},
            )
        self._react(ledger, params, state, events)
        effects = active_effects(events, state.spec.industry, state.tick)
        current = metrics(state, effects, params, ledger)
        self._integrate(ledger, params, state, effects, current)
        ledger.last_tick = state.tick
        if state.tick % KPI_EVERY == 0:
            sample = make_sample(state, current, ledger)
            plant = ledger.plant_id
            db.execute(
                "INSERT INTO kpi_samples VALUES (?,?) "
                "ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (sample_key(plant, state.tick), sample.model_dump_json()),
            )
            db.execute(
                "DELETE FROM kpi_samples WHERE id >= ? AND id < ?",
                (f"{plant}:", sample_key(plant, max(0, state.tick - KEEP_TICKS))),
            )
        db.execute(
            "INSERT INTO business_state VALUES (?,?) "
            "ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (ledger.plant_id, ledger.model_dump_json()),
        )
        return state

    def offset(self, plant_id: str) -> float:
        return 0.0

    def reset(self, db: sqlite3.Connection, plant_id: str) -> None:
        db.execute("DELETE FROM business_state WHERE id=?", (plant_id,))
        db.execute(
            "DELETE FROM kpi_samples WHERE id >= ? AND id < ?", (f"{plant_id}:", f"{plant_id};")
        )

    def _react(self, ledger: BusinessState, params, state: State, events) -> None:
        """Create orders once per business event; baseline demand arrives on a fixed cadence."""
        for event in events:
            if event.id in ledger.processed_events or event.domain != "business":
                continue
            ledger.processed_events.append(event.id)
            if event.kind == "demand_surge":
                for _ in range(2 + round(4 * event.severity)):
                    ledger.orders.append(
                        new_order(ledger, params, state.sim_seconds, source="demand_surge")
                    )
            elif event.kind == "rush_order":
                ledger.orders.append(
                    new_order(
                        ledger,
                        params,
                        state.sim_seconds,
                        source="rush_order",
                        scale=1 + event.severity,
                        hours=0.5,
                        priority=3,
                    )
                )
        open_orders = sum(1 for o in ledger.orders if o.status != "fulfilled")
        elapsed = state.tick - ledger.last_tick
        if (
            state.tick > 0
            and state.tick % NEW_ORDER_EVERY_TICKS < max(1, elapsed)
            and open_orders < MAX_OPEN_ORDERS
        ):
            ledger.orders.append(new_order(ledger, params, state.sim_seconds))

    def _integrate(self, ledger: BusinessState, params, state: State, effects, current) -> None:
        delayed = effects.get("business", {}).get("supply", 0.0) < 0
        if state.tick >= ledger.next_delivery_tick:
            if not delayed:
                ledger.raw_material_t += params.nominal_rate_tph * params.raw_per_t * 1.5
            ledger.next_delivery_tick = state.tick + DELIVERY_EVERY_TICKS
        if state.tick < ledger.downtime_until_tick:
            ledger.downtime_ticks += 1
        produced = min(
            current.production_rate_tph * HOURS_PER_TICK, ledger.raw_material_t / params.raw_per_t
        )
        share = produced / (current.production_rate_tph * HOURS_PER_TICK or 1)
        ledger.raw_material_t = max(0.0, ledger.raw_material_t - produced * params.raw_per_t)
        scrap = produced * current.scrap_fraction
        ledger.produced_t += produced
        ledger.scrap_t += scrap
        ledger.finished_goods_t += produced - scrap
        ledger.fuel_gj += current.fuel_gj_per_h * HOURS_PER_TICK * share
        ledger.electricity_kwh += current.electricity_kw * HOURS_PER_TICK * share
        ledger.co2e_kg += current.co2e_kg_per_h * HOURS_PER_TICK * share
        ledger.energy_cost += current.energy_cost_per_h * HOURS_PER_TICK * share
        for order in sorted(
            (o for o in ledger.orders if o.status != "fulfilled"),
            key=lambda o: (-o.priority, o.due_sim_seconds),
        ):
            take = min(ledger.finished_goods_t, order.quantity_t - order.filled_t)
            order.filled_t += take
            ledger.finished_goods_t -= take
            if order.filled_t >= order.quantity_t - 1e-9:
                order.status = "fulfilled"
                ledger.revenue += order.quantity_t * params.price_per_t
            elif order.status == "open" and state.sim_seconds > order.due_sim_seconds:
                order.status = "late"
                ledger.penalty_cost += (order.quantity_t - order.filled_t) * order.penalty_per_t
        ledger.orders = [o for o in ledger.orders if o.status != "fulfilled"][-30:] + [
            o for o in ledger.orders if o.status == "fulfilled"
        ][-10:]
