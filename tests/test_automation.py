import asyncio

import pytest
from fastapi.testclient import TestClient

from cognition.api import create_app
from cognition.capabilities.registry import default_manifest
from cognition.domain import Incident, Receipt
from cognition.harnesses.reference import ReferenceHarness
from cognition.runtime.automation import Automation, AutomationConfig


async def settle(runtime):
    await asyncio.gather(*runtime.tasks.values())


async def test_autopilot_dispatch_then_fresh_measurement_verification(platform):
    runtime = Automation(platform)
    state = platform.connector.disturb("kiln", "heat_load")
    runtime.enable("kiln", AutomationConfig(mode="autopilot", cooldown_seconds=0))
    await runtime.step(force=True)
    await settle(runtime)
    run = runtime.state("kiln")
    assert run.phase == "verifying"
    incident = Incident.model_validate_json(platform.store.get("incidents", run.incident_id))
    assert incident.status == "verifying"
    assert len(incident.trajectory) == 1
    assert platform.store.plant("kiln").tick == state.tick + 1
    command_count = platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
    for _ in range(180):
        await runtime.step(force=True)
        if runtime.state("kiln").phase == "cooldown":
            break
    incident = Incident.model_validate_json(platform.store.get("incidents", run.incident_id))
    assert incident.status == "resolved"
    assert "fresh" in incident.reason
    receipt = Receipt.model_validate_json(platform.store.get("commands", incident.id))
    assert receipt.recovered and receipt.verification == "completed"
    assert (
        platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
        == command_count
        == 1
    )
    samples = [
        event for event in platform.store.events(incident.id) if event["kind"] == "measurement"
    ]
    assert len(samples) >= 10
    assert len({event["body"]["revision"] for event in samples}) == len(samples)
    await runtime.disable("kiln")


async def test_supervised_approval_applies_nothing_until_accepted(platform):
    runtime = Automation(platform)
    platform.connector.disturb("kiln", "heat_load")
    runtime.enable("kiln", AutomationConfig(mode="supervised"))
    await runtime.step(force=True)
    await settle(runtime)
    run = runtime.state("kiln")
    assert run.phase == "awaiting_approval"
    frozen = platform.store.plant("kiln")
    await runtime.step(force=True)
    assert platform.store.plant("kiln") == frozen
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
    result = await platform.approve(run.incident_id, accepted=True)
    assert result.status == "verifying"
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 1
    with pytest.raises(ValueError, match="not awaiting"):
        await platform.approve(run.incident_id, accepted=True)
    await runtime.disable("kiln")


async def test_failure_stops_automatic_retries(platform):
    class Failure(ReferenceHarness):
        async def propose(self, request, tools):
            raise RuntimeError("provider failed")

    runtime = Automation(platform)
    runtime.harness_factory = lambda name: Failure()
    platform.connector.disturb("kiln", "heat_load")
    runtime.enable("kiln", AutomationConfig(mode="autopilot"))
    await runtime.step(force=True)
    await settle(runtime)
    assert runtime.state("kiln").phase == "attention"
    assert not runtime.state("kiln").enabled
    for _ in range(10):
        await runtime.step(force=True)
    assert len(platform.store.incidents()) == 1


async def test_observe_only_advances_without_agent_and_restart_disables(platform):
    runtime = Automation(platform)
    runtime.enable("kiln", AutomationConfig(mode="observe"))
    before = platform.store.plant("kiln")
    await runtime.step(force=True)
    after = platform.store.plant("kiln")
    assert after.tick == before.tick + 1
    assert after.sampled_at > before.sampled_at
    assert platform.store.incidents() == []
    restored = Automation(platform)
    assert not restored.state("kiln").enabled
    assert restored.state("kiln").phase == "attention"


def test_manifest_registry_and_automation_api():
    with TestClient(create_app(":memory:")) as client:
        assert len(client.get("/api/manifests").json()) == 3
        assert len(client.get("/api/registry").json()) >= 24
        assert all(not state["enabled"] for state in client.get("/api/automation").json())
        result = client.post("/api/plants/cement-demo/automation", json={"mode": "observe"})
        assert result.status_code == 200 and result.json()["enabled"]
        assert client.post("/api/plants/cement-demo/resolve", json={}).status_code == 409
        assert client.delete("/api/plants/cement-demo/automation").status_code == 200
        assert client.get("/api/automation").json()[0]["enabled"] is False


