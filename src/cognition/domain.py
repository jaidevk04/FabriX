"""Versioned platform contracts; never expose native SDK objects here."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def now() -> datetime:
    return datetime.now(UTC)


SECONDS_PER_TICK = 10.0


def sim_clock(seconds: float) -> str:
    """Format elapsed simulated process time as D+HH:MM:SS."""
    total = int(seconds)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    return (
        f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
        if days
        else (f"{hours:02d}:{minutes:02d}:{secs:02d}")
    )


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Industry(StrEnum):
    CEMENT = "cement"
    STEEL = "steel"
    CHEMICAL = "chemical"


class PlantSpec(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    industry: Industry


class State(Contract):
    spec: PlantSpec
    revision: int = 0
    sampled_at: datetime = Field(default_factory=now)
    tick: int = 0
    sim_seconds: float = Field(default=0, ge=0)
    temperature: float
    target: float
    duty: float = 50
    actuator: float = 50
    disturbance: float = 0
    quality: Literal["good", "bad"] = "good"
    stuck: bool = False
    mode: Literal["automatic", "manual"] = "automatic"
    interlock: bool = False


class Action(Contract):
    control: Literal["thermal_duty"] = "thermal_duty"
    value: float
    unit: Literal["percent"] = "percent"


class Control(Contract):
    name: str = "thermal_duty"
    unit: str = "percent"
    minimum: float = 10
    maximum: float = 90
    max_change: float = 20
    required_mode: str = "automatic"


class MaintenanceAction(Contract):
    """A repair work order: validated by the Gateway, carried out by the robot core."""

    control: Literal["maintenance"] = "maintenance"
    equipment: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    remedy: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class MonitorConfigAction(Contract):
    """A change to a core's monitor settings. Not a plant command."""

    control: Literal["monitor_config"] = "monitor_config"
    core: Literal["learning", "vision"]
    setting: Literal["mask_channel", "unmask_channel", "set_sensitivity"]
    target: str = Field(default="", max_length=64)
    value: float | None = None
    duration_ticks: int | None = Field(default=None, ge=1, le=600)


# `Action` stays the thermal-duty action so existing callers keep working. A plain union
# (anyOf in JSON schema) is used on purpose: it is safer for structured model output.
ProposedAction = Action | MaintenanceAction | MonitorConfigAction


class ImpactMetric(Contract):
    name: str = Field(min_length=1, max_length=60)
    value: float
    unit: str = Field(default="", max_length=20)


class ExpectedImpact(Contract):
    summary: str = Field(min_length=1, max_length=500)
    metrics: list[ImpactMetric] = Field(default_factory=list, max_length=8)


class Proposal(Contract):
    schema_version: Literal["1"] = "1"
    plant_id: str
    revision: int = Field(ge=0)
    expires_at: datetime
    summary: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(default_factory=list, max_length=20)
    action: ProposedAction | None = None
    expected_impact: ExpectedImpact | None = None
    escalation: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_decision(self) -> "Proposal":
        if (self.action is None) == (self.escalation is None):
            raise ValueError("Provide exactly one action or escalation")
        if self.expires_at.tzinfo is None:
            raise ValueError("Expiry must have a timezone")
        return self


class Request(Contract):
    incident_id: str
    snapshot: State
    objective: str = (
        "Assess the incident across all automation layers and restore the operating objective "
        "using approved controls, or escalate."
    )


class Capabilities(Contract):
    name: str
    live_model: bool
    structured_output: bool = True
    resume: bool = False
    streaming: bool = False
    cancellation: str = "cooperative"


class Prediction(Contract):
    trajectory: list[float]
    final_error: float
    recovered: bool
    safe: bool
    horizon_seconds: float = 0


