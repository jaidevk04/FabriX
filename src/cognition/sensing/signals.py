"""SignalBus: deterministic multi-rate channels generated from plant state and active events."""

import math
import random
import threading
from collections import deque

from cognition.domain import ChannelReading, SignalFeatures, State
from cognition.industries import CHANNELS
from cognition.industries.base import ChannelDef
from cognition.persistence.store import Store
from cognition.simulation.faults import FaultEngine, active_effects

MAX_WINDOW = 1024
HISTORY_TICKS = 90  # scalar history kept per plant for the Learning view
WINDOWS_KEPT = 8  # recent waveform windows kept per plant (UI replay only)


class SignalBus:
    def __init__(self, store: Store, faults: FaultEngine) -> None:
        self.store = store
        self.faults = faults
        self._lock = threading.Lock()
        self._history: dict[str, deque] = {}
        self._windows: dict[str, deque] = {}

    def definitions(self, state: State) -> tuple[ChannelDef, ...]:
        return CHANNELS[state.spec.industry]

    def _context(self, plant_id: str) -> tuple[State, dict[str, float]]:
        state = self.store.plant(plant_id)
        events = self.faults.events(plant_id)
        return state, active_effects(events, state.spec.industry, state.tick).get("signal", {})

    @staticmethod
    def find(state: State, channel: str) -> ChannelDef:
        for definition in CHANNELS[state.spec.industry]:
            if definition.id == channel:
                return definition
        raise KeyError(channel)

    def record(self, plant_id: str) -> None:
        """Remember the latest sample so a page that opens later still shows the recent past."""
        state, effects = self._context(plant_id)
        defs = self.definitions(state)
        values = {d.id: self._reading(state, d, effects).value for d in defs}
        windows = {
            d.id: [round(v, 4) for v in self._samples(state, d, effects, 256)]
            for d in defs
            if d.modality == "waveform"
        }
        with self._lock:
            self._history.setdefault(plant_id, deque(maxlen=HISTORY_TICKS)).append(
                {"tick": state.tick, "values": values}
            )
            self._windows.setdefault(plant_id, deque(maxlen=WINDOWS_KEPT)).append(
                {"tick": state.tick, "samples": windows}
            )

    def clear(self, plant_id: str) -> None:
        with self._lock:
            self._history.pop(plant_id, None)
            self._windows.pop(plant_id, None)

    def history(self, plant_id: str) -> dict:
        state = self.store.plant(plant_id)
        with self._lock:
            ticks = list(self._history.get(plant_id, ()))
            windows = list(self._windows.get(plant_id, ()))
        rates = {d.id: d.rate_hz for d in self.definitions(state) if d.modality == "waveform"}
        return {"ticks": ticks, "windows": windows, "rates": rates}

    def read_all(self, plant_id: str) -> list[ChannelReading]:
        state, effects = self._context(plant_id)
        return [self._reading(state, d, effects) for d in self.definitions(state)]

    def read_one(self, plant_id: str, channel: str) -> ChannelReading:
        state, effects = self._context(plant_id)
        return self._reading(state, self.find(state, channel), effects)

    def _reading(self, state: State, d: ChannelDef, effects: dict[str, float]) -> ChannelReading:
        if d.modality == "event":
            value = float(state.interlock)
        elif d.modality == "waveform":
            value = self._features(state, d, effects, 256, spectrum=False).rms
        else:
            value = self._scalar(state, d, effects)
        status = "normal"
        if d.high is not None and value > d.high:
            status = "high"
        elif d.low is not None and value < d.low:
            status = "low"
        return ChannelReading(
            channel=d.id,
            name=d.name,
            equipment=d.equipment,
            modality=d.modality,
            unit=d.unit,
            value=round(value, 3),
            nominal=d.nominal,
            low=d.low,
            high=d.high,
            status=status,  # type: ignore[arg-type]
        )

    def _scalar(self, state: State, d: ChannelDef, effects: dict[str, float]) -> float:
        rng = random.Random(f"{state.spec.id}:{d.id}:{state.tick}")
        value = d.nominal
        if d.link is not None:
            field, gain = d.link
            reference = state.target if field == "temperature" else 50
            value += gain * (getattr(state, field) - reference)
        for key, mode in d.effects:
            magnitude = effects.get(key, 0.0)
            if mode == "add":
                value += magnitude
            elif mode == "scale":
                value *= 1 + magnitude
            elif mode == "cut":
                value *= 1 - min(magnitude, 1.0)
            elif mode == "swing":
                value += magnitude * math.sin(state.tick * 0.9)
        return value + rng.gauss(0, d.noise)

    def baseline(self, plant_id: str, channel: str) -> ChannelReading:
        """The same channel with no active events: the simulated healthy twin."""
        state, _ = self._context(plant_id)
        return self._reading(state, self.find(state, channel), {})

    def baseline_features(
        self, plant_id: str, channel: str, n: int = 256, *, spectrum: bool = False
    ) -> SignalFeatures:
        state, _ = self._context(plant_id)
        d = self.find(state, channel)
        if d.modality != "waveform":
            raise ValueError("Only waveform channels have features")
        return self._features(state, d, {}, min(max(n, 16), MAX_WINDOW), spectrum)

    def window(self, plant_id: str, channel: str, n: int = 256) -> tuple[list[float], float]:
        """Raw samples for the UI only. Agents receive features, never raw waveforms."""
        state, effects = self._context(plant_id)
        d = self.find(state, channel)
        if d.modality != "waveform":
            raise ValueError("Only waveform channels have sample windows")
        return self._samples(state, d, effects, min(max(n, 16), MAX_WINDOW)), d.rate_hz

    def features(
        self, plant_id: str, channel: str, n: int = 256, *, spectrum: bool = True
    ) -> SignalFeatures:
        state, effects = self._context(plant_id)
        d = self.find(state, channel)
        if d.modality != "waveform":
            raise ValueError("Only waveform channels have features")
        return self._features(state, d, effects, min(max(n, 16), MAX_WINDOW), spectrum)

    def _samples(
        self, state: State, d: ChannelDef, effects: dict[str, float], n: int
    ) -> list[float]:
        rng = random.Random(f"{state.spec.id}:{d.id}:{state.tick}:{n}")
        rms, impulsive = d.nominal, 0.0
        for key, mode in d.effects:
            magnitude = effects.get(key, 0.0)
            if mode == "add":
                rms += magnitude
                impulsive += magnitude
            elif mode == "scale":
                rms *= 1 + magnitude / max(d.nominal, 1e-6) * 0.25
        amplitude = rms * math.sqrt(2) * 0.8
        probability = min(0.08, impulsive / 60)
        samples = []
        for i in range(n):
            t = i / d.rate_hz
            x = amplitude * math.sin(2 * math.pi * d.freq_hz * t)
            x += 0.3 * amplitude * math.sin(2 * math.pi * 2 * d.freq_hz * t + 0.5)
            x += rng.gauss(0, d.noise)
            if rng.random() < probability:
                x += rng.choice((-1, 1)) * amplitude * rng.uniform(1.5, 3.0)
            samples.append(round(x, 4))
        return samples

    def _features(
        self, state: State, d: ChannelDef, effects: dict[str, float], n: int, spectrum: bool = True
    ) -> SignalFeatures:
        x = self._samples(state, d, effects, n)
        mean = sum(x) / n
        centred = [v - mean for v in x]
        power = sum(v * v for v in centred) / n
        rms = math.sqrt(power)
        peak = max(abs(v) for v in centred)
        kurtosis = (sum(v**4 for v in centred) / n) / (power * power) if power > 0 else 0.0
        best_bin, best_mag = 1, 0.0
        for k in range(1, min(n // 2, 128) if spectrum else 1):
            re = sum(v * math.cos(2 * math.pi * k * i / n) for i, v in enumerate(centred))
            im = sum(v * math.sin(2 * math.pi * k * i / n) for i, v in enumerate(centred))
            if re * re + im * im > best_mag:
                best_bin, best_mag = k, re * re + im * im
        return SignalFeatures(
            channel=d.id,
            tick=state.tick,
            samples=n,
            rate_hz=d.rate_hz,
            rms=round(rms, 4),
            peak=round(peak, 4),
            crest=round(peak / rms, 3) if rms > 0 else 0.0,
            kurtosis=round(kurtosis, 3),
            dominant_hz=round(best_bin * d.rate_hz / n, 2),
        )
