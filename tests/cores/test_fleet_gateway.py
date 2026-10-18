import pytest

from cognition.control.fleet_gateway import Refused


def test_inspection_finds_what_the_tool_can_see(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=0.8, ramp_ticks=0)
    seen = platform.fleet_gateway.run("kiln", "inspect", "drive", tool="vibration_probe")
    assert seen.tier == "T0" and seen.result["findings"][0]["remedy"] == "bearing_swap"
    healthy = platform.fleet_gateway.run("kiln", "inspect", "feed", tool="gauge_read")
    assert healthy.result["normal"]
    verified = platform.fleet_gateway.run(
        "kiln", "verify", "drive", tool="vibration_probe", expect="kiln_drive_bearing_wear"
    )
    assert verified.result["confirmed"]
    denied = platform.fleet_gateway.run(
        "kiln", "verify", "drive", tool="vibration_probe", expect="coating_ring"
    )
    assert not denied.result["confirmed"]
    fleet = platform.fleet.state("kiln")
    assert all(r.zone == "dock" and r.status == "docked" for r in fleet.robots)
    assert fleet.robots[0].battery < 100


def test_robots_recharge_while_docked(platform):
    platform.fleet_gateway.run("kiln", "inspect", "drive", tool="acoustic")
    low = platform.fleet.state("kiln").robots[0].battery
    for _ in range(3):
        platform.connector.tick("kiln")
    assert platform.fleet.state("kiln").robots[0].battery > low


def test_refusals_are_explained_and_audited(platform):
    run = platform.fleet_gateway.run
    for args, kwargs, match in (
        (("inspect", "warp-core"), {"tool": "visual"}, "Unknown equipment"),
        (("inspect", "drive"), {"tool": "laser"}, "no tool"),
        (("dance", "drive"), {}, "Unknown mission kind"),
        (("unlock", "drive"), {}, "not locked out"),
        (("inspect", "kiln"), {"tool": "vibration_probe"}, "not allowed in a hot zone"),
    ):
        with pytest.raises(Refused, match=match):
            run("kiln", *args, **kwargs)
    state = platform.store.plant("kiln")
    state.interlock = True
    platform.store.put("plants", "kiln", state)
    with pytest.raises(Refused, match="interlock"):
        run("kiln", "inspect", "burner", tool="thermography")
    kinds = [e["kind"] for e in platform.store.events("cores:kiln")]
    assert kinds.count("mission_refused") == 6 and "mission_completed" not in kinds


def test_hot_zone_inspection_with_a_safe_tool_and_low_battery_refusal(platform):
    ok = platform.fleet_gateway.run("kiln", "inspect", "burner", tool="thermography")
    assert ok.zone == "burner-deck" and any("move" in s for s in ok.steps)
    fleet = platform.fleet.state("kiln")
    fleet.robots[0].battery = 12
    platform.store.put("missions", "fleet:kiln", fleet)
    with pytest.raises(Refused, match="battery too low"):
        platform.fleet_gateway.run("kiln", "inspect", "burner", tool="thermography")


def test_carrier_missions_and_patrol_and_lockout_state(platform):
    run = platform.fleet_gateway.run
    assert run("kiln", "sample", "feed", tool="samples").result["delivered_to"] == "lab"
    transport = run("kiln", "transport", "drive", tool="spares")
    assert transport.tier == "T1" and transport.result["to"] == "drive"
    assert run("kiln", "patrol", "kiln").result["zones_clear"]
    run("kiln", "lockout", "drive")
    fleet = platform.fleet.state("kiln")
    assert fleet.lockouts == ["drive"]
    assert next(r for r in fleet.robots if r.kind == "maintainer").zone == "drive-house"
    with pytest.raises(Refused, match="already locked out"):
        run("kiln", "lockout", "drive")
    run("kiln", "unlock", "drive")
    assert platform.fleet.state("kiln").lockouts == []


def test_missions_are_persisted_with_correlation_in_audit(platform):
    mission = platform.fleet_gateway.run("kiln", "patrol", "kiln", correlation="chain-9")
    stored = platform.store.get("missions", mission.id)
    assert mission.id in stored
    event = platform.store.events("cores:kiln")[-1]
    assert event["body"]["correlation_id"] == "chain-9" and event["kind"] == "mission_completed"
    assert platform.store.records("commands") == []
