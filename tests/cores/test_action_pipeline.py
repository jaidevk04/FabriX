import asyncio
from datetime import timedelta

import pytest

from cognition.domain import (
    Action,
    ExpectedImpact,
    MaintenanceAction,
    MonitorConfigAction,
    Proposal,
    Request,
    now,
)
from cognition.harnesses.reference import ReferenceHarness
from cognition.layers.cognitive.tools import Tools
from cognition.runtime.automation import Automation, AutomationConfig


def wear(platform, ticks=4):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(ticks):
        platform.sample("kiln")


def kinds(platform):
    return [e["kind"] for e in platform.store.events("cores:kiln")]


def missions(platform):
    return [
        e["body"]["kind"]
        for e in platform.store.events("cores:kiln")
        if e["kind"] == "mission_completed"
    ]


class Fixed(ReferenceHarness):
    def __init__(self, **proposal):
        self.fields = proposal

    async def propose(self, request, tools):
        return Proposal(
            plant_id=request.snapshot.spec.id,
            revision=request.snapshot.revision,
            expires_at=now() + timedelta(seconds=60),
            summary="Fixed proposal",
            **self.fields,
        )


async def test_repair_flows_from_proposal_through_robot_core_to_the_gateway(platform):
    wear(platform)
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    assert incident.status == "verifying"
    assert isinstance(incident.proposal.action, MaintenanceAction)  # type: ignore[union-attr]
    assert incident.proposal.expected_impact is not None  # type: ignore[union-attr]
    order = platform.orders.for_incident(incident.id)
    assert order and order.core == "robot" and order.control == "maintenance"
    assert order.status == "completed" and order.command_ids == [incident.id]
    assert len(platform.store.records("commands")) == 1
    assert platform.faults.events("kiln")[0].cleared_by == "remedy"
    fleet = platform.fleet.state("kiln")
    assert fleet.lockouts == [] and all(r.zone == "dock" for r in fleet.robots)
    assert platform.business.read("kiln")["ledger"].spares["bearing_set"] == 1
    assert missions(platform) == ["verify", "lockout", "unlock"]  # the first is T0 verification
    chain = [k for k in kinds(platform) if k.startswith("order_")]
    assert chain == ["order_created", "order_receipt"]
    events = [e for e in platform.store.events("cores:kiln") if e["kind"].startswith("order_")]
    assert {e["body"]["correlation_id"] for e in events} == {incident.id}


async def test_non_live_repair_resolves_with_a_measured_recovery(platform):
    wear(platform, 1)
    incident = await platform.resolve("kiln", ReferenceHarness())
    assert incident.status == "resolved" and incident.trajectory


async def test_missing_spare_escalates_before_any_robot_moves(platform):
    wear(platform)
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.spares["bearing_set"] = 0
    platform.store.put("business_state", "kiln", ledger)
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    assert incident.status == "escalated" and "lead time 72 h" in incident.reason
    assert "lockout" not in missions(platform) and platform.orders.all() == []


async def test_forced_repair_without_a_spare_is_refused_by_the_gateway_not_the_robot(platform):
    wear(platform)
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.spares["bearing_set"] = 0
    platform.store.put("business_state", "kiln", ledger)
    action = MaintenanceAction(equipment="drive", remedy="bearing_swap")
    incident = await platform.resolve("kiln", Fixed(action=action), live=True)
    assert incident.status == "escalated" and "not in inventory" in incident.reason
    order = platform.orders.for_incident(incident.id)
    assert order and order.status == "refused"
    assert "order_refused" in kinds(platform) and "lockout" not in missions(platform)
    assert platform.store.records("commands") == []


async def test_supervised_repair_waits_for_approval_then_runs(platform):
    wear(platform)
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True, approval_required=True)
    assert incident.status == "awaiting_approval"
    assert platform.store.records("commands") == [] and platform.orders.all() == []
    assert platform.faults.events("kiln")[0].state != "cleared"
    done = await platform.approve(incident.id, accepted=True)
    assert done.status == "verifying" and len(platform.store.records("commands")) == 1
    declined = await platform.resolve(
        "kiln",
        Fixed(action=MaintenanceAction(equipment="drive", remedy="bearing_swap")),
        live=True,
        approval_required=True,
    )
    assert declined.status == "escalated"  # cooldown or no fault left: refused before approval


async def test_low_battery_robot_refuses_and_unlock_is_not_needed(platform):
    wear(platform)
    fleet = platform.fleet.state("kiln")
    next(r for r in fleet.robots if r.kind == "maintainer").battery = 5
    platform.store.put("missions", "fleet:kiln", fleet)
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    assert incident.status == "escalated" and "battery" in incident.reason
    assert platform.orders.for_incident(incident.id).status == "refused"  # type: ignore[union-attr]
    assert platform.store.records("commands") == []


async def test_cancelled_order_is_interrupted_and_cancellation_propagates(platform, monkeypatch):
    wear(platform)

    class Cancelling:
        async def run(self, *args):
            raise asyncio.CancelledError

    monkeypatch.setattr("cognition.runtime.orders.executor_for", lambda core, *a, **k: Cancelling())
    with pytest.raises(asyncio.CancelledError):
        await platform.resolve("kiln", ReferenceHarness(), live=True)
    assert platform.orders.all()[0].status == "interrupted"
    assert platform.store.incidents()[0].status == "interrupted"


