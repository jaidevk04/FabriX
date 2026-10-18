import asyncio
from datetime import timedelta

import pytest

from cognition.control.gateway import Rejected
from cognition.domain import Request, now
from cognition.harnesses.reference import ReferenceHarness
from cognition.layers.cognitive.tools import Tools
from cognition.runtime.automation import Automation, AutomationConfig


def kinds(platform):
    return [e["kind"] for e in platform.store.events("cores:kiln")]


def test_transitions_are_audited_once_and_linked_to_the_injection(platform):
    fault = platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(6):
        platform.sample("kiln")
    assert kinds(platform).count("core_alert") >= 1
    drive = [
        e
        for e in platform.store.events("cores:kiln")
        if e["kind"] == "core_alert" and e["body"]["alert"] == "learning-drive"
    ]
    assert len(drive) == 1 and drive[0]["body"]["correlation_id"] == fault.id
    assert platform.store.get("core_reports", "kiln:learning")


def test_escalation_publishes_an_observation_that_triggers_review(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(3):
        platform.sample("kiln")
    snapshot = platform.store.plant("kiln")
    report = platform.perception.assess(snapshot)
    sources = {o["source"] for o in report["observations"]}
    assert "signal" in sources
    automation = Automation(platform)
    assert automation.needs_cognitive_review(snapshot)


def test_alerts_clear_after_debounce(platform):
    fault = platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(3):
        platform.sample("kiln")
    platform.faults.clear("kiln", fault.id)
    for _ in range(6):
        platform.sample("kiln")
    assert "core_alert_cleared" in kinds(platform)


def test_monitor_errors_do_not_stop_sampling(platform, monkeypatch):
    monkeypatch.setattr(
        type(platform.cores), "step", lambda *a: (_ for _ in ()).throw(KeyError("x"))
    )
    tick = platform.sample("kiln").tick
    assert platform.store.plant("kiln").tick == tick
    assert "core_runtime_error" in kinds(platform)


async def proposal(platform):
    state = platform.store.plant("kiln")
    request = Request(incident_id="drift", snapshot=state)
    return await ReferenceHarness().propose(request, Tools(request, platform.store))


async def test_gateway_is_strict_by_default_and_live_drift_is_bounded(platform):
    platform.connector.disturb("kiln", "heat_load")
    drifted = await proposal(platform)
    assert drifted.action is not None
    for _ in range(3):
        platform.connector.tick("kiln")
    before = platform.store.plant("kiln")
    with pytest.raises(Rejected, match="changed"):
        platform.gateway.execute(drifted, "strict", "kiln", live=True)
    with pytest.raises(Rejected, match="changed"):
        platform.gateway.execute(drifted, "tight", "kiln", live=True, max_drift=2)
    assert platform.store.records("commands") == [] and platform.store.plant("kiln") == before
    receipt = platform.gateway.execute(drifted, "loose", "kiln", live=True, max_drift=3)
    assert receipt.verification == "pending" and len(platform.store.records("commands")) == 1
    future = drifted.model_copy(update={"revision": before.revision + 5})
    with pytest.raises(Rejected, match="changed"):
        platform.gateway.validate(future, "kiln", max_drift=10)


async def test_drift_still_requires_a_fresh_forecast_and_unexpired_proposal(platform):
    platform.connector.disturb("kiln", "heat_load")
    old = (await proposal(platform)).model_copy(update={"expires_at": now() - timedelta(seconds=1)})
    platform.connector.tick("kiln")
    with pytest.raises(Rejected, match="expired"):
        platform.gateway.validate(old, "kiln", max_drift=10)


async def test_world_keeps_sampling_during_investigations_unless_strict(platform):
    assert platform.world.pause_when_busy is False
    platform.world.start("kiln", 0.2)
    platform.busy.add("kiln")
    before = platform.store.plant("kiln").tick
    await asyncio.sleep(0.7)
    assert platform.store.plant("kiln").tick > before
    platform.busy.discard("kiln")
    await platform.world.stop("kiln")


async def test_live_mode_investigates_a_stuck_actuator_but_never_acts(platform):
    platform.world.start("kiln", 60)
    await asyncio.sleep(0.05)
    state = platform.connector.disturb("kiln", "actuator_stuck")
    automation = Automation(platform)
    automation.enable("kiln", AutomationConfig(mode="autopilot"))
    await automation.step(force=True)
    await automation.tasks["kiln"]
    assert platform.store.incidents()[0].status == "escalated"
    assert platform.store.records("commands") == [] and state.stuck
    await automation.disable("kiln")
    await platform.world.stop("kiln")


async def test_interlock_is_never_investigated_even_in_live_mode(platform):
    platform.world.start("kiln", 60)
    await asyncio.sleep(0.05)
    state = platform.store.plant("kiln")
    state.interlock = True
    platform.store.put("plants", "kiln", state)
    automation = Automation(platform)
    automation.enable("kiln", AutomationConfig(mode="autopilot"))
    await automation.step(force=True)
    assert automation.state("kiln").phase == "attention" and "kiln" not in automation.tasks
    await platform.world.stop("kiln")


async def test_live_investigation_survives_revision_drift_end_to_end(platform):
    platform.connector.disturb("kiln", "heat_load")
    harness = ReferenceHarness()

    class Slow(ReferenceHarness):
        async def propose(self, request, tools):
            result = await harness.propose(request, tools)
            platform.connector.tick("kiln")  # the world moves while the agent thinks
            platform.connector.tick("kiln")
            return result

    incident = await platform.resolve("kiln", Slow(), live=True)
    assert incident.status == "verifying" and len(platform.store.records("commands")) == 1
