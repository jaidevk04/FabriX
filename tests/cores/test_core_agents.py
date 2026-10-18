import asyncio
from datetime import timedelta

import pytest

from cognition.agentkit.evals import scripted_model
from cognition.cores.runs import CoreBusy, RunStopped
from cognition.domain import (
    Action,
    MaintenanceAction,
    MonitorConfigAction,
    Proposal,
    now,
)
from cognition.harnesses.errors import HarnessFailure
from cognition.harnesses.reference import ReferenceHarness
from cognition.runtime.automation import Automation, AutomationConfig

FINDING = {
    "summary": "Drive vibration is high.",
    "status": "alert",
    "confidence": 0.8,
    "findings": [{"statement": "Bearing signature", "equipment": "drive", "evidence": ["rms 5.8"]}],
    "next_checks": ["Verify in person"],
}
EXECUTED = {"decision": "executed", "reason": ""}


def arm(platform, models):
    """Turn agents on with scripted models: models is {(core, mode): scripted_model}."""
    platform.core_agents.override = True
    platform.core_agents.model_factory = lambda core, mode: models[(core, mode)]


def kinds(platform):
    return [e["kind"] for e in platform.store.events("cores:kiln")]


class Fixed(ReferenceHarness):
    def __init__(self, action):
        self.action = action

    async def propose(self, request, tools):
        return Proposal(
            plant_id=request.snapshot.spec.id,
            revision=request.snapshot.revision,
            expires_at=now() + timedelta(seconds=60),
            summary="Fixed proposal",
            action=self.action,
        )


