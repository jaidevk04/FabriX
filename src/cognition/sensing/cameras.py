"""Camera feeds: generated placeholder frames and a simulated detector (no trained model)."""

import random
from importlib.resources import files

from cognition.domain import Detection, State
from cognition.industries import CAMERAS, FAULTS
from cognition.industries.base import CameraDef
from cognition.persistence.store import Store
from cognition.simulation.faults import FaultEngine, active_effects

CLIP_SUFFIXES = (".mp4", ".webm")
WARM = {"flame_cam": "#E58A3B", "furnace_cam": "#E58A3B", "shell_cam": "#C75B4A"}


class CameraBank:
    def __init__(self, store: Store, faults: FaultEngine) -> None:
        self.store = store
        self.faults = faults

    def definitions(self, plant_id: str) -> tuple[CameraDef, ...]:
        return CAMERAS[self.store.plant(plant_id).spec.industry]

    def find(self, plant_id: str, camera: str) -> CameraDef:
        for definition in self.definitions(plant_id):
            if definition.id == camera:
                return definition
        raise KeyError(camera)

    def _effects(self, state: State) -> dict[str, float]:
        events = self.faults.events(state.spec.id)
        return active_effects(events, state.spec.industry, state.tick).get("camera", {})

    def detections(self, plant_id: str, camera: str) -> list[Detection]:
        state = self.store.plant(plant_id)
        d = self.find(plant_id, camera)
        effects = self._effects(state)
        found = []
        for key, label in d.detects.items():
            magnitude = effects.get(key, 0.0)
            if magnitude < 0.05:
                continue
            rng = random.Random(f"{plant_id}:{camera}:{key}")
            jitter = random.Random(f"{plant_id}:{camera}:{key}:{state.tick}")
            confidence = min(0.99, 0.55 + 0.45 * min(magnitude, 1.0) + jitter.uniform(-0.03, 0.03))
            found.append(
                Detection(
                    camera=camera,
                    label=label,
                    confidence=round(max(0.0, confidence), 3),
                    severity=round(min(magnitude, 1.0), 3),
                    box=(
                        round(rng.uniform(0.15, 0.5) + jitter.uniform(-0.01, 0.01), 3),
                        round(rng.uniform(0.2, 0.5), 3),
                        round(rng.uniform(0.2, 0.3), 3),
                        round(rng.uniform(0.2, 0.3), 3),
                    ),
                )
            )
        return found

    def summary(self, plant_id: str) -> list[dict]:
        return [
            {
                "id": d.id,
                "name": d.name,
                "equipment": d.equipment,
                "zone": d.zone,
                "detects": sorted(d.detects.values()),
                "detections": self.detections(plant_id, d.id),
                "source": "generated placeholder frame",
            }
            for d in self.definitions(plant_id)
        ]

    def frame_svg(self, plant_id: str, camera: str, *, boxes: bool = True) -> str:
        """A generated stand-in for a camera frame. `boxes=False` leaves boxes to the UI."""
        state = self.store.plant(plant_id)
        d = self.find(plant_id, camera)
        rng = random.Random(f"{plant_id}:{camera}:{state.tick}")
        glow = WARM.get(camera, "#588FB6")
        noise = "".join(
            f'<rect x="{rng.randint(0, 316)}" y="{rng.randint(0, 176)}" '
            f'width="{rng.randint(2, 6)}" height="1" fill="#C2D7E7" opacity="0.08"/>'
            for _ in range(40)
        )
        marks = ""
        for det in self.detections(plant_id, camera) if boxes else []:
            x, y, w, h = (det.box[0] * 320, det.box[1] * 180, det.box[2] * 320, det.box[3] * 180)
            marks += (
                f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" fill="none" '
                f'stroke="#E5A04B" stroke-width="2"/>'
                f'<text x="{x:.0f}" y="{max(y - 4, 10):.0f}" fill="#E5A04B" font-size="9" '
                f'font-family="monospace">{det.label} {det.confidence:.2f}</text>'
            )
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" role="img" '
            f'aria-label="Placeholder frame from {d.name}">'
            f'<defs><radialGradient id="g" cx="50%" cy="55%" r="60%">'
            f'<stop offset="0" stop-color="{glow}" stop-opacity="0.55"/>'
            '<stop offset="1" stop-color="#0F1820" stop-opacity="1"/></radialGradient></defs>'
            '<rect width="320" height="180" fill="url(#g)"/>'
            '<rect x="60" y="70" width="200" height="50" rx="6" fill="#1C2A36" opacity="0.85"/>'
            '<rect x="80" y="120" width="160" height="14" fill="#233443" opacity="0.9"/>'
            f"{noise}{marks}"
            f'<text x="8" y="14" fill="#C2D7E7" font-size="10" font-family="monospace">'
            f"{d.name} | tick {state.tick}</text>"
            '<text x="8" y="172" fill="#C2D7E7" font-size="9" font-family="monospace" '
            'opacity="0.8">PLACEHOLDER FRAME | SIMULATED DETECTOR</text></svg>'
        )

    # ---------- footage library ----------
    @staticmethod
    def slug(label: str) -> str:
        return label.strip().lower().replace(" ", "-")

    def _clip_dir(self, industry: str):
        return files("cognition").joinpath("web", "media", "vision", industry)

    def clip_plan(self, plant_id: str) -> dict:
        """Clips the Vision page can play: faults each shows and whether the file exists."""
        industry = self.store.plant(plant_id).spec.industry
        folder = self._clip_dir(industry.value)
        present = (
            {item.name for item in folder.iterdir() if item.is_file()} if folder.is_dir() else set()
        )
        catalogue = FAULTS[industry]

        def entry(camera: CameraDef, state: str, label: str, slug: str, faults: list[dict]) -> dict:
            name = next(
                (
                    f"{camera.id}__{slug}{s}"
                    for s in CLIP_SUFFIXES
                    if f"{camera.id}__{slug}{s}" in present
                ),
                None,
            )
            return {
                "camera": camera.id,
                "camera_name": camera.name,
                "state": state,
                "label": label,
                "file": name or f"{camera.id}__{slug}.mp4",
                "available": name is not None,
                "url": f"/static/media/vision/{industry.value}/{name}" if name else None,
                "faults": faults,
            }

        clips: list[dict] = []
        covered: set[str] = set()
        for camera in self.definitions(plant_id):
            clips.append(entry(camera, "normal", "normal operation", "normal", []))
            for key, label in camera.detects.items():
                faults = [
                    {"id": f.id, "name": f.name}
                    for f in catalogue.values()
                    if key in f.effects.get("camera", {})
                ]
                covered.update(f["id"] for f in faults)
                clips.append(entry(camera, "fault", label, self.slug(label), faults))
        uncovered = [
            {"id": f.id, "name": f.name, "equipment": f.equipment}
            for f in catalogue.values()
            if f.domain == "fault" and f.id not in covered
        ]
        idle = [c.id for c in self.definitions(plant_id) if not c.detects]
        return {"clips": clips, "uncovered": uncovered, "idle_cameras": idle}
