"""Business routes: simulated orders, inventory, energy and CO2e. Unauthenticated, loopback only."""

from fastapi import APIRouter

from cognition.api.context import ApiContext


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["business"])
    platform, require = context.platform, context.require

    @router.get("/api/plants/{plant_id}/business")
    def business(plant_id: str):
        require(plant_id)
        return platform().business.read(plant_id)

    return router
