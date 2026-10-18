import asyncio
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from cognition.api import create_app
from cognition.api.schemas import SelectHarness
from cognition.domain import Request
from cognition.harnesses.antigravity import AntigravityHarness
from cognition.harnesses.reference import ReferenceHarness
from cognition.harnesses.streaming import PublicTextStream
from cognition.layers.cognitive.tools import Tools
from cognition.runtime.automation import Automation


def test_secret_split_across_chunks_is_redacted(monkeypatch):
    secret = "test-private-credential-123456"
    monkeypatch.setenv("GOOGLE_API_KEY", secret)
    output = []
    stream = PublicTextStream(output.append)
    stream.push("Starting " + "x" * 200 + secret[:10])
    assert output  # Delivers before completion, while retaining a safety tail.
    stream.push(secret[10:] + " done " + "y" * 200)
    stream.push("", final=True)
    text = "".join(output)
    assert secret not in text
    assert "[REDACTED]" in text
    assert text.endswith("y" * 200)


def test_sse_workflow_delivers_ordered_audit_and_outcome():
    with TestClient(create_app(":memory:")) as client:
        client.post("/api/plants/cement-demo/scenarios", json={"scenario": "heat_load"})
        with client.stream(
            "POST", "/api/plants/cement-demo/resolve/stream", json={"harness": "reference"}
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            blocks = "".join(response.iter_text()).split("\n\n")
        frames = []
        for block in blocks:
            lines = block.splitlines()
            event = next((line[7:] for line in lines if line.startswith("event: ")), None)
            data = next((line[6:] for line in lines if line.startswith("data: ")), None)
            if event and data:
                frames.append((event, json.loads(data)))
        assert frames[0][0] == "session"
        assert frames[-1][0] == "result"
        assert frames[-1][1]["status"] == "resolved"
        events = [data for name, data in frames if name == "activity"]
        assert events[0]["kind"] == "started"
        assert any(event["kind"] == "tool_called" for event in events)
        assert len({event["seq"] for event in events}) == len(events)
        assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)
        incident = frames[-1][1]
        assert client.get(f"/api/incidents/{incident['id']}/events").json() == events
        assert client.post("/api/plants/missing/resolve/stream", json={}).status_code == 404
        assert (
            client.post(
                "/api/plants/cement-demo/resolve/stream", json={"harness": "unknown"}
            ).status_code
            == 422
        )


async def test_stream_emits_before_completion_and_disconnect_cancels(platform, monkeypatch):
    waiting = asyncio.Event()

    class Slow(ReferenceHarness):
        async def propose(self, request, tools):
            tools.emit("Reading the process telemetry.\n")
            waiting.set()
            await asyncio.Event().wait()

    monkeypatch.setattr("cognition.api.routes.incidents.create", lambda name: Slow())
    app = create_app(":memory:")
    app.state.platform = platform
    app.state.automation = Automation(platform)
    # Current FastAPI keeps included routers lazy; inspect their actual routes.
    routes = [
        item
        for route in app.routes
        for item in getattr(getattr(route, "original_router", None), "routes", [route])
    ]
    endpoint = next(
        route.endpoint
        for route in routes
        if getattr(route, "path", "") == "/api/plants/{plant_id}/resolve/stream"
    )
    response = await endpoint("kiln", SelectHarness(harness="reference"))
    iterator = response.body_iterator
    session = await anext(iterator)
    assert "event: session" in session
    await asyncio.wait_for(waiting.wait(), 1)
    started = await anext(iterator)
    text = await anext(iterator)
    assert '"kind": "started"' in started
    assert "Reading the process telemetry" in text
    assert platform.store.incidents()[0].status == "investigating"
    await iterator.aclose()
    assert platform.store.incidents()[0].status == "interrupted"


async def test_sdk_response_text_streams_before_structured_output(platform, monkeypatch):
    request = Request(incident_id="sdk-stream", snapshot=platform.store.plant("kiln"))
    tools = Tools(request, platform.store)
    proposal = await ReferenceHarness().propose(request, tools)

    class Response:
        async def __aiter__(self):
            yield "Reading approved telemetry. " * 8
            yield "Investigation complete."

        async def structured_output(self):
            events = platform.store.events(request.incident_id)
            assert any(event["kind"] == "agent_text" for event in events)
            return proposal.model_dump()

    class Agent:
        def __init__(self, config):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def chat(self, prompt):
            return Response()

    monkeypatch.setitem(sys.modules, "google.antigravity", SimpleNamespace(Agent=Agent))
    harness = object.__new__(AntigravityHarness)
    monkeypatch.setattr(harness, "build", lambda tools, server=None: None)

    @asynccontextmanager
    async def fake_mcp(tools):
        yield None

    monkeypatch.setattr("cognition.mcp.incident.incident_mcp", fake_mcp)
    assert await harness.propose(request, tools) == proposal
    output = "".join(
        event["body"]["text"]
        for event in platform.store.events(request.incident_id)
        if event["kind"] == "agent_text"
    )
    assert output.endswith("Investigation complete.")
