"""Small contracts for industry extensions; no provider or HTTP dependencies."""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["dial", "ring", "flow", "rotor", "tank", "thermometer"]


@dataclass(frozen=True)
class ThermalParameters:
    target: float
    gain: float
    band: float
    envelope: float
    asset: str


@dataclass(frozen=True)
class IndustryProfile:
    id: str
    name: str
    thermal: ThermalParameters
    read_tool: str
    simulate_tool: str
    skill: str


@dataclass(frozen=True)
class Definition:
    id: str
    name: str
    unit: str
    minimum: float
    maximum: float
    low: float
    high: float
    kind: Kind
    explanation: str


@dataclass(frozen=True)
class FaultDef:
    """One catalogue entry. `thermal` is in gain units: disturbance = thermal * gain * severity.

    `effects` maps a layer (signal, camera, robot, business) to magnitudes at severity 1.
    Later phases read them; the thermal model only ever sees the disturbance term.
    """

    id: str
    name: str
    equipment: str
    description: str
    thermal: float
    effects: dict[str, dict[str, float]]
    remedy: str
    ramp_ticks: int = 30
    domain: Literal["fault", "business"] = "fault"


@dataclass(frozen=True)
class BusinessParameters:
    """Placeholder economics and emission factors for the simulated business layer."""

    product: str
    nominal_rate_tph: float
    raw_per_t: float
    fuel_gj_per_t: float
    kwh_per_t: float
    fuel_ef_kg_per_gj: float
    process_ef_kg_per_t: float
    price_per_t: float
    fuel_cost_per_gj: float
    tariff_per_kwh: float
    penalty_per_t: float
    spares: dict[str, tuple[int, float]]  # part -> (on hand, lead time hours)
    remedy_spare: dict[str, str | None]  # remedy -> part consumed (None = none)
    repair_hours: dict[str, float]  # placeholder downtime per remedy, in simulated hours
    part_cost: dict[str, float]  # placeholder price per spare part


@dataclass(frozen=True)
class ChannelDef:
    """A simulated sensor channel. `effects` maps a fault effect key to add, scale or swing."""

    id: str
    name: str
    equipment: str
    modality: Literal["waveform", "scalar", "event"]
    unit: str
    nominal: float
    noise: float = 0.0
    low: float | None = None
    high: float | None = None
    rate_hz: float = 1.0
    freq_hz: float = 0.0  # waveform: shaft or fundamental frequency
    link: tuple[str, float] | None = None  # (State field, gain per unit above target or 50)
    effects: tuple[tuple[str, Literal["add", "scale", "cut", "swing"]], ...] = ()


@dataclass(frozen=True)
class CameraDef:
    id: str
    name: str
    equipment: str
    zone: str
    detects: dict[str, str]  # camera effect key -> detection label


@dataclass(frozen=True)
class ZoneDef:
    id: str
    name: str
    kind: Literal["dock", "process", "hot", "safe"]
    equipment: tuple[str, ...] = ()
    next_to: tuple[str, ...] = ()
