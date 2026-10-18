import pytest
from fastapi.testclient import TestClient

from cognition.api import create_app
from cognition.domain import Industry, PlantSpec
from cognition.industries import CAMERAS, CHANNELS, ZONES, catalogue


def test_definitions_reference_real_equipment_zones_and_effects():
    for industry in Industry:
        zones = {z.id for z in ZONES[industry]}
        assert {"dock", "control"} <= zones
        for zone in ZONES[industry]:
            assert set(zone.next_to) <= zones
        equipment = {e for z in ZONES[industry] for e in z.equipment}
        assert {c.equipment for c in CHANNELS[industry]} - {
            "furnace",
            "reactor",
            "kiln",
        } <= equipment | {
            "burner",
            "drive",
            "feed",
            "rollers",
            "billets",
            "agitator",
            "jacket",
            "pipes",
        }
        signal_keys = {k for c in CHANNELS[industry] for k, _ in c.effects}
        camera_keys = {k for c in CAMERAS[industry] for k in c.detects}
        for fault in catalogue(industry).values():
            assert set(fault.effects.get("signal", {})) <= signal_keys | {"burner_flame_loss"}
        assert camera_keys <= {
            k for f in catalogue(industry).values() for k in f.effects.get("camera", {})
        }


def test_signals_are_deterministic_and_respond_to_faults(platform):
    healthy = {r.channel: r for r in platform.signals.read_all("kiln")}
    assert healthy["drive_current"].status == "normal"
    assert platform.signals.read_one("kiln", "drive_vibration") == healthy["drive_vibration"]
    base = platform.signals.features("kiln", "drive_vibration")
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    platform.faults.inject("kiln", "coating_ring", severity=1.0, ramp_ticks=0)
    platform.connector.tick("kiln")
    worn = platform.signals.features("kiln", "drive_vibration")
    assert worn.rms > base.rms * 1.5 and worn.kurtosis > base.kurtosis
    assert abs(worn.dominant_hz - 25) < 2
    now = {r.channel: r for r in platform.signals.read_all("kiln")}
    assert now["drive_current"].value > healthy["drive_current"].value
    assert now["shell_temperature"].value > healthy["shell_temperature"].value


def test_signal_validation(platform):
    with pytest.raises(KeyError):
        platform.signals.read_one("kiln", "nope")
    with pytest.raises(ValueError, match="waveform"):
        platform.signals.features("kiln", "draft")
    samples, rate = platform.signals.window("kiln", "drive_vibration", 99999)
    assert len(samples) == 1024 and rate == 1024


def test_event_channel_follows_interlock(platform):
    assert platform.signals.read_one("kiln", "interlock").value == 0
    state = platform.store.plant("kiln")
    state.interlock = True
    platform.store.put("plants", "kiln", state)
    assert platform.signals.read_one("kiln", "interlock").value == 1


def test_camera_detections_and_placeholder_frames(platform):
    assert all(c["detections"] == [] for c in platform.cameras.summary("kiln"))
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    platform.connector.tick("kiln")
    found = platform.cameras.detections("kiln", "flame_cam")
    assert found and found[0].label == "flame instability" and not found[0].trained_model
    assert platform.cameras.detections("kiln", "shell_cam") == []
    svg = platform.cameras.frame_svg("kiln", "flame_cam")
    assert svg.startswith("<svg") and "PLACEHOLDER FRAME" in svg and "flame instability" in svg
    with pytest.raises(KeyError):
        platform.cameras.frame_svg("kiln", "nope")


def test_fleet_starts_docked_and_resets_with_plant(platform):
    fleet = platform.fleet.state("kiln")
    assert {r.kind for r in fleet.robots} == {"inspector", "maintainer", "carrier"}
    assert all(r.zone == "dock" and r.status == "docked" and r.battery == 100 for r in fleet.robots)
    platform.platform_reset = platform.reset("kiln")
    assert platform.fleet.state("kiln") == fleet


def test_new_plants_get_their_industry_layout(platform):
    platform.onboard(PlantSpec(id="mill", name="Mill", industry=Industry.STEEL))
    assert "roller-line" in {z.id for z in platform.fleet.state("mill").zones}
    assert {c["id"] for c in platform.cameras.summary("mill")} == {
        "surface_cam",
        "furnace_cam",
        "roller_cam",
    }


def test_sensing_api():
    with TestClient(create_app(":memory:")) as client:
        plant = "steel-demo"
        assert len(client.get(f"/api/plants/{plant}/signals").json()) >= 8
        window = client.get(f"/api/plants/{plant}/signals/roller_vibration/window?n=64").json()
        assert len(window["samples"]) == 64 and window["features"]["rms"] > 0
        assert client.get(f"/api/plants/{plant}/signals/furnace_pressure/window").status_code == 422
        assert client.get(f"/api/plants/{plant}/signals/zzz/window").status_code == 404
        frame = client.get(f"/api/plants/{plant}/cameras/surface_cam/frame.svg")
        assert frame.headers["content-type"].startswith("image/svg+xml")
        assert client.get(f"/api/plants/{plant}/cameras/zzz/frame.svg").status_code == 404
        assert len(client.get(f"/api/plants/{plant}/fleet").json()["robots"]) == 3
        assert client.get("/api/plants/missing/cameras").status_code == 404
