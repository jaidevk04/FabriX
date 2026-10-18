"""Cement fault catalogue: simulated, uncalibrated effects on a kiln line."""

from cognition.industries.base import FaultDef

FAULTS = {
    "kiln_drive_bearing_wear": FaultDef(
        "kiln_drive_bearing_wear",
        "Kiln drive bearing wear",
        "drive",
        "Rising vibration and motor current on the kiln drive; mild heat-load drift.",
        1.0,
        {
            "signal": {"drive_vibration_rms": 4.0, "drive_current": 0.18},
            "camera": {"drive_hotspot": 0.4},
            "business": {"availability": -0.06},
        },
        "bearing_swap",
        ramp_ticks=40,
    ),
    "flame_instability": FaultDef(
        "flame_instability",
        "Flame instability",
        "burner",
        "Unsteady flame with draft and oxygen swings; extra fuel burned for the same heat.",
        5.0,
        {
            "signal": {"flame_variance": 12.0, "draft_swing": 35.0, "oxygen_swing": 1.2},
            "camera": {"flame_flicker": 0.7},
            "business": {"fuel_use": 0.12, "throughput": -0.05},
        },
        "burner_retune",
        ramp_ticks=20,
    ),
    "coating_ring": FaultDef(
        "coating_ring",
        "Kiln coating ring",
        "kiln",
        "Ring build-up restricts flow, raising shell temperature and drive current.",
        3.0,
        {
            "signal": {"shell_temp_rise": 45.0, "drive_current": 0.12},
            "camera": {"shell_hotspot": 0.6},
            "business": {"throughput": -0.1},
        },
        "ring_clearing",
        ramp_ticks=60,
    ),
}
