"""Steel fault catalogue: simulated, uncalibrated effects on a reheating furnace."""

from cognition.industries.base import FaultDef

FAULTS = {
    "roller_bearing_wear": FaultDef(
        "roller_bearing_wear",
        "Roller bearing wear",
        "rollers",
        "Vibration and drive current rise on the roller conveyor.",
        1.0,
        {
            "signal": {"roller_vibration_rms": 3.5, "roller_current": 0.15},
            "robot": {"inspection_priority": 0.6},
            "business": {"availability": -0.05},
        },
        "bearing_swap",
        ramp_ticks=40,
    ),
    "burner_out": FaultDef(
        "burner_out",
        "Burner out",
        "burner",
        "One burner in the bank is out; furnace loses heat and fuel flow redistributes.",
        7.0,
        {
            "signal": {"burner_flame_loss": 1.0, "fuel_flow_shift": 0.2},
            "camera": {"flame_flicker": 0.5},
            "business": {"throughput": -0.12},
        },
        "burner_relight",
        ramp_ticks=10,
    ),
    "billet_surface_defect": FaultDef(
        "billet_surface_defect",
        "Billet surface defects",
        "billets",
        "Surface scale and cracks appear on billets leaving the furnace.",
        0.0,
        {
            "camera": {"surface_defects": 0.8},
            "business": {"scrap": 0.08},
        },
        "billet_reject",
        ramp_ticks=20,
    ),
    "roller_misalignment": FaultDef(
        "roller_misalignment",
        "Roller misalignment",
        "rollers",
        "Billets drift sideways on the rollers; vibration rises and heating is uneven.",
        1.5,
        {
            "signal": {"roller_vibration_rms": 2.0},
            "camera": {"billet_drift": 0.7},
            "business": {"scrap": 0.03},
        },
        "roller_realign",
        ramp_ticks=30,
    ),
}
