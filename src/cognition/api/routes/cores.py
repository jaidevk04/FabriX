"""Core routes: live monitor reports and the core audit trail. Unauthenticated, loopback only."""

from fastapi import APIRouter, HTTPException

from cognition.api.context import ApiContext
from cognition.cores.context import CoreContext
from cognition.cores.optimization.objectives import GOALS, optimize
from cognition.cores.optimization.tools.optimization_solve_assignment import (
    optimization_solve_assignment,
)
from cognition.cores.registry import SPECS
from cognition.domain import Mission


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["cores"])
    platform, require = context.platform, context.require

    @router.get("/api/plants/{plant_id}/cores")
    def cores(plant_id: str):
        require(plant_id)
        return [
            {"name": spec.name, "description": spec.description}
            | {"report": platform().cores.live(plant_id, spec.name)}
            for spec in SPECS.values()
        ]

    @router.get("/api/cores/overview")
    def overview():
        """One call for the plant cards: world state, core status and alert counts per plant."""
        result = {}
        for state in platform().store.plants():
            plant_id = state.spec.id
            reports = {s.name: platform().cores.live(plant_id, s.name) for s in SPECS.values()}
            result[plant_id] = {
                "world": platform().world.running(plant_id),
                "cores": {name: report.status for name, report in reports.items()},
                "alerts": sum(len(report.alerts) for report in reports.values()),
            }
        return {"plants": result, "agents": platform().core_agents.status()}

    @router.get("/api/plants/{plant_id}/cores/panel")
    def panel(plant_id: str, after: int = 0):
        """Everything the Cores tab shows, in one request."""
        require(plant_id)
        p = platform()
        state = p.store.plant(plant_id)
        # Core and world audit streams share one global sequence, so one cursor serves both.
        events = sorted(
            p.store.events(f"cores:{plant_id}", after) + p.store.events(f"world:{plant_id}", after),
            key=lambda e: e["seq"],
        )[-80:]
        missions = sorted(
            (
                Mission.model_validate(v)
                for v in p.store.records("missions")
                if str(v.get("id", "")).startswith("mis-") and v["plant_id"] == plant_id
            ),
            key=lambda m: m.created_at,
        )
        work = p.workorders.all(plant_id)
        return {
            "tick": state.tick,
            "revision": state.revision,
            "sim_seconds": state.sim_seconds,
            "world": p.world.status(plant_id),
            "agents": p.core_agents.status(),
            "cores": [
                {
                    "name": s.name,
                    "description": s.description,
                    "report": p.cores.live(plant_id, s.name),
                }
                for s in SPECS.values()
            ],
            "runs": p.core_agents.runs(plant_id),
            "faults": p.faults.events(plant_id, include_cleared=False),
            "signals": p.signals.read_all(plant_id),
            "cameras": p.cameras.summary(plant_id),
            "fleet": p.fleet.state(plant_id),
            "orders": p.orders.all(plant_id)[-6:],
            "missions": missions[-6:],
            "work_orders": [w for w in work if w.status in ("open", "in_progress")]
            + [w for w in work if w.status == "completed"][-3:],
            "events": events,
            "last_seq": events[-1]["seq"] if events else after,
        }

    @router.get("/api/plants/{plant_id}/narration")
    def narration(plant_id: str, after: int = 0):
        """Recent world, core, automation and agent events for the twin's live activity card."""
        require(plant_id)
        store = platform().store
        streams = [f"cores:{plant_id}", f"world:{plant_id}", f"automation:{plant_id}"]
        recent = [i.id for i in store.incidents() if i.plant_id == plant_id][:2]
        events = sorted(
            (e | {"stream": s} for s in streams + recent for e in store.events(s, max(after, 0))),
            key=lambda e: e["seq"],
        )
        last_seq = events[-1]["seq"] if events else max(after, 0)
        if after < 0:  # first call from a page: replay events since the world clock last started
            world = store.events(f"world:{plant_id}")
            starts = [e["seq"] for e in world if e["kind"] == "world_started"]
            floor = starts[-1] if starts else 0
            return {"events": [e for e in events if e["seq"] > floor][-60:], "last_seq": last_seq}
        return {"events": events[-60:], "last_seq": last_seq if events else after}

    @router.get("/api/plants/{plant_id}/cores/events")
    def events(plant_id: str, after: int = 0):
        require(plant_id)
        return platform().store.events(f"cores:{plant_id}", after)

    @router.get("/api/plants/{plant_id}/cores/optimization/candidates")
    def candidates(plant_id: str, goal: str = "balanced", max_change: float = 20.0):
        require(plant_id)
        if goal not in GOALS:
            raise HTTPException(422, f"Unknown goal. Use one of: {', '.join(GOALS)}")
        return optimize(platform(), platform().store.plant(plant_id), goal, max(0.0, max_change))

    @router.get("/api/plants/{plant_id}/cores/optimization/plan")
    def plan(plant_id: str, problem: str = "maintenance_window", equipment: str = ""):
        require(plant_id)
        ctx = CoreContext(platform(), plant_id, "optimization")
        result = optimization_solve_assignment(ctx, problem, equipment)
        if result.get("status") == "error":
            raise HTTPException(422, f"{result['error']}. {result['hint']}")
        return result

    @router.get("/api/cores/agents")
    def agents():
        return platform().core_agents.status()

    @router.get("/api/plants/{plant_id}/cores/runs")
    def runs(plant_id: str):
        require(plant_id)
        return platform().core_agents.runs(plant_id)

    @router.post("/api/plants/{plant_id}/cores/stop")
    def stop_all(plant_id: str):
        """Stop all: terminate every active core run for the plant."""
        require(plant_id)
        stopped = platform().core_agents.stop_all(plant_id)
        platform().store.audit(f"cores:{plant_id}", "core_stop_all", {"stopped": len(stopped)})
        return {"stopped": stopped}

    @router.post("/api/plants/{plant_id}/cores/{core}/stop")
    def stop(plant_id: str, core: str):
        require(plant_id)
        if core not in SPECS:
            raise HTTPException(404, "Core not found")
        run = platform().core_agents.stop(plant_id, core)
        platform().store.audit(
            f"cores:{plant_id}", "core_stop", {"core": core, "stopped": run is not None}
        )
        return {"stopped": [run] if run else []}

    @router.get("/api/plants/{plant_id}/cores/{core}")
    def core(plant_id: str, core: str, analyse: bool = False):
        require(plant_id)
        if core not in SPECS:
            raise HTTPException(404, "Core not found")
        return platform().cores.live(plant_id, core, reference=analyse)

    return router