class Incident(Contract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    plant_id: str
    harness: str
    status: Literal[
        "investigating",
        "awaiting_approval",
        "verifying",
        "resolved",
        "escalated",
        "failed",
        "interrupted",
    ]
    created_at: datetime = Field(default_factory=now)
    proposal: Proposal | None = None
    reason: str = ""
    trajectory: list[float] = Field(default_factory=list)
    origin: Literal["manual", "automation"] = "manual"


class Receipt(Contract):
    command_id: str
    plant_id: str
    digest: str
    revision: int
    recovered: bool
    trajectory: list[float]
    verification: Literal["completed", "pending"] = "completed"


class WorldEvent(Contract):
    """A live injection into one plant: a fault or a business event (shared lifecycle)."""

    id: str = Field(default_factory=lambda: f"evt-{uuid4().hex[:12]}")
    plant_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    domain: Literal["fault", "business"] = "fault"
    severity: float = Field(default=0.7, ge=0, le=1)
    ramp_ticks: int = Field(default=0, ge=0, le=10_000)
    duration_ticks: int | None = Field(default=None, ge=1, le=1_000_000)
    state: Literal["ramping", "active", "cleared"] = "ramping"
    started_tick: int = Field(default=0, ge=0)
    cleared_tick: int | None = None
    cleared_by: Literal["duration", "operator", "remedy", "reset"] | None = None
    applied: float = 0
    created_at: datetime = Field(default_factory=now)


class WorldStatus(Contract):
    plant_id: str
    running: bool
    interval_seconds: float
    tick: int
    sim_seconds: float
    active_events: int
    kill_after_seconds: float = 0
    kill_seconds_left: float | None = None
    kill_tripped: bool = False


class Order(Contract):
    id: str
    product: str
    quantity_t: float = Field(gt=0)
    due_sim_seconds: float = Field(ge=0)
    priority: Literal[1, 2, 3] = 2
    penalty_per_t: float = Field(default=0, ge=0)
    filled_t: float = Field(default=0, ge=0)
    status: Literal["open", "fulfilled", "late"] = "open"
    source: Literal["baseline", "demand_surge", "rush_order"] = "baseline"


class BusinessState(Contract):
    """Simulated business ledger for one plant; placeholder factors, not accounting data."""

    plant_id: str
    last_tick: int = 0
    order_seq: int = 0
    orders: list[Order] = Field(default_factory=list)
    raw_material_t: float = Field(default=0, ge=0)
    finished_goods_t: float = Field(default=0, ge=0)
    spares: dict[str, int] = Field(default_factory=dict)
    pending_spares: dict[str, int] = Field(default_factory=dict)
    processed_events: list[str] = Field(default_factory=list)
    next_delivery_tick: int = 0
    downtime_until_tick: int = 0
    downtime_ticks: int = 0
    produced_t: float = 0
    scrap_t: float = 0
    fuel_gj: float = 0
    electricity_kwh: float = 0
    co2e_kg: float = 0
    energy_cost: float = 0
    revenue: float = 0
    penalty_cost: float = 0


class BusinessMetrics(Contract):
    basis: str = "Simulated model with placeholder factors; not plant accounting."
    nominal_rate_tph: float
    production_rate_tph: float
    good_rate_tph: float
    availability: float
    in_band_factor: float
    scrap_fraction: float
    fuel_gj_per_h: float
    electricity_kw: float
    co2e_kg_per_h: float
    specific_energy_gj_per_t: float
    tariff_multiplier: float
    energy_cost_per_h: float
    raw_cover_hours: float
    orders_at_risk: int
    open_orders: int


class ChannelReading(Contract):
    channel: str
    name: str
    equipment: str
    modality: Literal["waveform", "scalar", "event"]
    unit: str
    value: float
    nominal: float
    low: float | None = None
    high: float | None = None
    status: Literal["normal", "high", "low"] = "normal"
    basis: str = "Simulated channel generated from plant state and active events."


class SignalFeatures(Contract):
    channel: str
    tick: int
    samples: int
    rate_hz: float
    rms: float
    peak: float
    crest: float
    kurtosis: float
    dominant_hz: float
    basis: str = "Simulated waveform features; no recorded sensor data."


class Detection(Contract):
    camera: str
    label: str
    confidence: float = Field(ge=0, le=1)
    severity: float = Field(ge=0, le=1)
    box: tuple[float, float, float, float]  # x, y, w, h as fractions of the frame
    model: str = "simulated-detector"
    trained_model: bool = False


class Zone(Contract):
    id: str
    name: str
    kind: Literal["dock", "process", "hot", "safe"]
    equipment: list[str] = Field(default_factory=list)
    next_to: list[str] = Field(default_factory=list)


class Robot(Contract):
    id: str
    name: str
    kind: Literal["inspector", "maintainer", "carrier"]
    zone: str
    battery: float = Field(default=100, ge=0, le=100)
    status: Literal["docked", "idle", "moving", "working", "charging", "fault"] = "docked"
    tools: list[str] = Field(default_factory=list)
    mission_id: str | None = None


class FleetState(Contract):
    plant_id: str
    zones: list[Zone]
    robots: list[Robot]
    lockouts: list[str] = Field(default_factory=list)
    last_maintenance: dict[str, int] = Field(default_factory=dict)
    basis: str = "Simulated fleet on a zone graph; no physical robots."


CoreName = Literal["learning", "vision", "robot", "optimization"]
AlertLevel = Literal["info", "watch", "notify", "escalate"]
BusKind = Literal["read_signal_evidence", "read_detections", "read_fleet_state"]


class CoreAlert(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    plant_id: str
    core: CoreName
    level: AlertLevel
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1200)
    confidence: float = Field(ge=0, le=1)
    equipment: str | None = None
    evidence: list[str] = Field(default_factory=list, max_length=10)
    revision: int = Field(ge=0)
    tick: int = Field(ge=0)


class CoreReport(Contract):
    """What one core currently believes. Stamped with revision and time so age is visible."""

    plant_id: str
    core: CoreName
    revision: int = Field(ge=0)
    tick: int = Field(ge=0)
    observed_at: datetime = Field(default_factory=now)
    status: Literal["normal", "watch", "alert"] = "normal"
    summary: str = Field(min_length=1, max_length=2000)
    alerts: list[CoreAlert] = Field(default_factory=list)
    assessment: dict = Field(default_factory=dict)
    source: Literal["monitor", "reference", "agent"] = "monitor"
    model: str = "simulated-monitor"
    trained_model: bool = False
    degraded: bool = False


class BusRequest(Contract):
    id: str = Field(default_factory=lambda: f"req-{uuid4().hex[:12]}")
    correlation_id: str = Field(min_length=1, max_length=80)
    plant_id: str
    from_core: CoreName
    to_core: CoreName
    kind: BusKind
    target: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    question: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=0)
    expires_at: datetime
    chain: list[CoreName] = Field(default_factory=list, max_length=4)


