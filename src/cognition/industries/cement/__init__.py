"""Kiln process definitions and illustrative signal model."""

from cognition.industries.base import Definition, IndustryProfile, ThermalParameters

PROFILE = IndustryProfile(
    id="cement",
    name="Kiln process",
    thermal=ThermalParameters(1450, 12, 20, 250, "Kiln thermal surrogate"),
    read_tool="read_kiln_process",
    simulate_tool="simulate_kiln_duty",
    skill="cement-operations",
)
DEFINITIONS = [
    Definition(
        "draft",
        "Kiln draft",
        "Pa",
        -160,
        0,
        -110,
        -55,
        "dial",
        "Illustrative negative draft responds to thermal load and disturbance.",
    ),
    Definition(
        "oxygen",
        "Flue oxygen",
        "%",
        0,
        10,
        2.5,
        5,
        "ring",
        "Illustrative oxygen fraction varies with burner position and heat load.",
    ),
    Definition(
        "feed",
        "Raw-meal feed",
        "t/h",
        0,
        240,
        135,
        185,
        "flow",
        "Illustrative feed rate decreases as the disturbance grows.",
    ),
    Definition(
        "speed",
        "Kiln rotation",
        "rpm",
        0,
        6,
        2.5,
        4,
        "rotor",
        "Illustrative shell speed responds to duty and thermal deviation.",
    ),
    Definition(
        "cooler",
        "Cooler outlet",
        "°C",
        40,
        260,
        80,
        140,
        "thermometer",
        "Illustrative outlet temperature rises with kiln thermal deviation.",
    ),
]


def estimate(state):
    heat = (state.temperature - state.target) / PROFILE.thermal.gain
    load = state.disturbance / PROFILE.thermal.gain
    drive = state.actuator - 50
    return [
        -80 + heat * 0.8 - load * 0.3,
        3.5 - drive * 0.03 - heat * 0.025,
        160 - load * 1.5,
        3.2 + drive * 0.012 - heat * 0.005,
        110 + heat * 2.5,
    ]
