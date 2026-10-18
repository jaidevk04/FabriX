"""Chemical fault catalogue: simulated, uncalibrated effects on a jacketed reactor."""

from cognition.industries.base import FaultDef

FAULTS = {
    "agitator_imbalance": FaultDef(
        "agitator_imbalance",
        "Agitator imbalance",
        "agitator",
        "Vibration and motor current rise on the agitator drive; mixing worsens slightly.",
        1.0,
        {
            "signal": {"agitator_vibration_rms": 3.0, "agitator_current": 0.14},
            "business": {"availability": -0.04},
        },
        "agitator_rebalance",
        ramp_ticks=30,
    ),
    "jacket_fouling": FaultDef(
        "jacket_fouling",
        "Jacket fouling",
        "jacket",
        "Fouling slows heat transfer: slow temperature response and lower coolant flow.",
        4.0,
        {
            "signal": {"coolant_flow_drop": 0.25, "jacket_dt_rise": 6.0},
            "business": {"throughput": -0.08, "energy_use": 0.1},
        },
        "jacket_flush",
        ramp_ticks=60,
    ),
    "pipe_leak": FaultDef(
        "pipe_leak",
        "Process pipe leak",
        "pipes",
        "Small leak on process piping: gas readings rise, product loss, emissions.",
        1.0,
        {
            "signal": {"gas_ppm": 40.0, "pressure_drop": 0.15},
            "camera": {"leak_plume": 0.8},
            "business": {"scrap": 0.04, "emissions": 0.1},
        },
        "pipe_seal",
        ramp_ticks=15,
    ),
    "pump_cavitation": FaultDef(
        "pump_cavitation",
        "Circulation pump cavitation",
        "jacket",
        "Jacket circulation pump cavitates: noisy flow, vibration, uneven heating.",
        2.0,
        {
            "signal": {"pump_vibration_rms": 3.2, "coolant_flow_swing": 3.5},
            "business": {"availability": -0.05},
        },
        "pump_service",
        ramp_ticks=25,
    ),
}
