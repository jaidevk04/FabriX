"""Deterministic baseline feedback and non-bypassable simulator interlocks."""

from cognition.domain import State
from cognition.industries import PACKS


def feedback(state: State) -> float:
    if state.mode != "automatic" or state.quality != "good":
        return 0.0
    return max(
        -2.0, min(2.0, -(state.temperature - state.target) / PACKS[state.spec.industry].gain * 0.15)
    )


def actuator_target(state: State) -> float:
    pack = PACKS[state.spec.industry]
    if state.quality == "good":
        if state.temperature >= state.target + pack.envelope:
            state.interlock = True
        elif state.temperature <= state.target + pack.envelope * 0.85:
            state.interlock = False
    return 10.0 if state.interlock else state.duty + feedback(state)


def assess(state: State) -> dict:
    interlock = (
        state.interlock or state.temperature >= state.target + PACKS[state.spec.industry].envelope
    )
    blocked = interlock or state.stuck or state.quality != "good" or state.mode != "automatic"
    return {
        "status": "interlocked" if interlock else "blocked" if blocked else "regulating",
        "basis": "Deterministic simulator feedback and high-temperature cutoff; no PLC connection.",
        "feedback": round(feedback(state), 3),
        "commanded_duty": state.duty,
        "actuator_position": state.actuator,
        "interlock": interlock,
        "tracking_fault": state.stuck,
        "cognitive_control_permitted": not blocked,
        "policy": (
            "Bounded local feedback; high-high cutoff at target + demo envelope, "
            "reset at 85% of envelope. Cognitive agents cannot change this policy."
        ),
    }
