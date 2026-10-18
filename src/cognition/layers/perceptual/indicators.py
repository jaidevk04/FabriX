"""Illustrative process estimates derived from the thermal snapshot, not new sensors.

Ranges are demo display bands, not plant operating limits. These estimates do
not extend the gateway's control authority or change thermal recovery criteria.
"""

from typing import Literal

from cognition.domain import Contract, State
from cognition.industries import DEFINITIONS, get_industry
from cognition.industries.base import Kind


class Indicator(Contract):
    id: str
    name: str
    unit: str
    value: float | None
    minimum: float
    maximum: float
    band: tuple[float, float]
    kind: Kind
    condition: Literal["within_band", "outside_band", "unavailable"]
    explanation: str


def process_indicators(state: State) -> list[Indicator]:
    values = get_industry(state.spec.industry).estimate(state)
    result = []
    for definition, estimate in zip(DEFINITIONS[state.spec.industry], values, strict=True):
        value = round(max(definition.minimum, min(definition.maximum, estimate)), 2)
        condition: Literal["within_band", "outside_band", "unavailable"] = (
            "unavailable"
            if state.quality != "good"
            else "within_band"
            if definition.low <= value <= definition.high
            else "outside_band"
        )
        result.append(
            Indicator(
                id=definition.id,
                name=definition.name,
                unit=definition.unit,
                value=value if state.quality == "good" else None,
                minimum=definition.minimum,
                maximum=definition.maximum,
                band=(definition.low, definition.high),
                kind=definition.kind,
                condition=condition,
                explanation=definition.explanation,
            )
        )
    return result
