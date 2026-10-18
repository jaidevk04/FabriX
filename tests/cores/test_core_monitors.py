from pathlib import Path

from cognition.cores.learning.reference import diagnose
from cognition.cores.registry import SPECS


def sample(platform, ticks=3, plant="kiln"):
    for _ in range(ticks):
        platform.sample(plant)


def test_healthy_plant_has_no_alerts_and_every_core_reports(platform):
    sample(platform, 2)
    for name in SPECS:
        report = platform.cores.live("kiln", name)
        assert report.status == "normal" and report.alerts == [] and not report.trained_model
        assert platform.cores.live("kiln", name, reference=True).source == "reference"


def test_learning_detects_bearing_wear_and_reference_names_the_signature(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    sample(platform)
    report = platform.cores.live("kiln", "learning")
    alert = report.alerts[0]
    assert alert.equipment == "drive" and alert.level == "escalate" and alert.confidence >= 0.7
    assert any("drive_vibration" in line for line in alert.evidence)
    top = diagnose(platform, "kiln")[0]
    assert top["fault"] == "kiln_drive_bearing_wear" and top["remedy"] == "bearing_swap"
    reference = platform.cores.live("kiln", "learning", reference=True)
    assert reference.assessment["prognosis"]["drive"]["stage"] == "advanced"
    assert "kiln_drive_bearing_wear" in reference.summary


def test_learning_scores_grow_with_severity(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=0.3, ramp_ticks=0)
    sample(platform)
    mild = platform.cores.live("kiln", "learning").assessment["equipment"]["drive"]["score"]
    platform.faults.clear("kiln", platform.faults.events("kiln")[0].id)
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    sample(platform)
    severe = platform.cores.live("kiln", "learning").assessment["equipment"]["drive"]["score"]
    assert 0.25 <= mild < severe


def test_vision_detects_flame_instability_and_correlates(platform):
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    sample(platform)
    report = platform.cores.live("kiln", "vision")
    assert report.alerts[0].equipment == "burner" and report.alerts[0].core == "vision"
    reference = platform.cores.live("kiln", "vision", reference=True)
    assert reference.assessment["candidates"][0]["fault"] == "flame_instability"


def test_robot_recommends_inspection_from_peer_evidence_and_never_escalates(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    sample(platform)
    robot = platform.cores.live("kiln", "robot")
    assert [a.equipment for a in robot.alerts] == ["drive"]
    assert all(a.level != "escalate" for a in robot.alerts)
    plan = platform.cores.live("kiln", "robot", reference=True).assessment["plan"]
    assert plan[0]["zone"] == "drive-house" and plan[0]["robot"] == "Scout-1"


def test_robot_flags_fleet_faults_and_low_battery(platform):
    fleet = platform.fleet.state("kiln")
    fleet.robots[0].status = "fault"
    fleet.robots[1].battery = 10
    platform.store.put("missions", "fleet:kiln", fleet)
    ids = {a.id for a in platform.cores.live("kiln", "robot").alerts}
    assert ids == {"robot-fault-inspector", "robot-battery-maintainer"}


def test_monitors_and_analysers_never_read_injected_event_labels():
    import cognition

    root = Path(cognition.__file__).parent / "cores"
    files = [*root.glob("*/monitor.py"), *root.glob("*/reference.py"), root / "_evidence.py"]
    assert len(files) >= 9
    for file in files:
        text = file.read_text()
        assert ".faults" not in text and "world_events" not in text, file.name
