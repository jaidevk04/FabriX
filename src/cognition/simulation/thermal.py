"""Educational thermal surrogates, with actuator lag and bounded baseline control.

Each tick advances simulated process time by SECONDS_PER_TICK (an illustrative scale,
not a calibrated time constant). The three
packs share a model with industry-specific parameters; no calibration is implied.
"""

from typing import Literal

from cognition.domain import SECONDS_PER_TICK, Action, Control, PlantSpec, Prediction, State, now
from cognition.industries import PACKS
from cognition.layers.reflexive import actuator_target

Scenario = Literal["heat_load", "actuator_stuck", "sensor_fault"]


def onboard(spec: PlantSpec) -> State:
    pack = PACKS[spec.industry]
    return State(spec=spec, temperature=pack.target, target=pack.target)


def inject(state: State, scenario: Scenario) -> State:
    result = state.model_copy(deep=True)
    pack = PACKS[state.spec.industry]
    result.temperature += pack.gain * 7
    result.disturbance = pack.gain * 15
    if scenario == "actuator_stuck":
        result.stuck = True
    elif scenario == "sensor_fault":
        result.quality = "bad"
    result.revision += 1
    result.sampled_at = now()
    return result


def check_action(state: State, action: Action) -> None:
    if state.interlock:
        raise ValueError("Reflexive interlock blocks cognitive control")
    limits = Control()
    if not limits.minimum <= action.value <= limits.maximum:
        raise ValueError("Control bound exceeded")
    if abs(action.value - state.duty) > limits.max_change:
        raise ValueError("Maximum control change exceeded")


def advance(state: State, steps: int = 60) -> tuple[State, list[float]]:
    result = state.model_copy(deep=True)
    pack = PACKS[state.spec.industry]
    trajectory = [result.temperature]
    for _ in range(steps):
        commanded = actuator_target(result)
        if not result.stuck:
            result.actuator += 0.3 * (commanded - result.actuator)
        equilibrium = result.target + pack.gain * (result.actuator - 50) + result.disturbance
        result.temperature += 0.1 * (equilibrium - result.temperature)
        result.tick += 1
        result.sim_seconds += SECONDS_PER_TICK
        trajectory.append(result.temperature)
    result.revision += 1
    result.sampled_at = now()
    return result, trajectory


def recovered(state: State, trajectory: list[float]) -> bool:
    band = PACKS[state.spec.industry].band
    return (
        state.quality == "good"
        and len(trajectory) >= 10
        and all(abs(t - state.target) <= band for t in trajectory[-10:])
    )


def simulate(state: State, action: Action | None = None) -> Prediction:
    shadow = state.model_copy(deep=True)
    if action is not None:
        check_action(state, action)
        shadow.duty = action.value
    final, trajectory = advance(shadow)
    envelope = PACKS[state.spec.industry].envelope
    return Prediction(
        trajectory=trajectory,
        final_error=abs(final.temperature - final.target),
        recovered=recovered(final, trajectory),
        safe=all(abs(t - final.target) <= envelope for t in trajectory),
        horizon_seconds=final.sim_seconds - state.sim_seconds,
    )
