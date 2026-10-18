import pytest

from cognition.control.gateway import Rejected
from cognition.domain import MonitorConfigAction


def action(**values) -> MonitorConfigAction:
    base = dict(core="learning", setting="mask_channel", target="feed_rate", duration_ticks=5)
    return MonitorConfigAction(**(base | values))


def test_quiet_channel_can_be_masked_for_a_limited_time(platform):
    desk = platform.config_desk
    desk.apply(platform, "kiln", action())
    assert desk.masked("kiln", "learning") == {"feed_rate"}
    for _ in range(6):
        platform.sample("kiln")
    assert desk.masked("kiln", "learning") == set()


def test_channel_with_an_active_alert_cannot_be_masked(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    platform.sample("kiln")
    with pytest.raises(Rejected, match="active alert"):
        platform.config_desk.validate(platform, "kiln", action(target="drive_vibration"))
    assert platform.cores.live("kiln", "learning").alerts


def test_mask_rules_and_sensitivity(platform):
    desk = platform.config_desk
    for bad, match in (
        (action(target="nope"), "Unknown channel"),
        (action(duration_ticks=None), "duration"),
        (action(core="vision"), "Only the learning core"),
        (action(setting="set_sensitivity", value=3.0), "between 0.5 and 1.5"),
    ):
        with pytest.raises(Rejected, match=match):
            desk.validate(platform, "kiln", bad)
    platform.faults.inject("kiln", "flame_instability", severity=0.6, ramp_ticks=0)
    platform.sample("kiln")
    base = platform.cores.live("kiln", "vision").assessment["cameras"]["flame_cam"]["score"]
    desk.apply(
        platform, "kiln", action(core="vision", setting="set_sensitivity", value=0.5, target="")
    )
    low = platform.cores.live("kiln", "vision").assessment["cameras"]["flame_cam"]["score"]
    assert low == pytest.approx(base * 0.5, abs=0.01)
    assert [e["kind"] for e in platform.store.events("cores:kiln")].count(
        "core_config_changed"
    ) == 1
