from typing import Literal

from pydantic import Field

from cognition.domain import Contract
from cognition.simulation.thermal import Scenario


class Trigger(Contract):
    scenario: Scenario | Literal["perception_conflict"] = "heat_load"


class AttentionDecision(Contract):
    """How the operator answers a run that is waiting on them ("Needs attention")."""

    action: Literal["fixed", "investigate", "dismiss"]


class WorldStart(Contract):
    interval_seconds: float = Field(default=1.0, ge=0.2, le=60)


class InjectEvent(Contract):
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    severity: float = Field(default=0.7, ge=0, le=1)
    ramp_ticks: int | None = Field(default=None, ge=0, le=10_000)
    duration_ticks: int | None = Field(default=None, ge=1, le=1_000_000)


class MissionRequest(Contract):
    """Operator-started T0 or T1 mission. Repairs go through the Gateway, not this route."""

    kind: Literal["inspect", "verify", "sample", "patrol", "transport"]
    target: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    tool: str = Field(default="", max_length=40)
    expect: str = Field(default="", max_length=64)


class WorkOrderRequest(Contract):
    equipment: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    remedy: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    note: str = Field(default="", max_length=300)


class SelectHarness(Contract):
    harness: str = Field(default="reference", pattern=r"^[a-z][a-z0-9_-]{0,40}$")