def test_manifest_rejects_unimplemented_control_or_signal(platform):
    manifest = default_manifest(platform.store.plant("kiln").spec).model_dump()
    manifest["signals"][0]["source"] = "plc.unreviewed_tag"
    from cognition.capabilities.registry import Manifest

    with pytest.raises(ValueError, match="not implemented"):
        Manifest.model_validate(manifest)


def test_manifest_units_and_estimate_basis_are_checked(platform):
    from cognition.capabilities.registry import Manifest

    manifest = default_manifest(platform.store.plant("kiln").spec).model_dump()
    manifest["signals"][0]["unit"] = "bar"
    with pytest.raises(ValueError, match="unit"):
        Manifest.model_validate(manifest)
    manifest = default_manifest(platform.store.plant("kiln").spec).model_dump()
    manifest["signals"][4]["basis"] = "simulated"
    with pytest.raises(ValueError, match="estimates"):
        Manifest.model_validate(manifest)


async def test_stop_before_task_starts_and_cancel_pending_approval(platform):
    runtime = Automation(platform)
    platform.connector.disturb("kiln", "heat_load")
    runtime.enable("kiln", AutomationConfig(mode="autopilot"))
    await runtime.step(force=True)
    await runtime.disable("kiln")
    assert not runtime.state("kiln").enabled
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
    runtime.enable("kiln", AutomationConfig(mode="supervised"))
    await runtime.step(force=True)
    await settle(runtime)
    incident_id = runtime.state("kiln").incident_id
    await runtime.disable("kiln")
    assert (
        Incident.model_validate_json(platform.store.get("incidents", incident_id)).status
        == "interrupted"
    )
    with pytest.raises(ValueError):
        await platform.approve(incident_id, accepted=True)


async def test_bad_measurement_escalates_after_dispatch(platform):
    runtime = Automation(platform)
    platform.connector.disturb("kiln", "heat_load")
    runtime.enable("kiln", AutomationConfig(mode="autopilot"))
    await runtime.step(force=True)
    await settle(runtime)
    platform.connector.disturb("kiln", "sensor_fault")
    await runtime.step(force=True)
    run = runtime.state("kiln")
    assert run.phase == "attention" and not run.enabled
    assert (
        Incident.model_validate_json(platform.store.get("incidents", run.incident_id)).status
        == "escalated"
    )


async def test_simulator_pauses_during_frozen_snapshot_investigation(platform):
    entered, release = asyncio.Event(), asyncio.Event()

    class Waiting(ReferenceHarness):
        async def propose(self, request, tools):
            entered.set()
            await release.wait()
            return await super().propose(request, tools)

    runtime = Automation(platform)
    runtime.harness_factory = lambda name: Waiting()
    platform.connector.disturb("kiln", "heat_load")
    runtime.enable("kiln", AutomationConfig(mode="autopilot"))
    await runtime.step(force=True)
    await asyncio.wait_for(entered.wait(), 1)
    snapshot = platform.store.plant("kiln")
    for _ in range(10):
        await runtime.step(force=True)
    assert platform.store.plant("kiln") == snapshot
    release.set()
    await settle(runtime)
    assert runtime.state("kiln").phase == "verifying"
    await runtime.disable("kiln")


async def test_expired_approval_never_applies_command(platform):
    from datetime import timedelta

    from cognition.domain import now

    runtime = Automation(platform)
    platform.connector.disturb("kiln", "heat_load")
    runtime.enable("kiln", AutomationConfig(mode="supervised"))
    await runtime.step(force=True)
    await settle(runtime)
    incident_id = runtime.state("kiln").incident_id
    incident = Incident.model_validate_json(platform.store.get("incidents", incident_id))
    incident.proposal.expires_at = now() - timedelta(seconds=1)
    platform.store.put("incidents", incident_id, incident)
    await runtime.step(force=True)
    assert runtime.state("kiln").phase == "attention"
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
    assert (
        "expired"
        in Incident.model_validate_json(platform.store.get("incidents", incident_id)).reason
    )
