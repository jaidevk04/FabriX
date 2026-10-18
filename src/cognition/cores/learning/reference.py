"""Offline analyser for the learning core: signature-matched diagnosis and prognosis.

It reads only sensor evidence, never the injected-event labels.
"""

from cognition.cores.base import build_report
from cognition.cores.learning.monitor import (
    MODEL,
    channel_scores,
    fuse,
    remaining_life_hours,
    stage_of,
)
from cognition.domain import CoreReport
from cognition.industries import CHANNELS, catalogue


def diagnose(platform, plant_id: str) -> list[dict]:
    """Rank catalogue faults by how many of their signal channels currently deviate."""
    state = platform.store.plant(plant_id)
    deviating = {c["channel"]: c["score"] for c in channel_scores(platform, plant_id)}
    by_key: dict[str, list[str]] = {}
    for channel in CHANNELS[state.spec.industry]:
        for key, _mode in channel.effects:
            by_key.setdefault(key, []).append(channel.id)
    candidates = []
    for fault in catalogue(state.spec.industry).values():
        keys = fault.effects.get("signal", {})
        channels = sorted({ch for key in keys for ch in by_key.get(key, [])})
        if not channels:
            continue
        hits = [ch for ch in channels if deviating.get(ch, 0) >= 0.25]
        if not hits:
            continue
        strength = sum(deviating[ch] for ch in hits) / len(channels)
        candidates.append(
            {
                "fault": fault.id,
                "equipment": fault.equipment,
                "match": round(len(hits) / len(channels), 2),
                "strength": round(strength, 3),
                "channels": hits,
                "remedy": fault.remedy,
            }
        )
    return sorted(candidates, key=lambda c: (-c["match"], -c["strength"]))


def reference(platform, plant_id: str) -> CoreReport:
    from cognition.cores.learning.monitor import monitor

    base = monitor(platform, plant_id)
    state = platform.store.plant(plant_id)
    fused = fuse(channel_scores(platform, plant_id))
    candidates = diagnose(platform, plant_id)
    prognosis = {
        equipment: {
            "stage": stage_of(group["score"]),
            "remaining_life_hours": remaining_life_hours(group["score"]),
        }
        for equipment, group in fused.items()
        if group["score"] >= 0.25
    }
    summary = base.summary
    if candidates:
        top = candidates[0]
        summary += (
            f" Best signature match: {top['fault']} on {top['equipment']} "
            f"({int(top['match'] * 100)}% of its channels)."
        )
    return build_report(
        state,
        "learning",
        base.alerts,
        summary,
        base.assessment | {"candidates": candidates[:3], "prognosis": prognosis},
        source="reference",
        model=MODEL,
    )
