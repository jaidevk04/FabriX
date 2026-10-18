"""World routes: live clock and fault injection. Unauthenticated, loopback only."""

from fastapi import APIRouter, HTTPException

from cognition.api.context import ApiContext
from cognition.api.schemas import InjectEvent, WorldStart
from cognition.industries import catalogue


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["world"])
    platform, require = context.platform, context.require

    @router.get("/api/plants/{plant_id}/world")
    def world_status(plant_id: str):
        require(plant_id)
        return platform().world.status(plant_id)

    @router.post("/api/plants/{plant_id}/world/start")
    async def world_start(plant_id: str, body: WorldStart | None = None):
        require(plant_id)
        try:
            return platform().world.start(plant_id, (body or WorldStart()).interval_seconds)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/plants/{plant_id}/world/stop")
    async def world_stop(plant_id: str):
        require(plant_id)
        return await platform().world.stop(plant_id)

    @router.get("/api/plants/{plant_id}/fault-catalogue")
    def fault_catalogue(plant_id: str):
        require(plant_id)
        industry = platform().store.plant(plant_id).spec.industry
        return [
            {
                "id": value.id,
                "name": value.name,
                "domain": value.domain,
                "equipment": value.equipment,
                "description": value.description,
                "remedy": value.remedy,
                "default_ramp_ticks": value.ramp_ticks,
                "effects": value.effects,
            }
            for value in catalogue(industry).values()
        ]

    @router.get("/api/plants/{plant_id}/faults")
    def faults(plant_id: str, include_cleared: bool = False):
        require(plant_id)
        return platform().faults.events(plant_id, include_cleared=include_cleared)

    @router.post("/api/plants/{plant_id}/faults", status_code=201)
    def inject(plant_id: str, body: InjectEvent):
        require(plant_id)
        try:
            return platform().faults.inject(
                plant_id,
                body.kind,
                severity=body.severity,
                ramp_ticks=body.ramp_ticks,
                duration_ticks=body.duration_ticks,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.delete("/api/plants/{plant_id}/faults/{fault_id}")
    def clear(plant_id: str, fault_id: str):
        require(plant_id)
        try:
            return platform().faults.clear(plant_id, fault_id, by="operator")
        except KeyError as exc:
            raise HTTPException(404, "Fault not found") from exc

    return router
