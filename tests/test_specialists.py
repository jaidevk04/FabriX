import json

import httpx
import pytest
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict

from cognition.api import create_app
from cognition.capabilities.specialists import Specialist, delegate, register
from cognition.domain import Request
from cognition.layers.cognitive.tools import Tools


async def test_sdk_a2a_delegation_is_approved_scoped_and_advisory(platform):
    from a2a.types import AgentCard, AgentInterface, Message, Part, Role, SendMessageResponse

    card = AgentCard(
        name="Thermal specialist",
        description="Thermal advisory analysis",
        version="1",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        supported_interfaces=[
            AgentInterface(
                url="https://expert.example/a2a", protocol_binding="JSONRPC", protocol_version="1.0"
            )
        ],
    )
    payloads = []

    def endpoint(request):
        if request.method == "GET":
            return httpx.Response(200, json=MessageToDict(card))
        payload = json.loads(request.content)
        payloads.append(payload)
        response = SendMessageResponse(
            message=Message(
                message_id="reply",
                role=Role.ROLE_AGENT,
                parts=[Part(text="Read the SOP and test bounded duty changes.")],
            )
        )
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": payload["id"], "result": MessageToDict(response)}
        )

    transport = httpx.MockTransport(endpoint)
    specialist = Specialist(
        id="expert", name="Expert", url="https://expert.example", plant_ids=["kiln"], approved=True
    )
    await register(platform.store, specialist, transport=transport)
    request = Request(incident_id="a2a-test", snapshot=platform.store.plant("kiln"))
    result = await delegate(
        platform.store, request, "expert", "Review thermal recovery", transport=transport
    )
    assert result["authority"] == "advisory_only"
    assert "bounded duty" in result["advisory"]
    assert payloads[0]["method"] == "SendMessage"
    assert "delegate_specialist" in {
        function.__name__ for function in Tools(request, platform.store).functions()
    }
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
    specialist.approved = False
    platform.store.put("specialists", specialist.id, specialist)
    with pytest.raises(PermissionError, match="scope"):
        await delegate(platform.store, request, "expert", "Review", transport=transport)


@pytest.mark.parametrize(
    "url", ["http://external.example", "https://user:password@example.com", "file:///tmp/agent"]
)
def test_specialist_endpoint_restrictions(url):
    with pytest.raises(ValueError):
        Specialist(id="expert", name="Expert", url=url, plant_ids=["kiln"])


def test_revocation_removes_discovery_and_delegation():
    from cognition.capabilities.registry import Capability

    with TestClient(create_app(":memory:")) as client:
        store = client.app.state.platform.store
        specialist = Specialist(
            id="expert",
            name="Expert",
            url="https://expert.example",
            plant_ids=["cement-demo"],
            approved=True,
        )
        store.put("specialists", specialist.id, specialist)
        for kind, name in [("agent", "expert"), ("tool", "delegate_specialist")]:
            capability = Capability(
                id=f"cement-demo:{kind}:{name}",
                plant_id="cement-demo",
                kind=kind,
                name=name,
                description="Approved specialist",
                transport="a2a",
            )
            store.put("capabilities", capability.id, capability)
        assert client.delete("/api/specialists/expert").status_code == 200
        assert not client.get("/api/specialists").json()[0]["approved"]
        request = Request(incident_id="revoked", snapshot=store.plant("cement-demo"))
        tools = Tools(request, store)
        assert "delegate_specialist" not in {function.__name__ for function in tools.functions()}
        assert not any(capability["name"] == "expert" for capability in tools.discover())
