"""Learning core monitor: a simulated sensor language model over multi-rate channels."""

from cognition.cores.base import build_report, clamp, confidence_for, level_for
from cognition.domain import CoreAlert, CoreReport
from cognition.sensing.signals import SignalBus

MODEL = "simulated-sensor-lm-v0"


def encode_waveform(rms_ratio: float, kurtosis_excess: float) -> tuple[str, float]:
    """Per-modality encoder: a token and an anomaly score from simple features."""
    level = clamp((rms_ratio - 1.15) / 0.9)
    impulsive = clamp(kurtosis_excess / 2)
    score = round(0.7 * level + 0.3 * impulsive, 3)
    if score < 0.1:
        return "wave:steady", score
    return ("wave:impulsive-high" if impulsive > 0.4 else "wave:level-high"), score


def encode_scalar(deviation: float, scale: float, status: str) -> tuple[str, float]:
    score = clamp(abs(deviation) / scale / 4)
    if status != "normal":
        score = max(score, 0.6)
    if score < 0.1:
        return "scalar:steady", round(score, 3)
    return ("scalar:rising" if deviation > 0 else "scalar:falling"), round(score, 3)


def channel_scores(platform, plant_id: str, *, respect_config: bool = True) -> list[dict]:
    bus: SignalBus = platform.signals
    config = platform.config_desk.get(plant_id, "learning") if respect_config else None
    masked = platform.config_desk.masked(plant_id, "learning") if respect_config else set()
    scores = []
    for reading in bus.read_all(plant_id):
        if reading.modality == "event" or reading.channel in masked:
            continue
        base = bus.baseline(plant_id, reading.channel)
        if reading.modality == "waveform":
            now = bus.features(plant_id, reading.channel, spectrum=False)
            ref = bus.baseline_features(plant_id, reading.channel)
            token, score = encode_waveform(
                now.rms / max(ref.rms, 1e-6), now.kurtosis - ref.kurtosis
            )
            detail = f"rms {now.rms} vs baseline {ref.rms} {reading.unit}, kurtosis {now.kurtosis}"
        else:
            definition = bus.find(platform.store.plant(plant_id), reading.channel)
            scale = max(3 * definition.noise, 0.03 * abs(definition.nominal), 1e-6)
            token, score = encode_scalar(reading.value - base.value, scale, reading.status)
            detail = f"{reading.value} {reading.unit} vs baseline {base.value}"
        if config is not None:
            score = round(clamp(score * config.sensitivity), 3)
        scores.append(
            {
                "channel": reading.channel,
                "equipment": reading.equipment,
                "modality": reading.modality,
                "token": token,
                "score": score,
                "detail": detail,
            }
        )
    return scores


def fuse(scores: list[dict]) -> dict[str, dict]:
    """Noisy-OR fusion across modalities per equipment: agreement raises the score."""
    grouped: dict[str, dict] = {}
    for item in scores:
        group = grouped.setdefault(item["equipment"], {"channels": [], "miss": 1.0})
        group["channels"].append(item)
        group["miss"] *= 1 - 0.9 * item["score"]
    for group in grouped.values():
        group["score"] = round(1 - group["miss"], 3)
        del group["miss"]
    return grouped


def stage_of(score: float) -> str:
    return "early" if score < 0.5 else "developing" if score < 0.75 else "advanced"


def remaining_life_hours(score: float) -> float:
    """Simulated prognosis: shrinks as the fused score grows. Not a calibrated model."""
    return round(max(1.0, 400 * (1 - score) ** 1.5), 0)


def monitor(platform, plant_id: str) -> CoreReport:
    state = platform.store.plant(plant_id)
    fused = fuse(channel_scores(platform, plant_id))
    alerts = []
    for equipment, group in sorted(fused.items()):
        score = group["score"]
        level = level_for(score)
        if level == "info":
            continue
        hot = [c for c in group["channels"] if c["score"] >= 0.1]
        alerts.append(
            CoreAlert(
                id=f"learning-{equipment}",
                plant_id=plant_id,
                core="learning",
                level=level,
                title=f"{equipment} signal anomaly ({stage_of(score)})",
                summary=(
                    f"Fused sensor-model score {score} on {equipment}: "
                    + "; ".join(f"{c['channel']} {c['token']}" for c in hot)
                ),
                confidence=confidence_for(score),
                equipment=equipment,
                evidence=[f"{c['channel']}: {c['detail']}" for c in hot][:10],
                revision=state.revision,
                tick=state.tick,
            )
        )
    worst = max((g["score"] for g in fused.values()), default=0.0)
    summary = (
        "All monitored signals match their simulated baselines."
        if not alerts
        else f"{len(alerts)} equipment group(s) deviate from baseline; worst score {worst}."
    )
    return build_report(
        state,
        "learning",
        alerts,
        summary,
        {
            "equipment": {
                key: {"score": g["score"], "stage": stage_of(g["score"])}
                for key, g in fused.items()
            }
        },
        model=MODEL,
    )
