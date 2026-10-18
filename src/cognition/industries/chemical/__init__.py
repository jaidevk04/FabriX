"""Reactor process definitions and illustrative signal model."""

from cognition.industries.base import Definition, IndustryProfile, ThermalParameters

PROFILE = IndustryProfile(
    id="chemical",
    name="Reactor process",
    thermal=ThermalParameters(180, 1.5, 3, 35, "Jacketed reactor thermal surrogate"),
    read_tool="read_reactor_process",
    simulate_tool="simulate_reactor_duty",
    skill="chemical-operations",
)
DEFINITIONS = [
    Definition(
        "pressure",
        "Reactor pressure",
        "bar",
        0,
        8,
        1.6,
        3.2,
        "dial",
        "Illustrative pressure increases with reactor temperature deviation; "
        "no thermodynamic equation of state is claimed.",
    ),
    Definition(
        "level",
        "Vessel fill",
        "%",
        0,
        100,
        45,
        75,
        "tank",
        "Illustrative vessel inventory depends on the current disturbance; "
        "no mass-balance model is calibrated.",
    ),
    Definition(
        "agitation",
        "Agitator speed",
        "rpm",
        0,
        600,
        260,
        400,
        "rotor",
        "Illustrative mixing speed responds to the thermal actuator position.",
    ),
    Definition(
        "conversion",
        "Batch conversion",
        "%",
        0,
        100,
        85,
        100,
        "ring",
        "Illustrative conversion score declines away from the thermal target; "
        "this is not a reaction-kinetics prediction.",
    ),
    Definition(
        "coolant",
        "Jacket circulation",
        "m³/h",
        0,
        60,
        18,
        40,
        "flow",
        "Illustrative circulation demand increases with thermal deviation.",
    ),
]


def estimate(state):
    heat = (state.temperature - state.target) / PROFILE.thermal.gain
    load = state.disturbance / PROFILE.thermal.gain
    drive = state.actuator - 50
    return [
        2.4 + heat * 0.06,
        62 + load * 0.5,
        320 + drive * 1.5,
        96 - abs(heat) * 0.5,
        26 + abs(heat) * 0.8,
    ]
