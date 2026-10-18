"""Persisted, plant-scoped onboarding manifests and approved capability metadata."""

from typing import Literal

from pydantic import Field, model_validator

from cognition.domain import Contract, Control, PlantSpec, State
from cognition.industries import get_industry
from cognition.layers.perceptual.indicators import DEFINITIONS
from cognition.persistence.store import Store
from cognition.simulation.thermal import PACKS


class AssetMapping(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)


class SignalMapping(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    source: str = Field(min_length=1, max_length=100)
    unit: str = Field(max_length=30)
    basis: Literal["simulated", "estimate"] = "simulated"


class Manifest(Contract):
    plant: PlantSpec
    connector: Literal["twin"] = "twin"
    assets: list[AssetMapping] = Field(min_length=1, max_length=100)
    signals: list[SignalMapping] = Field(min_length=1, max_length=100)
    controls: list[Control] = Field(default_factory=lambda: [Control()], min_length=1, max_length=1)

    @model_validator(mode="after")
    def validate_mappings(self):
        if len({asset.id for asset in self.assets}) != len(self.assets):
            raise ValueError("Duplicate asset mappings")
        if len({signal.name for signal in self.signals}) != len(self.signals):
            raise ValueError("Duplicate signal mappings")
        allowed = {"temperature", "target", "duty", "actuator"} | {
            f"indicators.{definition.id}" for definition in DEFINITIONS[self.plant.industry]
        }
        if any(signal.source not in allowed for signal in self.signals):
            raise ValueError("Signal source is not implemented by the twin connector")
        units = {"temperature": "degC", "target": "degC", "duty": "percent", "actuator": "percent"}
        units.update(
            {
                f"indicators.{definition.id}": definition.unit
                for definition in DEFINITIONS[self.plant.industry]
            }
        )
        aliases = {
            "degC": {"degC", "°C"},
            "°C": {"degC", "°C"},
            "percent": {"percent", "%"},
            "%": {"percent", "%"},
        }
        for signal in self.signals:
            expected = units[signal.source]
            if signal.unit not in aliases.get(expected, {expected}):
                raise ValueError("Signal unit does not match its connector source")
            if signal.source.startswith("indicators.") and signal.basis != "estimate":
                raise ValueError("Derived indicator mappings must be labelled estimates")
        if self.controls != [Control()]:
            raise ValueError(
                "The twin connector currently supports the standard thermal-duty control"
            )
        return self


class Capability(Contract):
    id: str
    plant_id: str
    kind: Literal["connector", "tool", "agent", "control"]
    name: str
    description: str
    transport: Literal["local", "mcp", "a2a"] = "local"
    approved: bool = True
    read_only: bool = True
    metadata: dict = Field(default_factory=dict)


def default_manifest(spec: PlantSpec) -> Manifest:
    return Manifest(
        plant=spec,
        assets=[AssetMapping(id="process", name=PACKS[spec.industry].asset)],
        signals=[
            SignalMapping(name=name, source=name, unit=unit)
            for name, unit in [
                ("temperature", "degC"),
                ("target", "degC"),
                ("duty", "percent"),
                ("actuator", "percent"),
            ]
        ]
        + [
            SignalMapping(
                name=definition.id,
                source=f"indicators.{definition.id}",
                unit=definition.unit,
                basis="estimate",
            )
            for definition in DEFINITIONS[spec.industry]
        ],
    )


class Registry:
    def __init__(self, store: Store):
        self.store = store

    def register(self, manifest: Manifest) -> None:
        plant_id = manifest.plant.id
        self.store.put("manifests", plant_id, manifest)
        definitions = [
            (
                "connector",
                "twin",
                "Read simulator measurements and dispatch gateway-authorized commands",
                "local",
                True,
            ),
            ("tool", "discover", "Find registered approved capabilities", "mcp", True),
            (
                "tool",
                "read_snapshot",
                "Read scoped temperature duty quality and process context",
                "mcp",
                True,
            ),
            ("tool", "read_time", "Read simulated process time and forecast horizon", "mcp", True),
            ("tool", "read_instruments", "Read simulated process instruments", "mcp", True),
            (
                "tool",
                "forecast_instruments",
                "Forecast process instruments over simulated time",
                "mcp",
                True,
            ),
            ("tool", "read_control", "Read thermal control limits and units", "mcp", True),
            ("tool", "read_sop", "Read recovery operating procedures", "mcp", True),
            ("tool", "simulate_action", "Predict a candidate action on a twin copy", "mcp", True),
            (
                "agent",
                "process_investigator",
                "Local investigator role supplied by the selected harness",
                "local",
                True,
            ),
            (
                "control",
                "thermal_duty",
                "Gateway-only thermal input percent control",
                "local",
                False,
            ),
            (
                "control",
                "maintenance",
                "Gateway-validated repair work order carried out by the robot core",
                "local",
                False,
            ),
        ]
        profile = get_industry(manifest.plant.industry).PROFILE
        definitions.extend(
            [
                (
                    "tool",
                    "read_layers",
                    "Read reflexive status, qualified perception and conflicts",
                    "mcp",
                    True,
                ),
                ("tool", "list_skills", "List skills available to the incident", "mcp", True),
                ("tool", "read_core_live", "Read a core's current monitor state", "mcp", True),
                ("tool", "ask_core", "Ask a core agent or analyser to analyse", "mcp", True),
                ("tool", "read_core_reports", "Read core reports frozen at start", "mcp", True),
                ("tool", "request_optimization", "Rank duty candidates on the twin", "mcp", True),
                ("tool", "read_business", "Read simulated orders and inventory", "mcp", True),
                ("tool", "read_kpis", "Read OEE and orders at risk", "mcp", True),
                ("tool", "read_sustainability", "Read energy, fuel and CO2e", "mcp", True),
                ("tool", "read_skill", "Read an available skill on demand", "mcp", True),
                (
                    "tool",
                    "read_skill_resource",
                    "Read a skill reference, asset or script file",
                    "mcp",
                    True,
                ),
                (
                    "tool",
                    profile.read_tool,
                    f"Read {profile.name} instruments and evidence",
                    "mcp",
                    True,
                ),
                (
                    "tool",
                    profile.simulate_tool,
                    f"Test permitted {profile.name} duty on the twin",
                    "mcp",
                    True,
                ),
                (
                    "tool",
                    "apply_validated_action",
                    "Private platform executor; gateway validation and approval required",
                    "mcp",
                    False,
                ),
            ]
        )
        for kind, name, description, transport, read_only in definitions:
            capability = Capability(
                id=f"{plant_id}:{kind}:{name}",
                plant_id=plant_id,
                kind=kind,
                name=name,
                description=description,
                transport=transport,
                read_only=read_only,
                metadata={
                    "connector": manifest.connector,
                    "industry": manifest.plant.industry,
                    "control": Control().model_dump() if kind == "control" else None,
                    "authority": "platform_executor"
                    if name == "apply_validated_action"
                    else "cognitive_advisory",
                    "sdk": "modelcontextprotocol/python-sdk" if transport == "mcp" else None,
                    "skill": profile.skill,
                },
            )
            self.store.put("capabilities", capability.id, capability)

    def ensure(self, state: State) -> None:
        try:
            manifest = Manifest.model_validate_json(self.store.get("manifests", state.spec.id))
        except KeyError:
            self.register(default_manifest(state.spec))
        else:
            # Backfill new standard tool metadata without touching specialist approval.
            try:
                self.store.get("capabilities", f"{state.spec.id}:control:maintenance")
            except KeyError:
                self.register(manifest)

    def discover(self, plant_id: str, query: str = "", snapshot: State | None = None) -> list[dict]:
        self.ensure(snapshot or self.store.plant(plant_id))
        words = query.lower().split()
        return [
            value
            for value in self.store.records("capabilities")
            if value["plant_id"] == plant_id
            and value["approved"]
            and (not words or any(word in str(value).lower() for word in words))
        ]
