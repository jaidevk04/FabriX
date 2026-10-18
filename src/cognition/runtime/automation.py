"""Opt-in, bounded simulator autopilot owned by application lifespan."""

import asyncio
import time
from datetime import datetime
from typing import Literal
from uuid import uuid4

from anyio import CancelScope
from pydantic import Field

from cognition.domain import Contract, Incident, Receipt, now
from cognition.harnesses.factory import create
from cognition.runtime.platform import Platform
from cognition.simulation.thermal import PACKS

FOLLOWUP_EVERY = 20  # verification samples between follow-up corrections


class AutomationConfig(Contract):
    mode: Literal["observe", "supervised", "autopilot"] = "observe"
    harness: str = Field(default="reference", pattern=r"^[a-z][a-z0-9_-]{0,40}$")
    interval_seconds: float = Field(default=2, ge=0.2, le=60)
    max_investigations: int = Field(default=3, ge=1, le=20)
    # Stop the whole run (world clock, agents, robots) once this many investigations are verified.
    stop_when_done: bool = False
    cooldown_seconds: float = Field(default=60, ge=0, le=3600)
    max_verification_steps: int = Field(default=180, ge=20, le=600)


class AutomationState(Contract):
    plant_id: str
    config: AutomationConfig = Field(default_factory=AutomationConfig)
    enabled: bool = False
    phase: Literal[
        "off",
        "observing",
        "planning",
        "awaiting_approval",
        "awaiting_parts",
        "verifying",
        "cooldown",
        "attention",
    ] = "off"
    reason: str = "Manual operation."
    incident_id: str | None = None
    investigations: int = 0
    completed: int = 0  # investigations whose recovery was verified in this run
    run_complete: bool = False
    verification_steps: int = 0
    stable_samples: int = 0
    started_at: datetime | None = None
    last_sample_at: datetime | None = None


