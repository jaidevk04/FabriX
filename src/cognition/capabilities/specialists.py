"""Approved, advisory-only A2A specialists using the official Python SDK."""

import asyncio
import json
import os
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import Field, model_validator

from cognition.capabilities.registry import Capability
from cognition.domain import Contract, Request
from cognition.harnesses.streaming import PublicTextStream
from cognition.persistence.store import Store


class Specialist(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,40}$")
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(max_length=500)
    plant_ids: list[str] = Field(min_length=1, max_length=100)
    approved: bool = False
    card: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_endpoint(self):
        url = urlparse(self.url)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Specialist endpoint must not contain credentials, query or fragment")
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise ValueError("Use HTTPS or a loopback HTTP specialist")
        if not url.hostname:
            raise ValueError("Invalid specialist endpoint")
        return self


def origin(url: str):
    parsed = urlparse(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def credential_headers(specialist: Specialist) -> dict[str, str]:
    token = os.getenv(f"COGNITION_SPECIALIST_{specialist.id.upper().replace('-', '_')}_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def register(store: Store, specialist: Specialist, *, transport=None) -> Specialist:
    import httpx
    from a2a.client import A2ACardResolver
    from google.protobuf.json_format import MessageToDict

    if not specialist.approved:
        raise ValueError("Explicit approval to share scoped snapshots is required")
    try:
        store.get("specialists", specialist.id)
    except KeyError:
        pass
    else:
        raise ValueError("Specialist ID is already registered")
    for plant_id in specialist.plant_ids:
        store.plant(plant_id)
    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        transport=transport,
        headers=credential_headers(specialist),
    ) as http:
        card = await A2ACardResolver(http, specialist.url).get_agent_card()
    if not card.name or not card.supported_interfaces:
        raise ValueError("Specialist did not provide a usable agent card")
    if any(
        origin(interface.url) != origin(specialist.url) for interface in card.supported_interfaces
    ):
        raise ValueError("Agent card advertises an endpoint outside the approved origin")
    specialist.card = MessageToDict(card, preserving_proto_field_name=True)
    store.put("specialists", specialist.id, specialist)
    for plant_id in specialist.plant_ids:
        capability = Capability(
            id=f"{plant_id}:agent:{specialist.id}",
            plant_id=plant_id,
            kind="agent",
            name=specialist.id,
            description=card.description,
            transport="a2a",
            metadata={"url": specialist.url, "advisory_only": True},
        )
        store.put("capabilities", capability.id, capability)
        tool = Capability(
            id=f"{plant_id}:tool:delegate_specialist",
            plant_id=plant_id,
            kind="tool",
            name="delegate_specialist",
            transport="mcp",
            description="Request advisory analysis from approved scoped A2A specialists",
        )
        store.put("capabilities", tool.id, tool)
    return specialist


async def delegate(
    store: Store, request: Request, specialist_id: str, objective: str, *, transport=None
) -> dict:
    import httpx
    from a2a.client import ClientConfig, ClientFactory
    from a2a.types import (
        AgentCard,
        CancelTaskRequest,
        GetTaskRequest,
        Message,
        Part,
        Role,
        SendMessageRequest,
        TaskState,
    )
    from google.protobuf.json_format import ParseDict

    specialist = Specialist.model_validate_json(store.get("specialists", specialist_id))
    if not specialist.approved or request.snapshot.spec.id not in specialist.plant_ids:
        raise PermissionError("Specialist is outside the approved incident scope")
    headers = credential_headers(specialist)
    card = ParseDict(specialist.card, AgentCard())
    task_id = None
    client = None
    completed = False
    async with httpx.AsyncClient(
        timeout=15, headers=headers, follow_redirects=False, transport=transport
    ) as http:
        client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
        try:
            async with asyncio.timeout(30):
                message = Message(
                    message_id=str(uuid4()),
                    role=Role.ROLE_USER,
                    parts=[
                        Part(
                            text=json.dumps(
                                {
                                    "instruction": "Provide advisory analysis only; "
                                    "you have no control-write authority.",
                                    "objective": objective[:2000],
                                    "incident_id": request.incident_id,
                                    "snapshot": request.snapshot.model_dump(mode="json"),
                                }
                            )
                        )
                    ],
                )
                store.audit(
                    request.incident_id, "specialist_started", {"specialist_id": specialist.id}
                )
                result = None
                async for event in client.send_message(SendMessageRequest(message=message)):
                    result = event
                if result is None:
                    raise RuntimeError("Specialist returned no response")
                text = []
                state = "message"
                if result.HasField("message"):
                    text = [part.text for part in result.message.parts if part.text]
                elif result.HasField("task"):
                    task = result.task
                    task_id = task.id
                    while task.status.state in (
                        TaskState.TASK_STATE_SUBMITTED,
                        TaskState.TASK_STATE_WORKING,
                    ):
                        await asyncio.sleep(1)
                        task = await client.get_task(GetTaskRequest(id=task.id))
                    state = TaskState.Name(task.status.state)
                    if task.status.state != TaskState.TASK_STATE_COMPLETED:
                        raise RuntimeError("Specialist did not complete advisory analysis")
                    text = [
                        part.text
                        for artifact in task.artifacts
                        for part in artifact.parts
                        if part.text
                    ]
                redacted: list[str] = []
                stream = PublicTextStream(redacted.append)
                stream.push("\n".join(text)[:10000], final=True)
                completed = True
                output = {
                    "specialist_id": specialist.id,
                    "task_id": task_id,
                    "state": state,
                    "advisory": "".join(redacted),
                    "authority": "advisory_only",
                }
                store.audit(request.incident_id, "specialist_result", output)
                return output
        finally:
            if task_id and not completed:
                try:
                    await asyncio.wait_for(client.cancel_task(CancelTaskRequest(id=task_id)), 3)
                except Exception:
                    pass
            await client.close()