class BusResponse(Contract):
    request_id: str
    status: Literal["ok", "refused"]
    reason: str = ""
    evidence: dict = Field(default_factory=dict)
    answered_at: datetime = Field(default_factory=now)


class CoreConfig(Contract):
    plant_id: str
    core: CoreName
    masked: dict[str, int] = Field(default_factory=dict)  # channel -> tick until which it is masked
    sensitivity: float = Field(default=1.0, ge=0.5, le=1.5)


class Mission(Contract):
    id: str = Field(default_factory=lambda: f"mis-{uuid4().hex[:12]}")
    plant_id: str
    robot_id: str
    kind: Literal["inspect", "verify", "sample", "patrol", "transport", "lockout", "unlock"]
    tier: Literal["T0", "T1", "T2-prep"]
    tool: str = ""
    target: str = ""
    zone: str = ""
    status: Literal["completed", "refused"] = "completed"
    steps: list[str] = Field(default_factory=list)
    result: dict = Field(default_factory=dict)
    tick: int = 0
    battery_used: float = 0
    created_at: datetime = Field(default_factory=now)


class CoreRun(Contract):
    """One agent run by a core: analysis for a question or alert, or execution of an order."""

    id: str = Field(default_factory=lambda: f"run-{uuid4().hex[:12]}")
    plant_id: str
    core: CoreName
    kind: Literal["analysis", "order"]
    status: Literal["running", "completed", "interrupted", "failed", "timeout"] = "running"
    detail: str = Field(default="", max_length=300)
    started_at: datetime = Field(default_factory=now)
    ended_at: datetime | None = None