class Automation:
    def __init__(self, platform: Platform):
        self.platform = platform
        platform.automation = self  # the kill switch stops automation through this
        self.states: dict[str, AutomationState] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.due: dict[str, float] = {}
        self.cooldown: dict[str, float] = {}
        self.seen_tick: dict[str, int] = {}
        self.clock: asyncio.Task | None = None
        self.harness_factory = create
        for data in platform.store.records("automation"):
            state = AutomationState.model_validate(data)
            if state.enabled:
                state.enabled, state.phase = False, "attention"
                state.reason = (
                    "Automation stopped on restart. Review the last incident before enabling."
                )
            self.states[state.plant_id] = state
            self.save(state)

    def state(self, plant_id: str) -> AutomationState:
        self.platform.store.plant(plant_id)
        return self.states.setdefault(plant_id, AutomationState(plant_id=plant_id))

    def save(self, state: AutomationState):
        self.platform.store.put("automation", state.plant_id, state)

    def enable(self, plant_id: str, config: AutomationConfig) -> AutomationState:
        state = self.state(plant_id)
        if state.enabled or plant_id in self.platform.busy:
            raise ValueError("Plant automation or investigation is already active")
        if config.mode != "observe":
            self.harness_factory(config.harness)  # Validate availability before enabling.
        state = AutomationState(
            plant_id=plant_id,
            config=config,
            enabled=True,
            phase="observing",
            reason="Monitoring fresh simulator samples.",
            started_at=now(),
        )
        self.states[plant_id] = state
        self.due[plant_id] = time.monotonic()
        self.save(state)
        self.platform.store.audit(
            f"automation:{plant_id}", "automation_enabled", config.model_dump()
        )
        return state

    async def disable(self, plant_id: str) -> AutomationState:
        state = self.state(plant_id)
        state.enabled, state.phase = False, "off"
        state.reason = "Automation stopped. Simulator commands already applied remain in effect."
        task = self.tasks.get(plant_id)
        if task and not task.done():
            task.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(task, return_exceptions=True)
        if state.incident_id:
            try:
                incident = Incident.model_validate_json(
                    self.platform.store.get("incidents", state.incident_id)
                )
            except KeyError:
                incident = None
            if incident and incident.status in ("verifying", "awaiting_approval"):
                incident.status, incident.reason = (
                    "interrupted",
                    "Automation stopped before verification completed.",
                )
                self.platform.store.put("incidents", incident.id, incident)
                self.platform.store.audit(incident.id, "cancelled", {"source": "operator"})
        await self.platform.core_agents.stop_all_and_wait(plant_id)
        self.platform.fleet_gateway.recall(plant_id)
        self.save(state)
        self.platform.store.audit(f"automation:{plant_id}", "automation_stopped", {})
        return state

    async def operator_decision(self, plant_id: str, action: str) -> AutomationState:
        """The operator answers a run that escalated: mark it fixed, look again, or dismiss it.

        `fixed` tells the simulator the problem was repaired (active faults are cleared as an
        operator action), closes the escalated incident and puts the agent back on watch.
        `investigate` keeps the faults and puts the agent back on watch for a fresh look.
        `dismiss` only acknowledges the alert and leaves automation off.
        """
        state = self.state(plant_id)
        if state.phase != "attention" or state.enabled:
            raise ValueError("Nothing is waiting for an operator decision")
        if plant_id in self.platform.busy:
            raise ValueError("An investigation is still running for this plant")
        store = self.platform.store
        stream = f"automation:{plant_id}"
        if action == "dismiss":
            state.phase, state.reason = "off", "Alert acknowledged. Automation is off."
            self.save(state)
            store.audit(stream, "attention_dismissed", {})
            return state
        cleared = 0
        if action == "fixed":
            for event in self.platform.faults.events(plant_id, include_cleared=False):
                if event.domain == "fault":
                    self.platform.faults.clear(plant_id, event.id, by="operator")
                    cleared += 1
            self._close_by_operator(state)
        state.enabled, state.phase = True, "observing"
        state.reason = (
            "Operator marked the fault fixed. Watching for a deviation."
            if action == "fixed"
            else "Operator asked for a fresh look. Watching for a deviation."
        )
        state.investigations = state.verification_steps = state.stable_samples = 0
        state.incident_id = None
        self.due[plant_id] = 0.0
        self.cooldown.pop(plant_id, None)
        self.save(state)
        store.audit(
            stream,
            "operator_marked_fixed" if action == "fixed" else "attention_resumed",
            {"cleared": cleared},
        )
        return state

    def _close_by_operator(self, state: AutomationState) -> None:
        if not state.incident_id:
            return
        try:
            incident = Incident.model_validate_json(
                self.platform.store.get("incidents", state.incident_id)
            )
        except KeyError:
            return
        if incident.status == "escalated":
            incident.status, incident.reason = "resolved", "Marked fixed by the operator."
            self.platform.store.put("incidents", incident.id, incident)
            self.platform.store.audit(incident.id, "operator_marked_fixed", {})

    def start(self):
        self.clock = asyncio.create_task(self.run())

    async def close(self):
        if self.clock:
            self.clock.cancel()
            await asyncio.gather(self.clock, return_exceptions=True)
        for plant_id in list(self.states):
            if self.states[plant_id].enabled:
                await self.disable(plant_id)

    async def run(self):
        while True:
            await self.step()
            await asyncio.sleep(0.1)

    def attention(self, state: AutomationState, reason: str):
        state.enabled, state.phase, state.reason = False, "attention", reason
        self.save(state)
        self.platform.store.audit(
            f"automation:{state.plant_id}", "attention_required", {"reason": reason}
        )

    async def step(self, *, force: bool = False):
        for state in list(self.states.values()):
            if not state.enabled or state.plant_id in self.platform.busy:
                continue
            if state.phase == "awaiting_approval":
                assert state.incident_id
                incident = Incident.model_validate_json(
                    self.platform.store.get("incidents", state.incident_id)
                )
                if incident.status == "verifying":
                    state.phase, state.reason = "verifying", incident.reason
                    state.verification_steps = state.stable_samples = 0
                elif incident.status != "awaiting_approval":
                    self.attention(state, incident.reason)
                elif incident.proposal and incident.proposal.expires_at <= now():
                    await self.platform.approve(incident.id, accepted=False, actor="expiry-policy")
                    self.attention(state, "Approval window expired. Start a fresh investigation.")
                continue
            if state.phase == "awaiting_parts":
                snapshot = self.platform.connector.snapshot(state.plant_id)
                ledger = self.platform.business.ledger(snapshot)
                if not ledger.pending_spares:
                    state.phase = "cooldown"
                    state.reason = "Spare delivered. Autopilot starting repair investigation."
                    state.investigations = 0
                    self.cooldown[state.plant_id] = time.monotonic() + 1
                    self.save(state)
                continue
            if state.phase == "planning":
                continue
            if not force and time.monotonic() < self.due.get(state.plant_id, 0):
                continue
            self.due[state.plant_id] = time.monotonic() + state.config.interval_seconds
            try:
                if self.platform.world.running(state.plant_id):
                    # The world clock owns the tick; consume each fresh sample once.
                    snapshot = self.platform.connector.snapshot(state.plant_id)
                    if self.seen_tick.get(state.plant_id) == snapshot.tick:
                        continue
                    self.seen_tick[state.plant_id] = snapshot.tick
                else:
                    snapshot = self.platform.sample(state.plant_id)
            except Exception:
                self.attention(state, "Simulator observation failed. Operator review required.")
                continue
            state.last_sample_at = snapshot.sampled_at
            live_world = self.platform.world.running(state.plant_id)
            # Stuck actuator, bad sensor or manual mode: live mode still investigates (the
            # Gateway refuses actions). An interlock always means no action.
            degraded = snapshot.quality != "good" or snapshot.stuck or snapshot.mode != "automatic"
            if state.phase == "verifying":
                self.verify(state, snapshot)
                if (
                    state.phase == "verifying"
                    and state.stable_samples == 0
                    and state.verification_steps
                    and state.verification_steps % FOLLOWUP_EVERY == 0
                    and state.incident_id
                    and self.stalled(state, snapshot)
                ):
                    # Autopilot corrects on its own; supervised queues it for approval.
                    await self.platform.orders.followup(
                        state.incident_id, autonomous=state.config.mode == "autopilot"
                    )
            elif state.config.mode == "observe":
                state.phase, state.reason = (
                    "observing",
                    "Simulator advancing; agent decisions disabled.",
                )
            elif snapshot.interlock or (degraded and not live_world):
                self.attention(
                    state,
                    "Reflexive interlock, invalid telemetry, stuck actuator or manual mode "
                    "requires operator review.",
                )
            elif time.monotonic() < self.cooldown.get(state.plant_id, 0):
                state.phase = "cooldown"
            elif self.needs_cognitive_review(snapshot) or (live_world and degraded):
                if state.investigations >= state.config.max_investigations:
                    self.attention(
                        state, "Investigation limit reached. Review before starting another run."
                    )
                elif not any(not task.done() for task in self.tasks.values()):
                    state.phase, state.reason = (
                        "planning",
                        "Investigating a process deviation or conflicting qualified evidence.",
                    )
                    state.investigations += 1
                    state.incident_id = str(uuid4())
                    self.tasks[state.plant_id] = asyncio.create_task(self.investigate(state))
            else:
                state.phase, state.reason = (
                    "observing",
                    "Fresh measurements remain inside the recovery band.",
                )
            if (
                state.enabled
                and state.config.stop_when_done
                and state.completed >= state.config.max_investigations
            ):
                await self.complete_run(state)
                continue
            self.save(state)

    async def complete_run(self, state: AutomationState) -> None:
        """Stop-when-done: the requested number of recoveries is verified, so end the whole run."""
        plant_id = state.plant_id
        done, limit = state.completed, state.config.max_investigations
        await self.platform.world.stop(plant_id)
        await self.disable(plant_id)
        state.run_complete = True
        state.reason = (
            f"Run complete: {done} of {limit} investigations verified. "
            "Agents, monitors and robots are stopped."
        )
        self.save(state)
        self.platform.store.audit(
            f"automation:{plant_id}", "run_complete", {"verified": done, "limit": limit}
        )

    def clear_finished(self, plant_id: str) -> None:
        """A reset returns a finished run to the plain stopped state."""
        state = self.states.get(plant_id)
        if state and not state.enabled and state.run_complete:
            state.run_complete, state.reason = False, "Manual operation."
            self.save(state)

    def stalled(self, state: AutomationState, snapshot) -> bool:
        """True when the last verification window made no real progress toward the band."""
        assert state.incident_id
        incident = Incident.model_validate_json(
            self.platform.store.get("incidents", state.incident_id)
        )
        trajectory = incident.trajectory
        if len(trajectory) <= FOLLOWUP_EVERY:
            return False
        now_error = abs(trajectory[-1] - snapshot.target)
        then_error = abs(trajectory[-1 - FOLLOWUP_EVERY] - snapshot.target)
        return now_error > PACKS[snapshot.spec.industry].band and now_error > 0.8 * then_error

    def needs_cognitive_review(self, snapshot) -> bool:
        if abs(snapshot.temperature - snapshot.target) > PACKS[snapshot.spec.industry].band:
            return True
        report = self.platform.perception.assess(snapshot)
        return bool(
            report["conflicts"]
            or any(
                item["status"] == "anomaly" and item["confidence"] >= 0.7
                for item in report["observations"]
            )
        )

    async def investigate(self, state: AutomationState):
        try:
            incident = await self.platform.resolve(
                state.plant_id,
                self.harness_factory(state.config.harness),
                incident_id=state.incident_id,
                live=True,
                approval_required=state.config.mode == "supervised",
            )
            if not state.enabled:
                return
            if incident.status in ("verifying", "awaiting_approval"):
                state.phase, state.reason = incident.status, incident.reason
                state.verification_steps = state.stable_samples = 0
                self.save(state)
            elif state.config.mode == "autopilot":
                reason = incident.reason or ""
                # Auto spare ordering on shortages (unless blocked by a supplier-wide shortage)
                has_shortage_event = any(
                    e.kind == "spare_shortage" and e.state != "cleared"
                    for e in self.platform.faults.events(state.plant_id)
                )
                missing_spare = "inventory" in reason.lower() or "spare" in reason.lower()
                if missing_spare and not has_shortage_event:
                    import re

                    from cognition.business.model import parameters

                    match = re.search(r"needs spare ['\"]([^'\"]+)['\"]", reason)
                    part = match.group(1) if match else None
                    if not part:
                        params = parameters(self.platform.connector.snapshot(state.plant_id))
                        for p in params.spares:
                            if p in reason:
                                part = p
                                break
                    if part:
                        due_tick = self.platform.business.order_spare(
                            state.plant_id, part, lead_ticks=25
                        )
                        lead_s = due_tick - self.platform.connector.snapshot(state.plant_id).tick
                        state.phase = "awaiting_parts"
                        state.reason = (
                            f"Spare '{part}' ordered (arriving in ~{lead_s}s). "
                            "Autopilot will repair on arrival."
                        )
                        self.save(state)
                        return

                # Live drift / re-optimization on conditions changing
                if (
                    "drift" in reason.lower()
                    or "no longer fits" in reason.lower()
                    or "changed during investigation" in reason.lower()
                ):
                    state.phase = "cooldown"
                    state.reason = f"Re-optimizing on live state: {reason}"
                    self.cooldown[state.plant_id] = time.monotonic() + min(
                        state.config.cooldown_seconds, 3.0
                    )
                    self.save(state)
                    return

                self.attention(state, incident.reason)
            else:
                self.attention(state, incident.reason)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.attention(
                state, "Automation investigation failed. Review configuration; no automatic retry."
            )

    def verify(self, state: AutomationState, snapshot):
        assert state.incident_id
        incident = Incident.model_validate_json(
            self.platform.store.get("incidents", state.incident_id)
        )
        if incident.status != "verifying":
            self.attention(state, "Verification incident changed. Operator review required.")
            return
        state.verification_steps += 1
        band = PACKS[snapshot.spec.industry].band
        good = (
            snapshot.quality == "good"
            and not snapshot.stuck
            and not snapshot.interlock
            and snapshot.mode == "automatic"
        )
        state.stable_samples = (
            state.stable_samples + 1
            if good and abs(snapshot.temperature - snapshot.target) <= band
            else 0
        )
        incident.trajectory.append(snapshot.temperature)
        self.platform.store.audit(
            incident.id,
            "measurement",
            {
                "tick": snapshot.tick,
                "revision": snapshot.revision,
                "temperature": snapshot.temperature,
                "duty": snapshot.duty,
                "actuator": snapshot.actuator,
                "interlock": snapshot.interlock,
                "sampled_at": snapshot.sampled_at.isoformat(),
                "stable_samples": state.stable_samples,
            },
        )
        if state.stable_samples >= 10:
            incident.status, incident.reason = (
                "resolved",
                "Verified sustained recovery across ten fresh simulator samples.",
            )
            receipt = Receipt.model_validate_json(self.platform.store.get("commands", incident.id))
            receipt.recovered, receipt.verification = True, "completed"
            receipt.trajectory = incident.trajectory
            self.platform.store.put("commands", incident.id, receipt)
            self.platform.store.audit(
                incident.id,
                "verified",
                {"samples": state.verification_steps, "tick": snapshot.tick},
            )
            state.completed += 1
            state.phase, state.reason = "cooldown", incident.reason
            self.cooldown[state.plant_id] = time.monotonic() + state.config.cooldown_seconds
        elif not good or state.verification_steps >= state.config.max_verification_steps:
            incident.status, incident.reason = (
                "escalated",
                "Fresh measurements did not establish safe recovery. Operator review required.",
            )
            self.attention(state, incident.reason)
            self.platform.store.audit(incident.id, "verification_failed", {})
        self.platform.store.put("incidents", incident.id, incident)
        if incident.status in ("resolved", "escalated"):
            self.platform.close_impact(incident)
