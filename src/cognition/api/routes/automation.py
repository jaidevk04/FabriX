"""Route group; stateful work belongs to platform services."""

from fastapi import APIRouter, HTTPException

from cognition.api.context import ApiContext
from cognition.api.schemas import AttentionDecision
from cognition.runtime.automation import AutomationConfig


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["automation"])
    platform, require, app = context.platform, context.require, context.app

    @router.get("/api/automation")
    def automation_states():
        return [app.state.automation.state(state.spec.id) for state in platform().store.plants()]

    @router.post("/api/plants/{plant_id}/automation")
    def enable_automation(plant_id: str, config: AutomationConfig):
        require(plant_id)
        try:
            return app.state.automation.enable(plant_id, config)
        except (ValueError, ImportError) as exc:
            raise HTTPException(
                422, "Automation unavailable or already active; check selected harness"
            ) from exc

    @router.delete("/api/plants/{plant_id}/automation")
    async def disable_automation(plant_id: str):
        require(plant_id)
        return await app.state.automation.disable(plant_id)

    @router.post("/api/plants/{plant_id}/attention")
    async def attention(plant_id: str, body: AttentionDecision):
        """Operator answer to an escalation. Unauthenticated and loopback-only like the rest."""
        require(plant_id)
        try:
            return await app.state.automation.operator_decision(plant_id, body.action)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/incidents/{incident_id}/approval")
    async def approve(incident_id: str, accepted: bool):
        try:
            return await platform().approve(incident_id, accepted=accepted)
        except KeyError as exc:
            raise HTTPException(404, "Incident not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
