"""Evidence answers for the core bus: read-only, from monitors and sensors, no agents."""

from cognition.domain import BusRequest


def signal_evidence(platform, request: BusRequest) -> dict:
    readings = [
        r for r in platform.signals.read_all(request.plant_id) if r.equipment == request.target
    ]
    waves = {}
    for reading in readings:
        if reading.modality == "waveform":
            features = platform.signals.features(request.plant_id, reading.channel, spectrum=False)
            baseline = platform.signals.baseline_features(request.plant_id, reading.channel)
            waves[reading.channel] = {
                "rms": features.rms,
                "baseline_rms": baseline.rms,
                "kurtosis": features.kurtosis,
            }
    return {
        "equipment": request.target,
        "channels": [r.model_dump(mode="json") for r in readings],
        "waveform_features": waves,
        "basis": "Simulated channels; features only, no raw waveform.",
    }


def detection_evidence(platform, request: BusRequest) -> dict:
    cameras = [
        c for c in platform.cameras.definitions(request.plant_id) if c.equipment == request.target
    ]
    return {
        "equipment": request.target,
        "cameras": [
            {
                "camera": c.id,
                "detections": [
                    d.model_dump(mode="json")
                    for d in platform.cameras.detections(request.plant_id, c.id)
                ],
            }
            for c in cameras
        ],
        "basis": "Simulated detector on generated placeholder frames.",
    }


def fleet_evidence(platform, request: BusRequest) -> dict:
    fleet = platform.fleet.state(request.plant_id)
    zone = next((z for z in fleet.zones if request.target in z.equipment), None)
    return {
        "equipment": request.target,
        "zone": zone.model_dump(mode="json") if zone else None,
        "robots": [
            {
                "name": r.name,
                "kind": r.kind,
                "zone": r.zone,
                "battery": r.battery,
                "status": r.status,
            }
            for r in fleet.robots
        ],
        "basis": "Simulated fleet on a zone graph.",
    }
