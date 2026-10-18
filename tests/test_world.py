import asyncio

import pytest
from fastapi.testclient import TestClient

from cognition.api import create_app
from cognition.domain import Industry
from cognition.industries import catalogue
from cognition.runtime.automation import Automation, AutomationConfig
from cognition.simulation.thermal import PACKS

GAIN = PACKS[Industry.CEMENT].gain


def test_catalogues_are_complete_and_consistent():
    for industry in Industry:
        entries = catalogue(industry)
        assert len(entries) >= 3
        for key, value in entries.items():
            assert key == value.id and value.remedy and value.effects
            assert set(value.effects) <= {"signal", "camera", "robot", "business"}


def test_fault_ramps_into_the_disturbance_term_and_clears(platform):
    event = platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=4)
    assert event.state == "ramping"
    seen = []
    for _ in range(6):
        seen.append(platform.connector.tick("kiln").disturbance)
    assert seen == sorted(seen)
    assert seen[-1] == pytest.approx(5 * GAIN)
    assert platform.faults.events("kiln")[0].state == "active"
    platform.faults.clear("kiln", event.id)
    assert platform.connector.tick("kiln").disturbance == pytest.approx(0)
    assert platform.faults.events("kiln", include_cleared=False) == []


def test_several_faults_act_together_and_duration_expires(platform):
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    platform.faults.inject("kiln", "coating_ring", severity=0.5, ramp_ticks=0, duration_ticks=3)
    state = platform.connector.tick("kiln")
    assert state.disturbance == pytest.approx((5 + 3 * 0.5) * GAIN)
    for _ in range(4):
        state = platform.connector.tick("kiln")
    assert state.disturbance == pytest.approx(5 * GAIN)
    ring = next(e for e in platform.faults.events("kiln") if e.kind == "coating_ring")
    assert ring.state == "cleared" and ring.cleared_by == "duration"


def test_injection_validation(platform):
    with pytest.raises(ValueError, match="Unknown event kind"):
        platform.faults.inject("kiln", "nonsense")
    platform.faults.inject("kiln", "coating_ring")
    with pytest.raises(ValueError, match="already active"):
        platform.faults.inject("kiln", "coating_ring")
    with pytest.raises(KeyError):
        platform.faults.inject("missing", "coating_ring")


def test_scenarios_compose_with_faults_and_reset_clears_both(platform):
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    platform.connector.tick("kiln")
    state = platform.disturb("kiln", "heat_load")
    assert state.disturbance == pytest.approx(GAIN * 15 + 5 * GAIN)
    state = platform.reset("kiln")
    assert state.disturbance == 0
    assert platform.faults.events("kiln", include_cleared=False) == []
    assert platform.connector.tick("kiln").disturbance == 0


def test_faults_never_write_commands_and_are_audited(platform):
    event = platform.faults.inject("kiln", "flame_instability")
    platform.connector.tick("kiln")
    platform.faults.clear("kiln", event.id)
    assert platform.store.records("commands") == []
    kinds = [e["kind"] for e in platform.store.events("world:kiln")]
    assert kinds[0] == "fault_injected" and "fault_cleared" in kinds
    assert all(e["body"]["correlation_id"] == event.id for e in platform.store.events("world:kiln"))


async def test_world_clock_ticks_independently_and_stops(platform):
    start = platform.store.plant("kiln").tick
    status = platform.world.start("kiln", 0.2)
    assert status.running
    with pytest.raises(ValueError, match="already running"):
        platform.world.start("kiln", 0.2)
    await asyncio.sleep(0.7)
    assert platform.store.plant("kiln").tick > start
    stopped = await platform.world.stop("kiln")
    assert not stopped.running
    frozen = platform.store.plant("kiln").tick
    await asyncio.sleep(0.4)
    assert platform.store.plant("kiln").tick == frozen
    with pytest.raises(ValueError, match="Interval"):
        platform.world.start("kiln", 0.01)


async def test_world_pauses_for_investigation_and_automation_does_not_double_tick(platform):
    platform.world.start("kiln", 60)
    await asyncio.sleep(0.05)
    tick = platform.store.plant("kiln").tick
    automation = Automation(platform)
    automation.enable("kiln", AutomationConfig(mode="observe"))
    await automation.step(force=True)
    assert platform.store.plant("kiln").tick == tick
    await automation.disable("kiln")
    await platform.world.stop("kiln")


def test_world_api_round_trip():
    with TestClient(create_app(":memory:")) as client:
        plant = "steel-demo"
        catalogue_ids = {i["id"] for i in client.get(f"/api/plants/{plant}/fault-catalogue").json()}
        assert "burner_out" in catalogue_ids
        created = client.post(f"/api/plants/{plant}/faults", json={"kind": "burner_out"})
        assert created.status_code == 201
        assert (
            client.post(f"/api/plants/{plant}/faults", json={"kind": "burner_out"}).status_code
            == 422
        )
        assert (
            client.post(f"/api/plants/{plant}/faults", json={"kind": "x_unknown"}).status_code
            == 422
        )
        assert len(client.get(f"/api/plants/{plant}/faults").json()) == 1
        assert client.get(f"/api/plants/{plant}/world").json()["active_events"] == 1
        started = client.post(f"/api/plants/{plant}/world/start", json={"interval_seconds": 0.2})
        assert started.json()["running"]
        assert client.post(f"/api/plants/{plant}/world/start").status_code == 409
        assert not client.post(f"/api/plants/{plant}/world/stop").json()["running"]
        removed = client.delete(f"/api/plants/{plant}/faults/{created.json()['id']}")
        assert removed.json()["state"] == "cleared"
        assert client.delete(f"/api/plants/{plant}/faults/evt-missing").status_code == 404
        assert client.get("/api/plants/missing/faults").status_code == 404
