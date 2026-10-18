"""Layer status, qualified perception input and measured action response."""

from fastapi import APIRouter, HTTPException

from cognition.api.context import ApiContext
from cognition.layers.perceptual.service import Observation
from cognition.runtime.operations import operations


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["operations"])

    @router.get("/api/plants/{plant_id}/operations")
    def read_operations(plant_id: str):
        context.require(plant_id)
        return operations(context.platform(), plant_id, context.app.state.automation)

    @router.post("/api/plants/{plant_id}/perception", status_code=201)
    def publish_perception(plant_id: str, evidence: Observation):
        context.require(plant_id)
        platform = context.platform()
        try:
            return platform.perception.publish(platform.connector.snapshot(plant_id), evidence)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    return router
