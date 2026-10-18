"""Route group; stateful work belongs to platform services."""

import sqlite3

from fastapi import APIRouter, HTTPException

from cognition.api.context import ApiContext
from cognition.api.schemas import Trigger
from cognition.domain import Action, PlantSpec
from cognition.layers.perceptual.indicators import process_indicators
from cognition.simulation.thermal import simulate


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["plants"])
    platform, require, require_manual = context.platform, context.require, context.require_manual

    @router.get("/api/plants")
    def plants():
        return platform().store.plants()

    @router.post("/api/plants", status_code=201)
    def onboard(spec: PlantSpec):
        try:
            platform().onboard(spec)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Plant ID already exists") from exc
        return platform().store.plant(spec.id)

    @router.get("/api/plants/{plant_id}/instruments")
    def instruments(plant_id: str):
        require(plant_id)
        state = platform().connector.snapshot(plant_id)
        return {
            "plant_id": plant_id,
            "revision": state.revision,
            "sampled_at": state.model_dump(mode="json")["sampled_at"],
            "sim_seconds": state.sim_seconds,
            "tick": state.tick,
            "basis": "Derived model estimates; display bands are not plant operating limits.",
            "indicators": process_indicators(state),
        }

    @router.post("/api/plants/{plant_id}/scenarios")
    def trigger(plant_id: str, body: Trigger):
        require(plant_id)
        if plant_id in platform().busy:
            raise HTTPException(409, "Wait for the investigation before changing its snapshot")
        return platform().disturb(plant_id, body.scenario)

    @router.post("/api/plants/{plant_id}/reset")
    def reset(plant_id: str):
        require_manual(plant_id)
        return platform().reset(plant_id)

    @router.post("/api/plants/{plant_id}/predict")
    def predict(plant_id: str, body: Action):
        require(plant_id)
        state = platform().connector.snapshot(plant_id)
        try:
            prediction = simulate(state, body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"revision": state.revision, "prediction": prediction.model_dump()}

    return router
