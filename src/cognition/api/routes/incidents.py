"""Route group; stateful work belongs to platform services."""

import asyncio
import json
from uuid import uuid4

from anyio import CancelScope
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from cognition.api.context import ApiContext
from cognition.api.schemas import SelectHarness
from cognition.harnesses.base import ModelSettings
from cognition.harnesses.factory import create


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["incidents"])
    platform, require_manual = context.platform, context.require_manual

    @router.post("/api/plants/{plant_id}/resolve")
    async def resolve(plant_id: str, body: SelectHarness):
        require_manual(plant_id)
        try:
            harness = create(body.harness)
        except (ValueError, ImportError) as exc:
            raise HTTPException(
                422, "Harness unavailable; check SDK and model configuration"
            ) from exc
        return await platform().resolve(plant_id, harness)

    @router.get("/api/incidents")
    def incidents():
        return platform().store.incidents()

    @router.post("/api/plants/{plant_id}/resolve/stream")
    async def resolve_stream(plant_id: str, body: SelectHarness):
        require_manual(plant_id)
        try:
            harness = create(body.harness)
        except (ValueError, ImportError) as exc:
            raise HTTPException(
                422, "Harness unavailable; check SDK and model configuration"
            ) from exc
        incident_id = str(uuid4())

        def frame(event: str, data: dict, seq: int | None = None) -> str:
            prefix = f"id: {seq}\n" if seq is not None else ""
            return f"{prefix}event: {event}\ndata: {json.dumps(data)}\n\n"

        async def stream():
            task = asyncio.create_task(
                platform().resolve(plant_id, harness, incident_id=incident_id)
            )
            cursor = 0
            heartbeat = asyncio.get_running_loop().time()
            try:
                yield frame(
                    "session",
                    {
                        "incident_id": incident_id,
                        "harness": body.harness,
                        "model": ModelSettings.from_env().model
                        if body.harness != "reference"
                        else None,
                    },
                )
                while True:
                    for event in platform().store.events(incident_id, after=cursor):
                        cursor = event["seq"]
                        yield frame("activity", event, cursor)
                    if task.done():
                        incident = await task
                        # Drain final audit records written while the last frame was sent.
                        for event in platform().store.events(incident_id, after=cursor):
                            yield frame("activity", event, event["seq"])
                        yield frame("result", incident.model_dump(mode="json"))
                        break
                    if asyncio.get_running_loop().time() - heartbeat >= 10:
                        yield ": heartbeat\n\n"
                        heartbeat = asyncio.get_running_loop().time()
                    await asyncio.sleep(0.1)
            finally:
                if not task.done():
                    task.cancel()
                # A disconnected HTTP request cancels Starlette's task group.
                # Let worker/process-tree cleanup finish inside that scope.
                with CancelScope(shield=True):
                    await asyncio.gather(task, return_exceptions=True)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/incidents/{incident_id}/events")
    def events(incident_id: str):
        try:
            platform().store.get("incidents", incident_id)
        except KeyError as exc:
            raise HTTPException(404, "Incident not found") from exc
        return platform().store.events(incident_id)

    @router.get("/api/incidents/{incident_id}/stream")
    async def follow_incident(incident_id: str):
        try:
            platform().store.get("incidents", incident_id)
        except KeyError as exc:
            raise HTTPException(404, "Incident not found") from exc

        async def stream():
            cursor = 0
            heartbeat = 0.0
            session = json.dumps({"incident_id": incident_id, "harness": "automation"})
            yield f"event: session\ndata: {session}\n\n"
            while True:
                for event in platform().store.events(incident_id, after=cursor):
                    cursor = event["seq"]
                    yield f"id: {cursor}\nevent: activity\ndata: {json.dumps(event)}\n\n"
                data = json.loads(platform().store.get("incidents", incident_id))
                if data["status"] not in ("investigating", "verifying", "awaiting_approval"):
                    yield f"event: result\ndata: {json.dumps(data)}\n\n"
                    return
                if asyncio.get_running_loop().time() - heartbeat > 10:
                    yield ": heartbeat\n\n"
                    heartbeat = asyncio.get_running_loop().time()
                await asyncio.sleep(0.2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    return router
