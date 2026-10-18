"""Shared core helpers: alert levels, report assembly and equipment lookup."""

from dataclasses import dataclass
from typing import Any, Protocol

from cognition.domain import AlertLevel, CoreAlert, CoreName, CoreReport, State
from cognition.industries import ZONES

LEVELS: tuple[tuple[AlertLevel, float], ...] = (
    ("escalate", 0.75),
    ("notify", 0.5),
    ("watch", 0.25),
)
RANK = {"info": 0, "watch": 1, "notify": 2, "escalate": 3}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def level_for(score: float) -> AlertLevel:
    for name, threshold in LEVELS:
        if score >= threshold:
            return name
    return "info"


def confidence_for(score: float) -> float:
    return round(clamp(0.5 + 0.45 * score, 0.0, 0.97), 3)


def plant_equipment(state: State) -> set[str]:
    return {item for zone in ZONES[state.spec.industry] for item in zone.equipment}


def build_report(
    state: State,
    core: CoreName,
    alerts: list[CoreAlert],
    summary: str,
    assessment: dict[str, Any],
    *,
    source: str = "monitor",
    model: str = "simulated-monitor",
) -> CoreReport:
    worst = max((RANK[a.level] for a in alerts), default=0)
    status = "alert" if worst >= RANK["notify"] else "watch" if worst >= RANK["watch"] else "normal"
    return CoreReport(
        plant_id=state.spec.id,
        core=core,
        revision=state.revision,
        tick=state.tick,
        status=status,  # type: ignore[arg-type]
        summary=summary,
        alerts=alerts,
        assessment=assessment,
        source=source,  # type: ignore[arg-type]
        model=model,
    )


class Monitor(Protocol):
    def __call__(self, platform: Any, plant_id: str) -> CoreReport: ...


@dataclass(frozen=True)
class CoreSpec:
    """One core: its always-on monitor and its offline reference analyser."""

    name: CoreName
    description: str
    monitor: Monitor
    reference: Monitor
