"""Agent estate routes: the agent map and per-agent log. Read only, unauthenticated, loopback."""

from fastapi import APIRouter, HTTPException

from cognition.api.context import ApiContext
from cognition.runtime import agentlog


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["agents"])
    platform, require = context.platform, context.require

    @router.get("/api/plants/{plant_id}/agents/estate")
    def estate(plant_id: str):
        """Agents, their connections and what each is doing right now."""
        require(plant_id)
        automation = context.app.state.automation.state(plant_id)
        return agentlog.estate(platform(), plant_id, automation)

    @router.get("/api/plants/{plant_id}/agents/{agent}/log")
    def log(plant_id: str, agent: str, after: int = 0, limit: int = 400):
        """Readable log for one agent since the last plant reset. Poll with `after` to stream."""
        require(plant_id)
        if agent not in agentlog.AGENTS:
            raise HTTPException(404, "Unknown agent")
        return agentlog.entries(
            platform(), plant_id, agent, max(after, 0), min(max(limit, 1), 1000)
        )

    return router
