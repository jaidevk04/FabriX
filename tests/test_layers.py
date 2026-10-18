from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from cognition.api import create_app
from cognition.control.gateway import Rejected
from cognition.domain import Action, Industry, PlantSpec, Proposal, Request, now
from cognition.harnesses.reference import ReferenceHarness
from cognition.industries import get_industry
from cognition.layers.cognitive.prompt import SYSTEM_PROMPT, prompt
from cognition.layers.cognitive.tools import Tools
from cognition.layers.perceptual.service import Observation, Perception
from cognition.layers.reflexive import assess
from cognition.mcp.adapters import tool_functions
from cognition.mcp.control import execute_authorized
from cognition.mcp.incident import build_incident_server
from cognition.runtime.automation import Automation, AutomationConfig
from cognition.simulation.thermal import PACKS, advance


@pytest.mark.parametrize("industry", list(Industry))
async def test_industry_mcp_tools_are_scoped_and_share_generic_harness(platform, industry):
    identifier = f"scope-{industry}"
    platform.onboard(PlantSpec(id=identifier, name=identifier, industry=industry))
    snapshot = platform.connector.disturb(identifier, "heat_load")
    request = Request(incident_id=identifier, snapshot=snapshot)
    tools = Tools(request, platform.store)
    profile = get_industry(industry).PROFILE
    async with Client(build_incident_server(tools)) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert profile.read_tool in names and profile.simulate_tool in names
        assert "apply_validated_action" not in names
        for other in Industry:
            if other != industry:
                assert get_industry(other).PROFILE.read_tool not in names
        skill = await client.call_tool("read_skill", {"name": profile.skill})
        assert profile.read_tool in skill.structured_content["content"]
        wrong = await client.call_tool("read_skill", {"name": "../../.env"})
        assert wrong.is_error
    assert profile.skill in prompt(request)
    assert "cognitive supervisor" in SYSTEM_PROMPT
    assert "kiln" not in SYSTEM_PROMPT.lower()
    incident = await platform.resolve(identifier, ReferenceHarness(), live=True)
    assert incident.status == "verifying"
    dispatch = [
        event for event in platform.store.events(incident.id) if event["kind"] == "command_dispatch"
    ]
    assert dispatch[0]["body"]["sdk"] == "modelcontextprotocol/python-sdk"


def observation(state, **updates):
    return Observation.model_validate(
        {
            "id": "vision-check",
            "plant_id": state.spec.id,
            "revision": state.revision,
            "observed_at": now(),
            "expires_at": now() + timedelta(seconds=60),
            "source": "vision",
            "model": "external-test-model",
            "label": "Quality assessment",
            "status": "normal",
            "confidence": 0.9,
            "summary": "External test evidence.",
        }
        | updates
    )


def test_perceptual_evidence_conflicts_age_and_frozen_incident(platform):
    state = platform.connector.disturb("kiln", "heat_load")
    perception = Perception(platform.store)
    perception.publish(state, observation(state))
    tools = Tools(Request(incident_id="frozen-evidence", snapshot=state), platform.store)
    assert tools.read_layers()["perceptual"]["conflicts"]
    updated = platform.connector.tick("kiln", 1)
    assert perception.assess(updated)["conflicts"]
    for _ in range(3):
        updated = platform.connector.tick("kiln", 1)
    report = perception.assess(updated)
    assert report["observations"] == [] and report["excluded_observations"] == 1
    assert tools.read_layers()["perceptual"]["conflicts"]
    with pytest.raises(ValueError, match="revision"):
        perception.publish(updated, observation(state))
    with pytest.raises(ValueError, match="stale"):
        perception.publish(
            updated,
            observation(
                updated,
                observed_at=now() - timedelta(seconds=30),
                expires_at=now() - timedelta(seconds=1),
            ),
        )


async def test_conflict_triggers_review_and_reference_escalates(platform):
    state = platform.store.plant("kiln")
    platform.perception.publish(state, observation(state, status="anomaly"))
    automation = Automation(platform)
    automation.enable("kiln", AutomationConfig(mode="autopilot"))
    await automation.step(force=True)
    await automation.tasks["kiln"]
    assert automation.state("kiln").phase == "attention"
    assert platform.store.incidents()[0].status == "escalated"
    assert platform.store.records("commands") == []