class ActionOrder(Contract):
    """An approved proposal handed to the owning core, with the envelope it must stay inside."""

    id: str = Field(default_factory=lambda: f"ord-{uuid4().hex[:12]}")
    incident_id: str
    plant_id: str
    core: CoreName
    control: Literal["thermal_duty", "maintenance", "monitor_config"]
    status: Literal["running", "completed", "refused", "failed", "interrupted"] = "running"
    objective: str = Field(default="", max_length=300)
    expires_at: datetime
    command_ids: list[str] = Field(default_factory=list)
    followups: int = 0
    pending_followup: Proposal | None = None
    replanned: Proposal | None = None  # set when the plan was re-sized from the live state
    result: str = ""
    baseline: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now)


class KpiSample(Contract):
    plant_id: str
    tick: int = Field(ge=0)
    sim_seconds: float = Field(ge=0)
    oee: float
    availability: float
    performance: float
    quality: float
    production_rate_tph: float
    good_rate_tph: float
    energy_cost_per_h: float
    co2e_kg_per_h: float
    orders_at_risk: int
    deviation: float


class ImpactRecord(Contract):
    """What an incident's action achieved, compared with the twin's no-action forecast."""

    id: str
    plant_id: str
    control: Literal["thermal_duty", "maintenance", "monitor_config"]
    outcome: Literal["resolved", "escalated", "failed", "interrupted"]
    started_tick: int = Field(ge=0)
    ended_tick: int = Field(ge=0)
    elapsed_ticks: int = Field(ge=0)
    baseline: dict = Field(default_factory=dict)
    actual: dict = Field(default_factory=dict)
    deltas: dict = Field(default_factory=dict)
    projected: dict | None = None
    basis: str = "Simulated comparison with the twin's no-action forecast; placeholder prices."
    created_at: datetime = Field(default_factory=now)


class WorkOrder(Contract):
    id: str = Field(default_factory=lambda: f"wo-{uuid4().hex[:10]}")
    plant_id: str
    equipment: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    remedy: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=160)
    status: Literal["open", "in_progress", "completed", "cancelled"] = "open"
    priority: Literal[1, 2, 3] = 2
    source: Literal["alert", "order", "recommendation", "operator"] = "operator"
    source_ref: str = Field(default="", max_length=120)
    part: str | None = None
    est_hours: float = 0
    est_cost: float = 0
    created_tick: int = 0
    completed_tick: int | None = None
    note: str = Field(default="", max_length=300)
    created_at: datetime = Field(default_factory=now)
    basis: str = "Simulated work order; costs are placeholders."


class Recommendation(Contract):
    id: str
    plant_id: str
    kind: Literal["repair", "spare_reorder", "orders_at_risk", "energy_saving"]
    title: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=600)
    expected_value: float
    urgency: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=1)
    actions: list[str] = Field(default_factory=list, max_length=4)
    evidence: list[str] = Field(default_factory=list, max_length=6)
    blocked: str = ""
    tick: int = 0
    basis: str = "Simulated value in placeholder currency; not a financial forecast."


class RecommendationDecision(Contract):
    id: str
    status: Literal["dismissed", "accepted"]
    decided_at: datetime = Field(default_factory=now)
