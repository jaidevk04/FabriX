"""Scoped, budgeted tools shared by native harnesses and the process bridge.

Discovery is lexical capability matching, not semantic search. No control
writer is included in the agent toolset. Each run sees one immutable snapshot.
"""

from collections.abc import Callable
from copy import deepcopy
from threading import Lock
from typing import Any

from cognition.capabilities.registry import Registry
from cognition.config import tool_cap
from cognition.cores.optimization.objectives import GOALS, optimize
from cognition.cores.registry import SPECS
from cognition.cores.runs import CoreBusy, RunStopped
from cognition.cores.views import view
from cognition.domain import SECONDS_PER_TICK, Action, Control, Request, now, sim_clock
from cognition.industries import TOOL_BINDINGS, get_industry
from cognition.insights.kpi import kpis, sustainability
from cognition.layers.cognitive import skills
from cognition.layers.perceptual.indicators import process_indicators
from cognition.layers.perceptual.service import Perception
from cognition.layers.reflexive import assess as reflexive_status
from cognition.persistence.store import Store
from cognition.simulation.thermal import PACKS, advance, check_action, simulate


class Tools:
    def __init__(
        self,
        request: Request,
        store: Store,
        budget: int | None = None,
        *,
        perceptual: dict | None = None,
        services: Any = None,
    ) -> None:
        self.request = request.model_copy(deep=True)
        self.store = store
        self.budget = tool_cap() if budget is None else budget
        # The platform, when attached, gives read access to cores and business views. Core
        # reports are frozen here so one incident reasons over one consistent picture.
        self.services = services
        self.core_reports = (
            [r.model_dump(mode="json") for r in services.cores.reports(request.snapshot.spec.id)]
            if services is not None
            else []
        )
        self.calls = 0
        self.lock = Lock()
        self.perceptual = deepcopy(
            perceptual
            if perceptual is not None
            else Perception(store).assess(self.request.snapshot)
        )

    def record(self, name: str, args: dict) -> None:
        with self.lock:
            if self.calls >= self.budget:
                raise PermissionError("Tool budget exhausted")
            self.calls += 1
        self.store.audit(self.request.incident_id, "tool_called", {"name": name, "args": args})

    def emit(self, text: str) -> None:
        """Record public response text; not exposed as an agent tool."""
        self.store.audit(self.request.incident_id, "agent_text", {"text": text})

    def discover(self, query: str = "") -> list[dict]:
        """Discover approved connector, tool, agent-role and control capabilities."""
        self.record("discover", {"query": query})
        return Registry(self.store).discover(
            self.request.snapshot.spec.id, query, self.request.snapshot
        )

    def read_snapshot(self) -> dict:
        """Read the immutable, revisioned snapshot assigned to this incident."""
        self.record("read_snapshot", {})
        return self.request.snapshot.model_dump(mode="json") | {
            "process_indicators": {
                "basis": "Derived model estimates, not independent sensors or control limits.",
                "indicators": [
                    value.model_dump(mode="json")
                    for value in process_indicators(self.request.snapshot)
                ],
            }
        }

    def read_time(self) -> dict:
        """Read simulated process time, wall-clock time, telemetry age and forecast horizon."""
        self.record("read_time", {})
        snapshot = self.request.snapshot
        current = now()
        return {
            "simulated_elapsed_seconds": snapshot.sim_seconds,
            "simulated_clock": sim_clock(snapshot.sim_seconds),
            "tick": snapshot.tick,
            "seconds_per_tick": SECONDS_PER_TICK,
            "forecast_ticks": 60,
            "forecast_horizon_seconds": 60 * SECONDS_PER_TICK,
            "recovery_window_seconds": 10 * SECONDS_PER_TICK,
            "wall_clock_utc": current.isoformat(),
            "sampled_at": snapshot.sampled_at.isoformat(),
            "telemetry_age_seconds": (current - snapshot.sampled_at).total_seconds(),
            "proposal_expiry_limit_seconds": 120,
            "note": (
                "Simulated time is an illustrative scale. Proposal expiry and telemetry "
                "freshness use wall-clock time."
            ),
        }

    def read_instruments(self) -> dict:
        """Read simulator-derived process instruments with units, bands and conditions."""
        self.record("read_instruments", {})
        snapshot = self.request.snapshot
        return {
            "plant_id": snapshot.spec.id,
            "revision": snapshot.revision,
            "simulated_elapsed_seconds": snapshot.sim_seconds,
            "basis": "Derived model estimates, not independent sensors or control limits.",
            "indicators": [value.model_dump(mode="json") for value in process_indicators(snapshot)],
        }

    def forecast_instruments(self, value: float) -> dict:
        """Forecast instrument values over simulated time for a candidate duty, on a copy."""
        self.record("forecast_instruments", {"value": value})
        shadow = self.request.snapshot.model_copy(deep=True)
        check_action(shadow, Action(value=value))
        shadow.duty = value
        points = []
        for _ in range(10):
            shadow, _trajectory = advance(shadow, 6)
            points.append(
                {
                    "simulated_elapsed_seconds": shadow.sim_seconds,
                    "values": {i.id: i.value for i in process_indicators(shadow)},
                }
            )
        return {
            "duty": value,
            "start_seconds": self.request.snapshot.sim_seconds,
            "points": points,
            "basis": "Twin copy forecast; no control is applied.",
        }

    def read_control(self) -> dict:
        """Read permitted control units, bounds, change limits and operating mode."""
        self.record("read_control", {})
        return Control().model_dump() | {
            "other_controls": [
                {
                    "name": "maintenance",
                    "unit": "work_order",
                    "how": "Propose MaintenanceAction(equipment, remedy). The gateway checks a "
                    "matching fault, a spare in stock, cooldown, interlock and twin effect; the "
                    "robot core locks out, repairs and unlocks.",
                }
            ]
        }

    def read_layers(self) -> dict:
        """Read reflexive policy, qualified perceptual evidence and conflicts."""
        self.record("read_layers", {})
        return {
            "reflexive": reflexive_status(self.request.snapshot),
            "perceptual": self.perceptual,
            "cognitive": {
                "role": "supervisor",
                "authority": (
                    "Propose only; independent gateway and configured approval govern actuation."
                ),
            },
        }

    def list_skills(self) -> list[dict]:
        """List skills available to this incident with their descriptions and resources."""
        self.record("list_skills", {})
        return skills.summaries(self.request.snapshot.spec.industry)

    def read_skill(self, name: str) -> dict:
        """Load one available skill body, on demand. Skills give procedure, never authority."""
        self.record("read_skill", {"name": name})
        return {"name": name, "content": skills.read(self.request.snapshot.spec.industry, name)}

    def read_skill_resource(self, name: str, path: str) -> dict:
        """Read one file under a skill's references, assets or scripts folder."""
        self.record("read_skill_resource", {"name": name, "path": path})
        industry = self.request.snapshot.spec.industry
        return {"name": name, "path": path, "content": skills.read_file(industry, name, path)}

    def _services(self) -> Any:
        if self.services is None:
            raise PermissionError("Core services are not attached to this incident")
        return self.services

    def _revision(self) -> int:
        return self._services().store.plant(self.request.snapshot.spec.id).revision

    def _unknown_core(self, core: str) -> dict | None:
        if core in SPECS:
            return None
        return {
            "status": "error",
            "error": f"Unknown core '{core}'",
            "hint": f"Use one of: {', '.join(SPECS)}.",
        }

    def read_core_live(self, core: str, scope: str = "", response_format: str = "concise") -> dict:
        """Read a core's current monitor state. Fast, no model. Stamped with revision and age."""
        self.record("read_core_live", {"core": core, "scope": scope})
        if (error := self._unknown_core(core)) is not None:
            return error
        report = self._services().cores.live(self.request.snapshot.spec.id, core)
        return view(report, self._revision(), scope, response_format)

    def read_core_reports(self) -> dict:
        """Read the core reports frozen when this incident started, with their age."""
        self.record("read_core_reports", {})
        return {
            "frozen_at_revision": self.request.snapshot.revision,
            "reports": self.core_reports,
            "note": "Reports do not update during the incident; use read_core_live for now.",
        }

    async def ask_core(self, core: str, question: str, response_format: str = "concise") -> dict:
        """Ask a core to analyse. Slower than read_core_live. Asking the robot core may run an
        automatic T0 verification inspection. It never orders repairs."""
        self.record("ask_core", {"core": core, "question": question[:200]})
        if (error := self._unknown_core(core)) is not None:
            return error
        if not question.strip() or len(question) > 500:
            return {
                "status": "error",
                "error": "Question must be 1 to 500 characters",
                "hint": "Ask one focused question about the evidence.",
            }
        plant_id = self.request.snapshot.spec.id
        try:
            report = await self._services().cores.analyse(plant_id, core, question)
        except CoreBusy:
            return {
                "status": "error",
                "error": f"The {core} core is busy with another run",
                "hint": "Use read_core_live now, or ask again after it finishes.",
            }
        except RunStopped:
            return {
                "status": "error",
                "error": "The operator stopped this core run",
                "hint": "Continue with the evidence you have, or escalate.",
            }
        self.store.audit(
            self.request.incident_id, "core_answer", {"core": core, "source": report.source}
        )
        return view(report, self._revision(), "", response_format)

    def request_optimization(self, goal: str = "recovery", max_duty_change: float = 20.0) -> dict:
        """Ask the optimization core for ranked duty candidates with trade-offs. No commands."""
        self.record("request_optimization", {"goal": goal, "max_duty_change": max_duty_change})
        if goal not in GOALS:
            return {
                "status": "error",
                "error": f"Unknown goal '{goal}'",
                "hint": f"Use one of: {', '.join(GOALS)}.",
            }
        result = optimize(self._services(), self.request.snapshot, goal, max(0.0, max_duty_change))
        result["note"] = "Forecasts on the frozen snapshot; the gateway validates any action."
        return result

    def _business(self) -> dict:
        return self._services().business.read(self.request.snapshot.spec.id)

    def read_business(self) -> dict:
        """Read simulated production, orders, inventory and spare availability."""
        self.record("read_business", {})
        data = self._business()
        orders = sorted(data["ledger"].orders, key=lambda o: o.due_sim_seconds)[:5]
        return {
            "tick": data["tick"],
            "metrics": data["metrics"].model_dump(mode="json"),
            "next_orders": [o.model_dump(mode="json") for o in orders],
            "raw_material_t": round(data["ledger"].raw_material_t, 1),
            "finished_goods_t": round(data["ledger"].finished_goods_t, 1),
            "spares_available": data["spares_available"],
            "spare_lead_hours": data["spare_lead_hours"],
            "remedy_spare": data["remedy_spare"],
        }

    def read_kpis(self) -> dict:
        """Read OEE, orders at risk and production totals from the simulated business model."""
        self.record("read_kpis", {})
        data = self._business()
        return {"tick": data["tick"]} | kpis(data["metrics"], data["ledger"])

    def read_sustainability(self) -> dict:
        """Read energy, fuel, CO2e and cost rates and totals (placeholder factors)."""
        self.record("read_sustainability", {})
        data = self._business()
        return {"tick": data["tick"]} | sustainability(data["metrics"], data["ledger"])

    def read_industry_process(self, industry: str, tool_name: str) -> dict:
        if industry != self.request.snapshot.spec.industry:
            raise PermissionError("Industry tool is outside incident scope")
        self.record(tool_name, {})
        profile = get_industry(self.request.snapshot.spec.industry).PROFILE
        return {
            "industry": industry,
            "process": profile.name,
            "snapshot": self.request.snapshot.model_dump(mode="json"),
            "reflexive": reflexive_status(self.request.snapshot),
            "perceptual": self.perceptual,
            "implemented_controls": [Control().model_dump()],
        }

    def simulate_industry_action(self, industry: str, tool_name: str, value: float) -> dict:
        if industry != self.request.snapshot.spec.industry:
            raise PermissionError("Industry tool is outside incident scope")
        return self._simulate(value, tool_name)

    def read_sop(self) -> dict:
        """Read the industry demo procedure and temperature recovery criteria."""
        self.record("read_sop", {})
        pack = PACKS[self.request.snapshot.spec.industry]
        return {
            "asset": pack.asset,
            "temperature_unit": "degC",
            "band": pack.band,
            "time_basis": f"Each tick is {SECONDS_PER_TICK:g} simulated seconds; call read_time.",
            "procedure": [
                "Escalate on invalid telemetry or manual mode.",
                "Read control limits; test bounded duty adjustments.",
                "Require ten consecutive final readings inside operating band.",
                "Escalate if no permitted action can recover.",
            ],
            "validity": "Educational model; no physical plant authority.",
        }

    def simulate_action(self, value: float) -> dict:
        """Forecast a thermal-duty percentage on a copy, without executing controls."""
        return self._simulate(value, "simulate_action")

    def _simulate(self, value: float, name: str) -> dict:
        self.record(name, {"value": value})
        result = simulate(self.request.snapshot, Action(value=value)).model_dump()
        self.store.audit(
            self.request.incident_id,
            "tool_result",
            {
                "name": name,
                "value": value,
                "safe": result["safe"],
                "recovered": result["recovered"],
                "final_error": result["final_error"],
            },
        )
        return result

    def functions(self) -> list[Callable[..., Any]]:
        functions: list[Callable[..., Any]] = [
            self.discover,
            self.read_snapshot,
            self.read_time,
            self.read_instruments,
            self.forecast_instruments,
            self.read_control,
            self.read_sop,
            self.simulate_action,
            self.read_layers,
            self.list_skills,
            self.read_skill,
            self.read_skill_resource,
        ]
        functions.extend(TOOL_BINDINGS[self.request.snapshot.spec.industry](self))
        if self.services is not None:
            functions.extend(
                [
                    self.read_core_live,
                    self.ask_core,
                    self.read_core_reports,
                    self.request_optimization,
                    self.read_business,
                    self.read_kpis,
                    self.read_sustainability,
                ]
            )
        if any(
            value["approved"] and self.request.snapshot.spec.id in value["plant_ids"]
            for value in self.store.records("specialists")
        ):
            functions.append(self.delegate_specialist)
        return functions

    async def delegate_specialist(self, specialist_id: str, objective: str) -> dict:
        """Request advisory analysis from an explicitly approved scoped A2A specialist."""
        from cognition.capabilities.specialists import delegate

        self.record("delegate_specialist", {"specialist_id": specialist_id})
        return await delegate(self.store, self.request, specialist_id, objective)