async def test_unexpected_executor_error_records_only_the_type(platform, monkeypatch):
    wear(platform)

    class Broken:
        async def run(self, *args):
            raise RuntimeError("secret-token-123")

    monkeypatch.setattr("cognition.runtime.orders.executor_for", lambda core, *a, **k: Broken())
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    assert incident.status == "failed" and "secret-token" not in incident.reason
    assert platform.orders.all()[0].result == "RuntimeError"


async def test_thermal_duty_orders_belong_to_the_optimization_core(platform):
    platform.connector.disturb("kiln", "heat_load")
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    order = platform.orders.for_incident(incident.id)
    assert order and order.core == "optimization" and order.control == "thermal_duty"
    assert isinstance(incident.proposal.action, Action)  # type: ignore[union-attr]


async def test_monitor_config_runs_through_the_owning_core_without_a_plant_command(platform):
    action = MonitorConfigAction(
        core="learning", setting="mask_channel", target="feed_rate", duration_ticks=10
    )
    incident = await platform.resolve("kiln", Fixed(action=action), live=True)
    assert incident.status == "resolved" and "configuration" in incident.reason
    assert platform.config_desk.masked("kiln", "learning") == {"feed_rate"}
    assert platform.orders.for_incident(incident.id).core == "learning"  # type: ignore[union-attr]
    assert platform.store.records("commands") == []
    bad = MonitorConfigAction(
        core="learning", setting="mask_channel", target="nope", duration_ticks=3
    )
    refused = await platform.resolve("kiln", Fixed(action=bad), live=True)
    assert refused.status == "escalated" and "Unknown channel" in refused.reason


async def test_supervised_config_validates_before_asking(platform):
    action = MonitorConfigAction(core="vision", setting="set_sensitivity", value=0.8)
    incident = await platform.resolve(
        "kiln", Fixed(action=action), live=True, approval_required=True
    )
    assert incident.status == "awaiting_approval"
    assert (await platform.approve(incident.id, accepted=True)).status == "resolved"


async def force_followup_case(platform):
    platform.connector.disturb("kiln", "heat_load")
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    platform.connector.tick("kiln", 8)
    return incident


async def test_autopilot_followup_is_a_separate_gateway_command(platform):
    incident = await force_followup_case(platform)
    order = await platform.orders.followup(incident.id, autonomous=True)
    assert order is not None and order.followups == 1
    assert order.command_ids == [incident.id, f"{incident.id}:f1"]
    assert len(platform.store.records("commands")) == 2
    assert "followup_executed" in kinds(platform)


async def test_supervised_followup_waits_for_approval(platform):
    incident = await force_followup_case(platform)
    order = await platform.orders.followup(incident.id, autonomous=False)
    assert order is not None and order.pending_followup is not None
    assert len(platform.store.records("commands")) == 1
    assert await platform.orders.followup(incident.id, autonomous=False) is None
    declined = await platform.orders.decide_followup(order.id, accepted=False)
    assert declined.pending_followup is None and len(platform.store.records("commands")) == 1
    pending = await platform.orders.followup(incident.id, autonomous=False)
    assert pending is not None
    accepted = await platform.orders.decide_followup(pending.id, accepted=True)
    assert accepted.followups == 1 and len(platform.store.records("commands")) == 2
    with pytest.raises(ValueError, match="No follow-up"):
        await platform.orders.decide_followup(order.id, accepted=True)


async def test_no_followup_when_in_band_or_after_the_envelope_expires(platform):
    platform.connector.disturb("kiln", "heat_load")
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    for _ in range(80):
        platform.connector.tick("kiln")
    assert await platform.orders.followup(incident.id, autonomous=True) is None
    order = platform.orders.for_incident(incident.id)
    assert order is not None
    order.expires_at = now() - timedelta(seconds=1)
    platform.orders.save(order)
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    platform.connector.tick("kiln", 8)
    assert await platform.orders.followup(incident.id, autonomous=True) is None
    assert await platform.orders.followup("unknown", autonomous=True) is None


async def test_automation_attempts_followups_while_verifying(platform):
    platform.world.start("kiln", 60)
    await asyncio.sleep(0.05)
    platform.connector.disturb("kiln", "heat_load")
    automation = Automation(platform)
    automation.enable("kiln", AutomationConfig(mode="autopilot", interval_seconds=0.2))
    await automation.step(force=True)
    await automation.tasks["kiln"]
    assert automation.state("kiln").phase == "verifying"
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    for _ in range(25):
        platform.sample("kiln")  # the world clock is parked; advance the world by hand
        await automation.step(force=True)
    assert {"followup_executed", "followup_rejected"} & set(kinds(platform))
    await automation.disable("kiln")
    await platform.world.stop("kiln")


async def test_agent_visible_tools_cannot_reach_orders_or_the_gateway(platform):
    request = Request(incident_id="x", snapshot=platform.store.plant("kiln"))
    names = {fn.__name__ for fn in Tools(request, platform.store, services=platform).functions()}
    assert not {
        n for n in names if "execute" in n or "order" in n or "lockout" in n or "mission" in n
    }
    assert ExpectedImpact(summary="s").metrics == []
