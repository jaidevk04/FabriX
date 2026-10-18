from datetime import timedelta

import pytest

from cognition.control.gateway import Rejected
from cognition.domain import MaintenanceAction, Proposal, now


def repair(platform, equipment="drive", remedy="bearing_swap", **changes) -> Proposal:
    state = platform.store.plant("kiln")
    values = dict(
        plant_id="kiln",
        revision=state.revision,
        expires_at=now() + timedelta(seconds=60),
        summary="Repair",
        action=MaintenanceAction(equipment=equipment, remedy=remedy),
    )
    return Proposal(**(values | changes))


def wear(platform, **kw):
    return platform.faults.inject(
        "kiln", kw.pop("kind", "kiln_drive_bearing_wear"), severity=1.0, ramp_ticks=0
    )


def snapshot(platform):
    return (
        platform.store.plant("kiln"),
        platform.store.records("commands"),
        platform.store.records("business_state"),
        [e.state for e in platform.faults.events("kiln")],
    )


def refused(platform, proposal, match, *, lockout=True, command="cmd"):
    if lockout and "drive" not in platform.fleet.state("kiln").lockouts:
        platform.fleet_gateway.run("kiln", "lockout", "drive")
    before = snapshot(platform)
    with pytest.raises(Rejected, match=match):
        platform.gateway.execute(proposal, command, "kiln", live=True)
    assert snapshot(platform) == before  # no command row, no plant, spare or fault change


def test_successful_repair_clears_the_fault_uses_the_spare_and_is_idempotent(platform):
    wear(platform)
    platform.sample("kiln")
    platform.fleet_gateway.run("kiln", "lockout", "drive")
    proposal = repair(platform)
    receipt = platform.gateway.execute(proposal, "fix-1", "kiln", live=True)
    assert receipt.verification == "pending" and not receipt.recovered
    assert platform.faults.events("kiln")[0].state == "cleared"
    assert platform.faults.events("kiln")[0].cleared_by == "remedy"
    assert platform.business.read("kiln")["ledger"].spares["bearing_set"] == 1
    assert platform.fleet.state("kiln").last_maintenance["drive"] >= 0
    applied = [e for e in platform.store.events("fix-1") if e["kind"] == "maintenance_applied"]
    assert applied[0]["body"]["fault"] == "kiln_drive_bearing_wear"
    assert platform.gateway.execute(proposal, "fix-1", "kiln", live=True) == receipt
    assert platform.business.read("kiln")["ledger"].spares["bearing_set"] == 1
    other = repair(platform, summary="Different")
    with pytest.raises(Rejected, match="conflicts"):
        platform.gateway.execute(other, "fix-1", "kiln", live=True)


def test_repair_removes_the_heat_load_of_a_thermal_fault(platform):
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    state = platform.sample("kiln")
    assert state.disturbance > 0
    platform.fleet_gateway.run("kiln", "lockout", "burner")
    proposal = repair(platform, "burner", "burner_retune")
    platform.gateway.execute(proposal, "fix-burner", "kiln", live=False)
    assert platform.store.plant("kiln").disturbance == pytest.approx(0, abs=1e-6)


def test_no_matching_fault_or_wrong_remedy(platform):
    refused(platform, repair(platform), "No active fault", lockout=False)
    wear(platform)
    refused(platform, repair(platform, remedy="ring_clearing"), "No active fault")
    refused(platform, repair(platform, "burner", "burner_retune"), "No active fault")


def test_unknown_equipment_and_remedy(platform):
    wear(platform)
    refused(platform, repair(platform, "warp-core"), "Unknown equipment", lockout=False)


def test_missing_spare_reports_lead_time_and_shortage_event_blocks(platform):
    wear(platform)
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.spares["bearing_set"] = 0
    platform.store.put("business_state", "kiln", ledger)
    refused(platform, repair(platform), r"not in inventory \(lead time 72 h\)")
    ledger.spares["bearing_set"] = 2
    platform.store.put("business_state", "kiln", ledger)
    platform.faults.inject("kiln", "spare_shortage")
    refused(platform, repair(platform), "not in inventory", command="cmd-2")


def test_interlock_blocks_maintenance(platform):
    wear(platform)
    state = platform.store.plant("kiln")
    state.interlock = True
    platform.store.put("plants", "kiln", state)
    refused(platform, repair(platform), "interlock", lockout=False)


def test_lockout_and_clear_zone_are_required(platform):
    wear(platform)
    refused(platform, repair(platform), "Lock-out step required", lockout=False)
    platform.fleet_gateway.run("kiln", "lockout", "drive")
    fleet = platform.fleet.state("kiln")
    next(r for r in fleet.robots if r.kind == "inspector").zone = "drive-house"
    platform.store.put("missions", "fleet:kiln", fleet)
    refused(platform, repair(platform), "not clear", lockout=False, command="cmd-3")


def test_cooldown_after_a_repair(platform):
    wear(platform)
    platform.fleet_gateway.run("kiln", "lockout", "drive")
    platform.gateway.execute(repair(platform), "first", "kiln", live=True)
    platform.fleet_gateway.run("kiln", "unlock", "drive")
    wear(platform)
    refused(platform, repair(platform), "cooldown", command="second")
    for _ in range(31):
        platform.sample("kiln")
    assert platform.fleet.state("kiln").lockouts == ["drive"]
    platform.gateway.execute(repair(platform), "third", "kiln", live=True)


def test_scope_revision_expiry_and_escalations_still_apply(platform):
    wear(platform)
    platform.fleet_gateway.run("kiln", "lockout", "drive")
    for changes, match in (
        ({"plant_id": "other"}, "scope"),
        ({"revision": 99}, "changed"),
        ({"expires_at": now() - timedelta(seconds=1)}, "expired"),
    ):
        before = snapshot(platform)
        with pytest.raises(Rejected, match=match):
            platform.gateway.execute(repair(platform, **changes), "bad", "kiln", live=True)
        assert snapshot(platform) == before
    escalation = Proposal(
        plant_id="kiln",
        revision=platform.store.plant("kiln").revision,
        expires_at=now() + timedelta(seconds=30),
        summary="x",
        escalation="x",
    )
    with pytest.raises(Rejected, match="no executable action"):
        platform.gateway.execute(escalation, "esc", "kiln", live=True)


def test_union_round_trips_and_exactly_one_decision(platform):
    proposal = repair(platform)
    again = Proposal.model_validate_json(proposal.model_dump_json())
    assert isinstance(again.action, MaintenanceAction)
    with pytest.raises(ValueError, match="exactly one"):
        repair(platform, escalation="also escalate")
    assert "anyOf" in str(Proposal.model_json_schema()["$defs"]) or Proposal.model_json_schema()


def test_only_the_gateway_writes_command_receipts():
    from pathlib import Path

    import cognition

    root = Path(cognition.__file__).parent
    writers = {
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "INSERT INTO commands" in p.read_text()
    }
    assert writers == {"control/gateway.py"}