def test_reflexive_cutoff_is_independent_of_cognition_and_cannot_be_overridden(platform):
    state = platform.store.plant("kiln")
    state.temperature = state.target + PACKS[state.spec.industry].envelope + 1
    state.duty = 90
    platform.store.put("plants", state.spec.id, state)
    assert assess(state)["status"] == "interlocked"
    stepped, _ = advance(state, 1)
    assert stepped.interlock and stepped.actuator < state.actuator
    proposal = Proposal(
        plant_id="kiln",
        revision=state.revision,
        expires_at=now() + timedelta(seconds=60),
        summary="Attempted override",
        action=Action(value=70),
    )
    with pytest.raises(Rejected, match="interlock"):
        platform.gateway.execute(proposal, "blocked-override", "kiln", live=True)
    assert platform.store.records("commands") == []


async def test_official_mcp_action_idempotency_and_stale_scope_rejection(platform):
    state = platform.connector.disturb("kiln", "heat_load")
    request = Request(incident_id="private-command", snapshot=state)
    proposal = await ReferenceHarness().propose(request, Tools(request, platform.store))
    first = await execute_authorized(
        platform.gateway, proposal, "private-command", "kiln", live=True
    )
    second = await execute_authorized(
        platform.gateway, proposal, "private-command", "kiln", live=True
    )
    assert first == second
    assert first.verification == "pending"
    assert len(platform.store.records("commands")) == 1
    with pytest.raises(Rejected, match="changed"):
        await execute_authorized(platform.gateway, proposal, "stale-command", "kiln", live=True)
    assert len(platform.store.records("commands")) == 1


def test_operations_api_distinguishes_proposal_from_applied_and_estimates():
    with TestClient(create_app(":memory:")) as client:
        initial = client.get("/api/plants/cement-demo/operations").json()
        assert not initial["response"]["applied"]
        assert initial["perceptual"]["trained_model"] is False
        assert initial["reflexive"]["status"] == "regulating"
        client.post("/api/plants/cement-demo/scenarios", json={"scenario": "perception_conflict"})
        result = client.get("/api/plants/cement-demo/operations").json()
        assert result["perceptual"]["conflicts"]
        assert result["perceptual"]["observations"][0]["source"] == "demo"
        assert (
            client.post("/api/plants/cement-demo/resolve", json={"harness": "reference"}).json()[
                "status"
            ]
            == "escalated"
        )
        assert not client.get("/api/plants/cement-demo/operations").json()["response"]["applied"]
        assert client.get("/api/plants/missing/operations").status_code == 404


def test_operations_does_not_claim_past_recovery_after_new_disturbance():
    with TestClient(create_app(":memory:")) as client:
        client.post("/api/plants/cement-demo/scenarios", json={"scenario": "heat_load"})
        assert (
            client.post("/api/plants/cement-demo/resolve", json={"harness": "reference"}).json()[
                "status"
            ]
            == "resolved"
        )
        assert client.get("/api/plants/cement-demo/operations").json()["response"]["verified"]
        client.post("/api/plants/cement-demo/scenarios", json={"scenario": "heat_load"})
        assert not client.get("/api/plants/cement-demo/operations").json()["response"]["verified"]


async def test_custom_perception_provider_reaches_harness_and_is_frozen(platform):
    class Provider:
        def __init__(self):
            self.report = {"status": "normal", "basis": "Test provider", "indicators": []}

        def assess(self, state):
            return self.report

    provider = Provider()
    platform.perception = Perception(platform.store, provider)

    class Probe(ReferenceHarness):
        async def propose(self, request, tools):
            provider.report["basis"] = "Mutated after incident creation"
            assert tools.read_layers()["perceptual"]["basis"] == "Test provider"
            return Proposal(
                plant_id=request.snapshot.spec.id,
                revision=request.snapshot.revision,
                expires_at=now() + timedelta(seconds=60),
                summary="Test integration",
                escalation="Test integration",
            )

    result = await platform.resolve("kiln", Probe())
    assert result.status == "escalated"


async def test_callable_sdk_bridge_uses_official_mcp_and_preserves_budget(platform):
    import inspect

    request = Request(incident_id="sdk-mcp-tools", snapshot=platform.store.plant("kiln"))
    tools = Tools(request, platform.store, budget=2)
    async with tool_functions(tools) as functions:
        functions = {function.__name__: function for function in functions}
        assert inspect.iscoroutinefunction(functions["read_kiln_process"])
        assert "value" in inspect.signature(functions["simulate_kiln_duty"]).parameters
        assert (await functions["read_kiln_process"]())["snapshot"]["spec"]["id"] == "kiln"
        assert isinstance(await functions["discover"](), list)
        denied = None
        try:
            await functions["read_layers"]()
        except RuntimeError as error:
            denied = error
        assert denied is not None
    assert tools.calls == 2
