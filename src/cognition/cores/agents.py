"""CoreAgents: runs core agents with one run per core per plant, a Stop control and no budgets."""

import asyncio
import importlib
import json
import os
from collections import deque
from collections.abc import Callable
from typing import Any

from cognition.agentkit.adk import run_structured
from cognition.cores._shared.schemas import CoreFinding, OrderResult
from cognition.cores.context import CoreContext
from cognition.cores.executors import OrderRefused
from cognition.cores.runs import CoreBusy, RunStopped
from cognition.domain import ActionOrder, CoreName, CoreReport, CoreRun, Proposal, now
from cognition.harnesses.base import ModelSettings
from cognition.harnesses.errors import HarnessFailure

TRUE = ("1", "true", "yes", "on")


def to_report(finding: CoreFinding, monitor: CoreReport, model: str) -> CoreReport:
    return CoreReport(
        plant_id=monitor.plant_id,
        core=monitor.core,
        revision=monitor.revision,
        tick=monitor.tick,
        status=finding.status,
        summary=finding.summary,
        alerts=monitor.alerts,
        assessment=monitor.assessment
        | {
            "findings": [item.model_dump() for item in finding.findings],
            "next_checks": finding.next_checks,
            "confidence": finding.confidence,
        },
        source="agent",
        model=model,
    )


