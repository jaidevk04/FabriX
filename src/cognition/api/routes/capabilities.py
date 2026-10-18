"""Route group; stateful work belongs to platform services."""

import sqlite3

from fastapi import APIRouter, HTTPException

from cognition.api.context import ApiContext
from cognition.capabilities.registry import Capability, Manifest
from cognition.capabilities.specialists import Specialist, register
from cognition.domain import Request
from cognition.layers.cognitive.tools import Tools


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["capabilities"])
    platform, require = context.platform, context.require

    @router.post("/api/manifests", status_code=201)
    def import_manifest(manifest: Manifest):
        try:
            platform().onboard_manifest(manifest)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Plant ID already exists") from exc
        return manifest

    @router.get("/api/manifests")
    def manifests():
        return platform().store.records("manifests")

    @router.get("/api/registry")
    def registry():
        return platform().store.records("capabilities")

    @router.get("/api/specialists")
    def specialists():
        return platform().store.records("specialists")

    @router.post("/api/specialists", status_code=201)
    async def add_specialist(specialist: Specialist):
        try:
            return await register(platform().store, specialist)
        except Exception as exc:
            raise HTTPException(
                422,
                "Registration failed; check approval, plant scope and specialist agent card",
            ) from exc

    @router.delete("/api/specialists/{specialist_id}")
    def revoke_specialist(specialist_id: str):
        try:
            specialist = Specialist.model_validate_json(
                platform().store.get("specialists", specialist_id)
            )
        except KeyError as exc:
            raise HTTPException(404, "Specialist not found") from exc
        specialist.approved = False
        platform().store.put("specialists", specialist.id, specialist)
        for value in platform().store.records("capabilities"):
            if value["kind"] == "agent" and value["name"] == specialist.id:
                value["approved"] = False
                capability = Capability.model_validate(value)
                platform().store.put("capabilities", capability.id, capability)
            elif (
                value["name"] == "delegate_specialist" and value["plant_id"] in specialist.plant_ids
            ):
                value["approved"] = any(
                    item["approved"] and value["plant_id"] in item["plant_ids"]
                    for item in platform().store.records("specialists")
                )
                capability = Capability.model_validate(value)
                platform().store.put("capabilities", capability.id, capability)
        return {"specialist_id": specialist_id, "approved": False}

    @router.get("/api/plants/{plant_id}/capabilities")
    def discover(plant_id: str, query: str = ""):
        require(plant_id)
        request = Request(incident_id="discovery", snapshot=platform().store.plant(plant_id))
        return Tools(request, platform().store).discover(query)

    return router
