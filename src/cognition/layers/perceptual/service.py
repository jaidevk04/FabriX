"""Qualified evidence interface for simulator, learned and vision providers."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field, model_validator

from cognition.domain import Contract, State, now
from cognition.industries import PACKS
from cognition.layers.perceptual.indicators import process_indicators
from cognition.persistence.store import Store


class Observation(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    plant_id: str
    revision: int = Field(ge=0)
    observed_at: datetime
    expires_at: datetime
    source: Literal["ml", "vision", "demo", "signal", "robot"]
    model: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=120)
    status: Literal["normal", "anomaly", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def valid_window(self):
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Evidence timestamps must include a timezone")
        if not 0 < (self.expires_at - self.observed_at).total_seconds() <= 300:
            raise ValueError("Evidence validity window must be at most 300 seconds")
        return self


class EvidenceProvider(Protocol):
    """Adapter boundary for future commissioned ML/vision integrations."""

    def assess(self, state: State) -> dict: ...


class SimulatorProvider:
    def assess(self, state: State) -> dict:
        pack = PACKS[state.spec.industry]
        delta = abs(state.temperature - state.target)
        status = (
            "unavailable"
            if state.quality != "good"
            else "anomaly"
            if delta > pack.band
            else "normal"
        )
        return {
            "provider": "simulator-heuristic-v1",
            "trained_model": False,
            "status": status,
            "confidence": None,
            "basis": (
                "Deterministic thermal residual and derived model estimates; "
                "not ML or independent sensors."
            ),
            "thermal_residual": round(state.temperature - state.target, 3),
            "indicators": [value.model_dump(mode="json") for value in process_indicators(state)],
        }


class Perception:
    def __init__(self, store: Store, provider: EvidenceProvider | None = None):
        self.store, self.provider = store, provider or SimulatorProvider()

    def publish(
        self, state: State, observation: Observation, *, record: bool = True
    ) -> Observation:
        if observation.plant_id != state.spec.id or observation.revision != state.revision:
            raise ValueError("Evidence must match the current plant and revision")
        if (
            not 0 <= (now() - observation.observed_at).total_seconds() <= 300
            or observation.expires_at <= now()
        ):
            raise ValueError("Evidence is stale or future-dated")
        self.store.put("observations", f"{state.spec.id}:{observation.id}", observation)
        if not record:
            return observation
        self.store.audit(
            f"automation:{state.spec.id}",
            "observation_received",
            {
                "id": observation.id,
                "source": observation.source,
                "model": observation.model,
                "revision": observation.revision,
            },
        )
        return observation

    def assess(self, state: State) -> dict:
        report = self.provider.assess(state)
        observations, excluded = [], 0
        for data in self.store.records("observations"):
            item = Observation.model_validate(data)
            if item.plant_id != state.spec.id:
                continue
            if not 0 <= state.revision - item.revision <= 3 or item.expires_at <= now():
                excluded += 1
                continue
            observations.append(item.model_dump(mode="json"))
        # Disagreement is surfaced, never resolved by silently trusting one source.
        conflicts = [
            f"{item['model']}: {item['status']} conflicts with "
            f"thermal assessment {report['status']}."
            for item in observations
            if item["confidence"] >= 0.7
            and item["status"] in ("normal", "anomaly")
            and report["status"] in ("normal", "anomaly")
            and item["status"] != report["status"]
        ]
        return report | {
            "observations": observations,
            "conflicts": conflicts,
            "excluded_observations": excluded,
            "evidence_policy": (
                "Evidence must be unexpired and within three revisions of the current snapshot. "
                "Low confidence or disagreement requires explicit review; "
                "evidence never grants actuator authority."
            ),
        }