class CoreAgents:
    def __init__(self, platform) -> None:
        self.platform = platform
        self.override: bool | None = None  # tests and demos may force on or off
        self.model_factory: Callable[[str, str], Any] | None = None
        self.active: dict[tuple[str, str], tuple[CoreRun, asyncio.Task]] = {}
        self.stopping: set[str] = set()
        self.preempted: set[str] = set()  # analysis runs stopped to make room for an order
        self.history: deque[CoreRun] = deque(maxlen=50)
        self.background: set[asyncio.Task] = set()

    # Configuration

    @property
    def enabled(self) -> bool:
        if self.override is not None:
            return self.override
        return os.getenv("COGNITION_CORE_AGENTS", "").lower() in TRUE

    def ceiling(self) -> float:
        try:
            return max(0.0, float(os.getenv("COGNITION_CORE_RUN_SECONDS", "600")))
        except ValueError:
            return 600.0

    def available(self) -> tuple[bool, str]:
        """Whether agents can run now. Anything else means degraded, with the reference analyser."""
        if not self.enabled:
            return False, "Core agents are disabled; reference analysers answer."
        if self.model_factory is not None:
            return True, ""
        try:
            importlib.import_module("google.adk")
        except ImportError:
            return False, "Google ADK is not installed."
        settings = self._settings()
        try:
            settings.validate()
        except ValueError as error:
            return False, str(error)
        return True, ""

    def _settings(self) -> ModelSettings:
        base = ModelSettings.from_env()
        model = os.getenv("COGNITION_CORE_MODEL", "").strip() or base.model
        return ModelSettings(model, base.vertex, base.project, base.location)

    def status(self) -> dict:
        ok, reason = self.available()
        return {
            "enabled": self.enabled,
            "available": ok,
            "degraded": self.enabled and not ok,
            "reason": reason,
            "model": self._settings().model or None,
            "ceiling_seconds": self.ceiling(),
        }

    def _model(self, core: str, mode: str) -> Any:
        if self.model_factory is not None:
            return self.model_factory(core, mode)
        return self._settings().model

    @staticmethod
    def _builder(core: str):
        return importlib.import_module(f"cognition.cores.{core}.agent").build_agent

    # Run bookkeeping

    def runs(self, plant_id: str) -> list[CoreRun]:
        live = [run for (plant, _), (run, _) in self.active.items() if plant == plant_id]
        past = [run for run in self.history if run.plant_id == plant_id]
        return [*live, *reversed(past)]

    def _emitter(self, plant_id: str, core: str, run: CoreRun, correlation: str):
        """Log each agent step to the per-agent stream the Agent estate page reads."""

        def emit(kind: str, body: dict) -> None:
            self.platform.store.audit(
                f"agent:{plant_id}:{core}",
                kind,
                {"run": run.id, "correlation_id": correlation} | body,
            )

        return emit

    def _start(self, plant_id: str, core: str, kind: str, detail: str, correlation: str) -> CoreRun:
        if (plant_id, core) in self.active:
            raise CoreBusy(f"The {core} core already has a run in progress for this plant")
        run = CoreRun(plant_id=plant_id, core=core, kind=kind, detail=detail[:300])  # type: ignore[arg-type]
        self.platform.store.audit(
            f"cores:{plant_id}",
            "core_run_started",
            {"correlation_id": correlation, "run": run.id, "core": core, "kind": kind},
        )
        return run

    def _finish(self, run: CoreRun, status: str, correlation: str, **extra: Any) -> None:
        run.status, run.ended_at = status, now()  # type: ignore[assignment]
        self.history.append(run)
        self.platform.store.audit(
            f"cores:{run.plant_id}",
            f"core_run_{status}",
            {"correlation_id": correlation, "run": run.id, "core": run.core} | extra,
        )

    async def _watch(self, run: CoreRun, work, correlation: str) -> Any:
        key = (run.plant_id, run.core)
        task = asyncio.ensure_future(work)
        self.active[key] = (run, task)
        ceiling = self.ceiling() or None
        try:
            result = await asyncio.wait_for(task, timeout=ceiling)
        except TimeoutError:
            self._finish(run, "timeout", correlation)
            raise HarnessFailure("timeout") from None
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if run.id in self.stopping and (caller is None or caller.cancelling() == 0):
                self.stopping.discard(run.id)
                source = "preempted-by-order" if run.id in self.preempted else "operator-stop"
                self.preempted.discard(run.id)
                self._finish(run, "interrupted", correlation, source=source)
                raise RunStopped from None
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._finish(run, "interrupted", correlation, source="cancelled")
            raise
        except Exception as error:
            # Never record SDK error text: it can carry credentials.
            self._finish(run, "failed", correlation, type=type(error).__name__)
            raise
        else:
            self._finish(run, "completed", correlation)
            return result
        finally:
            self.active.pop(key, None)

    async def _make_room_for_order(self, plant_id: str, core: CoreName) -> None:
        """An approved order outranks an advisory analysis still running on the same core.

        Monitors wake analyses and the harness asks questions, so the core is often mid-analysis
        when its order arrives. Refusing the order for that ("CoreBusy") failed whole incidents
        after the plan was already approved. The analysis is stopped and recorded as preempted.
        """
        entry = self.active.get((plant_id, core))
        if entry is None or entry[0].kind == "order":
            return
        run, task = entry
        self.stopping.add(run.id)
        self.preempted.add(run.id)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for _ in range(100):  # the analysing caller frees the slot as it unwinds
            if (plant_id, core) not in self.active:
                break
            await asyncio.sleep(0.02)

    # Stop control

    def stop(self, plant_id: str, core: str) -> CoreRun | None:
        entry = self.active.get((plant_id, core))
        if entry is None:
            return None
        run, task = entry
        self.stopping.add(run.id)
        task.cancel()
        return run

    def stop_all(self, plant_id: str) -> list[CoreRun]:
        stopped = [
            self.stop(plant_id, core) for (plant, core) in list(self.active) if plant == plant_id
        ]
        return [run for run in stopped if run is not None]

    async def stop_all_and_wait(self, plant_id: str) -> list[CoreRun]:
        tasks = [task for (plant, _), (_, task) in self.active.items() if plant == plant_id]
        stopped = self.stop_all(plant_id)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)
        return stopped

    async def close(self) -> None:
        for plant_id in {plant for plant, _ in self.active}:
            await self.stop_all_and_wait(plant_id)
        for task in list(self.background):
            task.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)

    # Runs

    async def analyse(
        self, plant_id: str, core: CoreName, question: str, correlation: str = "analysis"
    ) -> CoreReport:
        monitor = self.platform.cores.live(plant_id, core)
        run = self._start(plant_id, core, "analysis", question, correlation)
        ctx = CoreContext(self.platform, plant_id, core, correlation_id=correlation)
        prompt = json.dumps(
            {
                "task": "Analyse and answer the question with a structured finding.",
                "question": question,
                "plant": plant_id,
                "tick": monitor.tick,
                "monitor_report": {
                    "status": monitor.status,
                    "summary": monitor.summary,
                    "alerts": [a.model_dump(mode="json") for a in monitor.alerts],
                },
            }
        )

        async def work() -> CoreFinding:
            model = self._model(core, "analysis")
            names.append(str(getattr(model, "model", model)))
            agent = self._builder(core)(ctx, model, "analysis")
            return await run_structured(
                agent, prompt, CoreFinding, run.id, self._emitter(plant_id, core, run, correlation)
            )

        names: list[str] = []
        finding = await self._watch(run, work(), correlation)
        report = to_report(finding, monitor, names[0] if names else "unknown")
        self.platform.store.audit(
            f"cores:{plant_id}",
            "core_report",
            {"correlation_id": correlation, "core": core, "status": report.status},
        )
        return report

    async def execute_order(self, order: ActionOrder, proposal: Proposal, bound) -> Any:
        """The owning agent decides on one order. The receipt comes from the bound tool only."""
        core = order.core
        await self._make_room_for_order(order.plant_id, core)
        run = self._start(order.plant_id, core, "order", order.objective, order.incident_id)
        ctx = CoreContext(
            self.platform,
            order.plant_id,
            core,
            correlation_id=order.incident_id,
            order=order,
            proposal=proposal,
            bound=bound,
        )
        prompt = json.dumps(
            {
                "task": "Decide on this approved order. Execute it once or refuse with a reason.",
                "order": {"id": order.id, "control": order.control, "objective": order.objective},
                "proposal": proposal.model_dump(mode="json"),
            }
        )

        async def work() -> OrderResult:
            agent = self._builder(core)(ctx, self._model(core, "order"), "order")
            return await run_structured(
                agent,
                prompt,
                OrderResult,
                run.id,
                self._emitter(order.plant_id, core, run, order.incident_id),
            )

        try:
            result = await self._watch(run, work(), order.incident_id)
        except RunStopped:
            if ctx.called and ctx.error is None and ctx.outcome is not None:
                return ctx.outcome  # the command landed before Stop; keep its receipt
            raise
        if ctx.error is not None:
            raise ctx.error
        if not ctx.called:
            reason = result.reason if result.decision == "refused" else "did not execute the order"
            raise OrderRefused(f"The {core} core agent {reason or 'refused the order'}")
        return ctx.outcome

    def wake(self, report: CoreReport, alert) -> None:
        """Start a background analysis when a monitor trips. Needs a running loop."""
        ok, _reason = self.available()
        if not ok or (report.plant_id, report.core) in self.active:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._woken(report.plant_id, report.core, alert))
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    async def _woken(self, plant_id: str, core: CoreName, alert) -> None:
        try:
            report = await self.analyse(
                plant_id, core, f"Alert {alert.id}: {alert.summary}", correlation=alert.id
            )
            self.platform.store.put("core_reports", f"{plant_id}:{core}", report)
        except (RunStopped, CoreBusy, HarnessFailure, asyncio.CancelledError):
            return
        except Exception as error:
            self.platform.store.audit(
                f"cores:{plant_id}", "core_wake_failed", {"type": type(error).__name__}
            )
