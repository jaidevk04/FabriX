"""Simulated maintenance work orders: drafted from alerts, tracked through robot repairs."""

from cognition.business.model import parameters
from cognition.cores.base import plant_equipment
from cognition.domain import ActionOrder, MaintenanceAction, WorkOrder, now
from cognition.industries import catalogue

ACTIVE = ("open", "in_progress")


class WorkOrders:
    def __init__(self, platform) -> None:
        self.platform = platform

    def all(self, plant_id: str | None = None, status: str | None = None) -> list[WorkOrder]:
        found = [WorkOrder.model_validate(v) for v in self.platform.store.records("work_orders")]
        found = [w for w in found if (plant_id is None or w.plant_id == plant_id)]
        found = [w for w in found if status is None or w.status == status]
        return sorted(found, key=lambda w: w.created_at)

    def get(self, order_id: str) -> WorkOrder:
        return WorkOrder.model_validate_json(self.platform.store.get("work_orders", order_id))

    def _save(self, order: WorkOrder, kind: str, body: dict | None = None) -> None:
        self.platform.store.put("work_orders", order.id, order)
        self.platform.store.audit(
            f"cores:{order.plant_id}",
            kind,
            {"correlation_id": order.source_ref or order.id, "work_order": order.id} | (body or {}),
        )

    def _existing(self, plant_id: str, equipment: str, remedy: str) -> WorkOrder | None:
        return next(
            (
                w
                for w in self.all(plant_id)
                if w.equipment == equipment and w.remedy == remedy and w.status in ACTIVE
            ),
            None,
        )

    def create(
        self,
        plant_id: str,
        equipment: str,
        remedy: str,
        *,
        source: str = "operator",
        source_ref: str = "",
        priority: int = 2,
        note: str = "",
        status: str = "open",
    ) -> WorkOrder:
        state = self.platform.store.plant(plant_id)
        if equipment not in plant_equipment(state):
            raise ValueError(f"Unknown equipment '{equipment}' for this plant")
        known = catalogue(state.spec.industry).values()
        if not any(d.equipment == equipment and d.remedy == remedy for d in known):
            raise ValueError(f"Remedy '{remedy}' does not apply to {equipment}")
        existing = self._existing(plant_id, equipment, remedy)
        if existing is not None:
            return existing
        params = parameters(state)
        part = params.remedy_spare.get(remedy)
        hours = params.repair_hours.get(remedy, 0.0)
        order = WorkOrder(
            plant_id=plant_id,
            equipment=equipment,
            remedy=remedy,
            title=f"{remedy.replace('_', ' ').capitalize()} on {equipment}",
            status=status,  # type: ignore[arg-type]
            priority=priority,  # type: ignore[arg-type]
            source=source,  # type: ignore[arg-type]
            source_ref=source_ref,
            part=part,
            est_hours=hours,
            est_cost=params.part_cost.get(part or "", 0.0),
            created_tick=state.tick,
            note=note,
        )
        self._save(order, "work_order_created", {"source": source})
        return order

    def cancel(self, order_id: str) -> WorkOrder:
        order = self.get(order_id)
        if order.status != "open":
            raise ValueError("Only open work orders can be cancelled")
        order.status = "cancelled"
        self._save(order, "work_order_cancelled")
        return order

    # Hooks called by the action pipeline.

    def start(self, order: ActionOrder, action: MaintenanceAction) -> WorkOrder:
        work = self.create(
            order.plant_id,
            action.equipment,
            action.remedy,
            source="order",
            source_ref=order.incident_id,
            priority=3,
        )
        work.status, work.source_ref = "in_progress", order.incident_id
        self._save(work, "work_order_started")
        return work

    def finish(self, order: ActionOrder, action: MaintenanceAction) -> None:
        work = self._existing(order.plant_id, action.equipment, action.remedy)
        if work is None:
            return
        work.status = "completed"
        work.completed_tick = self.platform.store.plant(order.plant_id).tick
        self._save(work, "work_order_completed", {"command": order.command_ids[-1:]})

    def release(self, order: ActionOrder, action: MaintenanceAction, reason: str) -> None:
        work = self._existing(order.plant_id, action.equipment, action.remedy)
        if work is not None and work.status == "in_progress":
            work.status, work.note = "open", f"Not done: {reason}"[:300]
            self._save(work, "work_order_released")

    def draft_from_alert(self, report, alert) -> WorkOrder | None:
        """Open a draft when a notify or escalate alert has a sensor-derived repair behind it."""
        from cognition.cores.learning.reference import diagnose

        if alert.core not in ("learning", "vision") or alert.level not in ("notify", "escalate"):
            return None
        for found in diagnose(self.platform, report.plant_id):
            if found["equipment"] == alert.equipment and found["match"] >= 0.5:
                return self.create(
                    report.plant_id,
                    found["equipment"],
                    found["remedy"],
                    source="alert",
                    source_ref=alert.id,
                    priority=3 if alert.level == "escalate" else 2,
                    note=f"Drafted from {alert.core} alert: {alert.title}"[:300],
                )
        return None


__all__ = ["WorkOrders", "now"]