def wear(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(4):
        platform.sample("kiln")


REPAIR = MaintenanceAction(equipment="drive", remedy="bearing_swap")


async def test_analysis_agent_calls_tools_and_returns_a_structured_report(platform):
    wear(platform)
    model = scripted_model(
        [
            ("learning_read_encoder_scores", {}),
            ("learning_read_features", {"channel": "drive_vibration"}),
            ("load_skill", {"name": "fault-diagnosis"}),
        ],
        FINDING,
    )
    arm(platform, {("learning", "analysis"): model})
    report = await platform.cores.analyse("kiln", "learning", "Why is the drive alerting?")
    assert report.source == "agent" and report.summary == FINDING["summary"]
    assert report.model == "scripted-offline" and not report.trained_model and not report.degraded
    assert report.alerts and report.assessment["findings"][0]["equipment"] == "drive"
    assert model.seen == [
        "learning_read_encoder_scores",
        "learning_read_features",
        "load_skill",
        "set_model_response",
    ]
    log = kinds(platform)
    assert "core_run_started" in log and "core_run_completed" in log
    called = [
        e["body"]["tool"]
        for e in platform.store.events("cores:kiln")
        if e["kind"] == "core_tool_called"
    ]
    assert called == ["learning_read_encoder_scores", "learning_read_features"]
    assert platform.store.records("commands") == []


async def test_disabled_or_unavailable_agents_fall_back_to_reference_with_a_clear_flag(
    platform, monkeypatch
):
    off = await platform.cores.analyse("kiln", "learning", "q")
    assert off.source == "reference" and not off.degraded
    for name in ("GEMINI_MODEL", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    platform.core_agents.override = True
    on = await platform.cores.analyse("kiln", "learning", "q")
    assert on.source == "reference" and on.degraded
    assert "GEMINI_MODEL" in on.assessment["degraded_reason"]
    status = platform.core_agents.status()
    assert status["enabled"] and not status["available"] and status["degraded"]


async def test_agent_failure_falls_back_for_analysis_and_never_records_error_text(platform):
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("secret-token-123")

    platform.core_agents.override = True
    platform.core_agents.model_factory = lambda core, mode: (_ for _ in ()).throw(
        RuntimeError("secret-token-123")
    )
    report = await platform.cores.analyse("kiln", "learning", "q")
    assert report.source == "reference" and report.degraded
    assert "RuntimeError" in report.assessment["degraded_reason"]
    assert "secret-token" not in str(platform.store.events("cores:kiln"))
    assert "secret-token" not in str(report.model_dump())
    assert "core_run_failed" in kinds(platform)


async def test_one_run_per_core_per_plant(platform):
    arm(platform, {("learning", "analysis"): scripted_model([], FINDING, delay=0.4)})
    first = asyncio.create_task(platform.cores.analyse("kiln", "learning", "q1"))
    await asyncio.sleep(0.1)
    with pytest.raises(CoreBusy):
        await platform.core_agents.analyse("kiln", "learning", "q2")
    # ask_core still gets a prompt answer: the deterministic analyser, flagged as degraded.
    second = await platform.cores.analyse("kiln", "learning", "q2")
    assert second.source != "agent" and second.degraded
    assert "busy" in second.assessment["degraded_reason"]
    assert (await first).source == "agent"
    assert ("kiln", "learning") not in platform.core_agents.active


async def test_stop_terminates_a_run_records_interrupted_and_ask_core_reports_it(platform):
    from cognition.domain import Request
    from cognition.layers.cognitive.tools import Tools

    arm(platform, {("learning", "analysis"): scripted_model([], FINDING, delay=5)})
    request = Request(incident_id="stop-me", snapshot=platform.store.plant("kiln"))
    tools = Tools(request, platform.store, services=platform)
    task = asyncio.create_task(tools.ask_core("learning", "slow question"))
    await asyncio.sleep(0.2)
    (run,) = platform.core_agents.runs("kiln")
    assert run.status == "running"
    assert platform.core_agents.stop("kiln", "learning").id == run.id
    answer = await task
    assert answer["status"] == "error" and "stopped" in answer["error"]
    assert platform.core_agents.runs("kiln")[0].status == "interrupted"
    assert "core_run_interrupted" in kinds(platform)
    assert platform.core_agents.stop("kiln", "learning") is None  # nothing left to stop


async def test_stop_raises_run_stopped_for_direct_callers(platform):
    arm(platform, {("vision", "analysis"): scripted_model([], FINDING, delay=5)})
    task = asyncio.create_task(platform.core_agents.analyse("kiln", "vision", "q"))
    await asyncio.sleep(0.2)
    assert len(platform.core_agents.stop_all("kiln")) == 1
    with pytest.raises(RunStopped):
        await task


async def test_cancelling_the_caller_is_not_mistaken_for_stop(platform):
    arm(platform, {("vision", "analysis"): scripted_model([], FINDING, delay=5)})
    task = asyncio.create_task(platform.core_agents.analyse("kiln", "vision", "q"))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert not isinstance(caught.value, RunStopped)
    assert platform.core_agents.runs("kiln")[0].status == "interrupted"
    assert platform.core_agents.active == {}


async def test_wall_clock_ceiling_ends_a_run_and_zero_turns_it_off(platform, monkeypatch):
    monkeypatch.setenv("COGNITION_CORE_RUN_SECONDS", "0.2")
    arm(platform, {("learning", "analysis"): scripted_model([], FINDING, delay=3)})
    with pytest.raises(HarnessFailure, match="time ceiling"):
        await platform.core_agents.analyse("kiln", "learning", "q")
    assert platform.core_agents.runs("kiln")[0].status == "timeout"
    report = await platform.cores.analyse("kiln", "learning", "q")  # falls back, flagged
    assert report.source == "reference" and report.degraded
    monkeypatch.setenv("COGNITION_CORE_RUN_SECONDS", "0")
    assert platform.core_agents.ceiling() == 0


async def test_alerts_wake_the_agent_and_store_its_report(platform):
    arm(
        platform,
        {(c, "analysis"): scripted_model([], FINDING) for c in ("learning", "vision", "robot")},
    )
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(3):
        platform.sample("kiln")
    await asyncio.gather(*platform.core_agents.background)
    stored = platform.store.get("core_reports", "kiln:learning")
    assert '"source":"agent"' in stored


async def test_main_harness_ask_core_gets_the_agent_answer(platform):
    from cognition.domain import Request
    from cognition.layers.cognitive.tools import Tools

    wear(platform)
    arm(platform, {("learning", "analysis"): scripted_model([], FINDING)})
    tools = Tools(
        Request(incident_id="ask", snapshot=platform.store.plant("kiln")),
        platform.store,
        services=platform,
    )
    answer = await tools.ask_core("learning", "q", "detailed")
    assert answer["stamp"]["source"] == "agent" and answer["assessment"]["findings"]


# Orders carried out by the owning core's agent.


async def test_robot_agent_executes_a_repair_order_through_its_bound_tool(platform):
    wear(platform)
    model = scripted_model(
        [
            ("robot_read_fleet", {}),
            ("robot_read_zones", {"zone": "drive-house"}),
            ("robot_execute_order", {}),
        ],
        EXECUTED,
    )
    arm(platform, {("robot", "order"): model})
    incident = await platform.resolve("kiln", Fixed(REPAIR), live=True)
    assert incident.status == "verifying"
    order = platform.orders.for_incident(incident.id)
    assert order and order.core == "robot" and order.status == "completed"
    assert order.command_ids == [incident.id] and len(platform.store.records("commands")) == 1
    assert platform.faults.events("kiln")[0].cleared_by == "remedy"
    assert platform.fleet.state("kiln").lockouts == []
    assert "core_run_completed" in kinds(platform) and "core_degraded" not in kinds(platform)


async def test_agent_may_refuse_and_the_incident_escalates_with_its_reason(platform):
    wear(platform)
    refusal = {"decision": "refused", "reason": "maintainer battery looks too low for the shift"}
    arm(platform, {("robot", "order"): scripted_model([("robot_read_fleet", {})], refusal)})
    incident = await platform.resolve("kiln", Fixed(REPAIR), live=True)
    assert incident.status == "escalated" and "battery looks too low" in incident.reason
    assert platform.orders.for_incident(incident.id).status == "refused"  # type: ignore[union-attr]
    assert platform.store.records("commands") == []
    assert platform.faults.events("kiln")[0].state != "cleared"


async def test_an_agent_that_says_executed_without_acting_is_refused(platform):
    wear(platform)
    arm(platform, {("robot", "order"): scripted_model([], EXECUTED)})
    incident = await platform.resolve("kiln", Fixed(REPAIR), live=True)
    assert incident.status == "escalated" and "did not execute" in incident.reason
    assert platform.store.records("commands") == []


async def test_the_bound_tool_runs_once_even_if_the_agent_calls_it_twice(platform):
    wear(platform)
    model = scripted_model([("robot_execute_order", {}), ("robot_execute_order", {})], EXECUTED)
    arm(platform, {("robot", "order"): model})
    incident = await platform.resolve("kiln", Fixed(REPAIR), live=True)
    assert incident.status == "verifying" and len(platform.store.records("commands")) == 1
    assert platform.business.read("kiln")["ledger"].spares["bearing_set"] == 1


async def test_gateway_rejection_inside_the_agent_run_wins_over_the_agents_words(platform):
    wear(platform)
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.spares["bearing_set"] = 0
    platform.store.put("business_state", "kiln", ledger)
    arm(platform, {("robot", "order"): scripted_model([("robot_execute_order", {})], EXECUTED)})
    incident = await platform.resolve("kiln", Fixed(REPAIR), live=True)
    assert incident.status == "escalated" and "not in inventory" in incident.reason
    assert platform.store.records("commands") == []
    assert "lockout" not in [
        e["body"]["kind"]
        for e in platform.store.events("cores:kiln")
        if e["kind"] == "mission_completed"
    ]


async def test_a_failed_agent_order_run_fails_the_incident_without_a_silent_fallback(platform):
    wear(platform)
    platform.core_agents.override = True
    platform.core_agents.model_factory = lambda core, mode: (_ for _ in ()).throw(
        RuntimeError("secret-token-123")
    )
    incident = await platform.resolve("kiln", Fixed(REPAIR), live=True)
    assert incident.status == "failed" and "secret-token" not in incident.reason
    assert platform.orders.all()[0].result == "RuntimeError"
    assert platform.store.records("commands") == []  # the reference executor did not step in


async def test_stop_during_an_order_interrupts_the_incident_and_the_order(platform):
    wear(platform)
    arm(
        platform,
        {("robot", "order"): scripted_model([("robot_execute_order", {})], EXECUTED, delay=5)},
    )
    task = asyncio.create_task(platform.resolve("kiln", Fixed(REPAIR), live=True))
    for _ in range(50):
        await asyncio.sleep(0.05)
        if ("kiln", "robot") in platform.core_agents.active:
            break
    platform.core_agents.stop("kiln", "robot")
    incident = await task
    assert incident.status == "interrupted" and "stopped by the operator" in incident.reason
    assert platform.orders.all()[0].status == "interrupted"
    assert platform.store.records("commands") == []
    assert "kiln" not in platform.busy


async def test_optimization_and_config_orders_use_their_own_agents(platform):
    platform.connector.disturb("kiln", "heat_load")
    duty = scripted_model(
        [("optimization_read_problem_context", {}), ("optimization_execute_order", {})], EXECUTED
    )
    config = scripted_model([("learning_apply_monitor_config", {})], EXECUTED)
    arm(platform, {("optimization", "order"): duty, ("learning", "order"): config})
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    assert incident.status == "verifying" and isinstance(incident.proposal.action, Action)  # type: ignore[union-attr]
    assert platform.orders.for_incident(incident.id).core == "optimization"  # type: ignore[union-attr]
    mask = MonitorConfigAction(
        core="learning", setting="mask_channel", target="feed_rate", duration_ticks=9
    )
    done = await platform.resolve("kiln", Fixed(mask), live=True)
    assert done.status == "resolved"
    assert platform.config_desk.masked("kiln", "learning") == {"feed_rate"}


async def test_stopping_automation_stops_core_runs_and_recalls_robots(platform):
    arm(platform, {("vision", "analysis"): scripted_model([], FINDING, delay=5)})
    platform.fleet_gateway.run("kiln", "lockout", "drive")
    run = asyncio.create_task(platform.core_agents.analyse("kiln", "vision", "q"))
    await asyncio.sleep(0.2)
    automation = Automation(platform)
    automation.enable("kiln", AutomationConfig(mode="observe"))
    await automation.disable("kiln")
    with pytest.raises(RunStopped):
        await run
    fleet = platform.fleet.state("kiln")
    assert fleet.lockouts == [] and all(
        r.zone == "dock" and r.status == "docked" for r in fleet.robots
    )
    assert "fleet_recalled" in kinds(platform)
