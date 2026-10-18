"""Order and mission routes. Unauthenticated, loopback only; robots go through FleetGateway."""

from fastapi import APIRouter, HTTPException

from cognition.api.context import ApiContext
from cognition.api.schemas import MissionRequest
from cognition.control.gateway import Rejected
from cognition.domain import Mission


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["orders"])
    platform, require = context.platform, context.require

    @router.get("/api/plants/{plant_id}/orders")
    def orders(plant_id: str):
        require(plant_id)
        return platform().orders.all(plant_id)

    @router.get("/api/orders/{order_id}")
    def order(order_id: str):
        try:
            return platform().orders.get(order_id)
        except KeyError as exc:
            raise HTTPException(404, "Order not found") from exc

    @router.post("/api/orders/{order_id}/followup/approval")
    async def followup_approval(order_id: str, accepted: bool):
        try:
            return await platform().orders.decide_followup(order_id, accepted=accepted)
        except KeyError as exc:
            raise HTTPException(404, "Order not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/plants/{plant_id}/missions")
    def missions(plant_id: str):
        require(plant_id)
        found = [
            Mission.model_validate(v)
            for v in platform().store.records("missions")
            if str(v.get("id", "")).startswith("mis-") and v["plant_id"] == plant_id
        ]
        return sorted(found, key=lambda m: m.created_at)

    @router.post("/api/plants/{plant_id}/missions", status_code=201)
    def run_mission(plant_id: str, body: MissionRequest):
        require(plant_id)
        try:
            return platform().fleet_gateway.run(
                plant_id, body.kind, body.target, tool=body.tool, expect=body.expect
            )
        except Rejected as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
