"""Furnace process definitions and illustrative signal model."""

from cognition.industries.base import Definition, IndustryProfile, ThermalParameters

PROFILE = IndustryProfile(
    id="steel",
    name="Furnace process",
    thermal=ThermalParameters(1200, 10, 18, 220, "Reheating furnace surrogate"),
    read_tool="read_furnace_process",
    simulate_tool="simulate_furnace_duty",
    skill="steel-operations",
)
DEFINITIONS = [
    Definition(
        "pressure",
        "Furnace pressure",
        "Pa",
        -10,
        40,
        5,
        18,
        "dial",
        "Illustrative furnace pressure responds to heat-load disturbance.",
    ),
    Definition(
        "oxygen",
        "Flue oxygen",
        "%",
        0,
        10,
        2,
        4.5,
        "ring",
        "Illustrative combustion oxygen varies with burner position and thermal load.",
    ),
    Definition(
        "core",
        "Billet core",
        "°C",
        800,
        1400,
        1100,
        1200,
        "thermometer",
        "Illustrative billet core temperature is offset from furnace temperature; "
        "no heat-penetration model is calibrated.",
    ),
    Definition(
        "fuel",
        "Fuel-gas flow",
        "Nm³/h",
        0,
        3000,
        1000,
        2100,
        "flow",
        "Illustrative fuel demand follows the current burner actuator.",
    ),
    Definition(
        "throughput",
        "Line throughput",
        "t/h",
        0,
        160,
        75,
        125,
        "flow",
        "Illustrative production rate decreases with thermal deviation and disturbance.",
    ),
]


def estimate(state):
    heat = (state.temperature - state.target) / PROFILE.thermal.gain
    load = state.disturbance / PROFILE.thermal.gain
    drive = state.actuator - 50
    return [
        12 + heat * 0.35 + load * 0.2,
        3.2 - drive * 0.025 - heat * 0.025,
        state.temperature - 50,
        1500 + drive * 24,
        100 - abs(heat) * 0.8 - load * 0.4,
    ]
