from datetime import timedelta

import pytest

from cognition.domain import BusRequest, now


def ask(platform, **changes):
    values = dict(
        correlation_id="chain-1",
        plant_id="kiln",
        from_core="vision",
        to_core="learning",
        kind="read_signal_evidence",
        target="drive",
        question="Is the drive vibrating?",
        revision=platform.store.plant("kiln").revision,
        expires_at=now() + timedelta(seconds=30),
    )
    return platform.cores.bus.request(BusRequest(**(values | changes)))


def test_evidence_requests_are_answered_without_raw_waveforms(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    platform.sample("kiln")
    answer = ask(platform)
    assert answer.status == "ok"
    features = answer.evidence["waveform_features"]["drive_vibration"]
    assert features["rms"] > features["baseline_rms"]
    assert "samples" not in str(answer.evidence)
    detections = ask(
        platform, from_core="learning", to_core="vision", kind="read_detections", target="burner"
    )
    assert detections.status == "ok" and detections.evidence["cameras"]
    fleet = ask(platform, from_core="learning", to_core="robot", kind="read_fleet_state")
    assert fleet.status == "ok" and fleet.evidence["zone"]["id"] == "drive-house"


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"from_core": "learning", "to_core": "learning"}, "loop"),
        ({"chain": ["learning"]}, "loop"),
        ({"target": "warp-core"}, "Unknown equipment"),
        ({"expires_at": now() - timedelta(seconds=1)}, "expired"),
        ({"to_core": "robot"}, "does not answer"),
        ({"revision": 10_000}, "future"),
        (
            {"from_core": "learning", "to_core": "vision", "kind": "read_signal_evidence"},
            "does not answer",
        ),
    ],
)
def test_bus_refuses_invalid_requests(platform, changes, reason):
    answer = ask(platform, **changes)
    assert answer.status == "refused" and reason in answer.reason


def test_nobody_can_ask_optimization_or_order_actions(platform):
    from cognition.cores.bus import ALLOWED, ANSWERS

    assert {owner for owner, _ in ANSWERS.values()} == {"learning", "vision", "robot"}
    assert all(kind.startswith("read_") for kinds in ALLOWED.values() for kind in kinds)
    assert ask(platform, to_core="optimization").status == "refused"


def test_bus_is_audited_with_correlation_ids_and_writes_no_commands(platform):
    ask(platform)
    ask(platform, target="warp-core")
    events = platform.store.events("cores:kiln")
    assert [e["kind"] for e in events] == [
        "core_request",
        "core_answer",
        "core_request",
        "core_refused",
    ]
    assert {e["body"]["correlation_id"] for e in events} == {"chain-1"}
    assert platform.store.records("commands") == []
