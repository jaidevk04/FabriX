"""Repeatable evaluation: play each story on an in-memory platform and measure what happened."""

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from cognition.cores.base import RANK
from cognition.domain import Incident, PlantSpec
from cognition.evaluation.stories import STORIES, Story
from cognition.insights.kpi import incident_timings
from cognition.persistence.store import Store
from cognition.runtime.automation import Automation, AutomationConfig
from cognition.runtime.platform import Platform
from cognition.simulation.thermal import PACKS

GRACE_TICKS = 30  # an alert shortly after a fault clears is not a false alarm
SETTLE_TICKS = 15  # quiet iterations that count as "finished"
STALL_TICKS = 40  # iterations with automation off and faults still active


@contextmanager
def core_agents(enabled: bool) -> Iterator[None]:
    """Turn the ADK core agents on or off for the duration of a run."""
    previous = os.environ.get("COGNITION_CORE_AGENTS")
    os.environ["COGNITION_CORE_AGENTS"] = "true" if enabled else "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("COGNITION_CORE_AGENTS", None)
        else:
            os.environ["COGNITION_CORE_AGENTS"] = previous


def _apply(platform: Platform, automation: Automation, plant_id: str, step) -> None:
    if step.action == "inject":
        platform.faults.inject(
            plant_id, step.kind, severity=step.severity, ramp_ticks=step.ramp_ticks
        )
    elif step.action == "clear":
        for event in platform.faults.events(plant_id, include_cleared=False):
            if event.kind == step.kind:
                platform.faults.clear(plant_id, event.id, by="operator")
    elif not automation.state(plant_id).enabled and plant_id not in platform.busy:
        automation.enable(plant_id, _config(automation.state(plant_id).config.harness))


def _config(harness: str) -> AutomationConfig:
    return AutomationConfig(
        mode="autopilot", harness=harness, cooldown_seconds=0, max_investigations=6
    )


def _alerts(platform: Platform, plant_id: str) -> list[dict]:
    return [
        e["body"]
        for e in platform.store.events(f"cores:{plant_id}")
        if e["kind"] == "core_alert" and e["body"].get("tick") is not None
    ]


def _measure(platform: Platform, plant_id: str, story: Story) -> dict[str, Any]:
    faults = [e for e in platform.faults.events(plant_id) if e.domain == "fault"]
    # A fault is "open" from its start until shortly after it clears. Any open fault excuses an
    # alert: the monitors attribute by signal, so they may name a neighbouring equipment group.
    spans: list[tuple[int, float]] = [
        (
            e.started_tick,
            (e.cleared_tick if e.cleared_tick is not None else float("inf")) + GRACE_TICKS,
        )
        for e in faults
    ]
    first_start = min((start for start, _ in spans), default=None)
    alerts = [a for a in _alerts(platform, plant_id) if RANK[a["level"]] >= RANK["notify"]]
    detection: dict[str, int | None] = {}
    for equipment in story.expect.detect:
        hits = [
            a["tick"]
            for a in alerts
            if a.get("equipment") == equipment
            and first_start is not None
            and a["tick"] >= first_start
        ]
        detection[equipment] = (
            (min(hits) - first_start) if hits and first_start is not None else None
        )
    false = {
        (a["core"], a["alert"])
        for a in alerts
        if a.get("equipment") is not None
        and not any(start <= a["tick"] <= end for start, end in spans)
    }
    incidents: list[Incident] = list(reversed(platform.store.incidents()))
    all_events = [e for i in incidents for e in platform.store.events(i.id)]
    core_events = platform.store.events(f"cores:{plant_id}")
    state = platform.store.plant(plant_id)
    band = PACKS[state.spec.industry].band
    recovered = [i for i in incidents if i.status == "resolved"]
    return {
        "detection_ticks": detection,
        "false_alarms": len(false),
        "incidents": [
            {"status": i.status, "reason": i.reason, "timings": incident_timings(platform, i)}
            for i in incidents
        ],
        "resolved": len(recovered),
        "work_orders": len(platform.workorders.all(plant_id)),
        "escalated_reasons": [i.reason for i in incidents if i.status == "escalated"],
        "faults_active": sum(
            e.state != "cleared" for e in platform.faults.events(plant_id) if e.domain == "fault"
        ),
        "in_band": abs(state.temperature - state.target) <= band,
        "final_tick": state.tick,
        "cost": {
            "tool_calls": sum(e["kind"] == "tool_called" for e in all_events),
            "core_queries": sum(e["kind"] == "core_query" for e in core_events),
            "agent_runs": sum(e["kind"] == "core_run_started" for e in core_events),
            "model_calls": None,
        },
    }


def _checks(story: Story, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    expect, checks = story.expect, []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    for equipment in expect.detect:
        latency = metrics["detection_ticks"].get(equipment)
        check(f"detects {equipment}", latency is not None, f"latency {latency} ticks")
    if expect.false_alarms is not None:
        check(
            "no false alarms",
            metrics["false_alarms"] <= expect.false_alarms,
            f"{metrics['false_alarms']} false alarm(s)",
        )
    if expect.resolved_min:
        check(
            "incidents resolved",
            metrics["resolved"] >= expect.resolved_min,
            f"{metrics['resolved']} resolved",
        )
    if expect.escalated_text:
        check(
            "escalation explains the cause",
            any(expect.escalated_text in r.lower() for r in metrics["escalated_reasons"]),
            f"looking for '{expect.escalated_text}'",
        )
    if expect.all_faults_cleared:
        check("faults repaired", metrics["faults_active"] == 0, f"{metrics['faults_active']} left")
    if not story.steps:
        check("no investigation", not metrics["incidents"], f"{len(metrics['incidents'])} started")
    return checks


async def run_scenario(
    story: Story, harness: str = "reference", *, agents: bool = False
) -> dict[str, Any]:
    """Play one story to completion. Offline unless a live harness or agents are requested."""
    store = Store()
    platform = Platform(store)
    plant_id = f"{story.industry}-eval"
    try:
        with core_agents(agents):
            platform.onboard(PlantSpec(id=plant_id, name=plant_id, industry=story.industry))
            automation = Automation(platform)
            automation.enable(plant_id, _config(harness))
            start = store.plant(plant_id).tick
            pending = sorted(story.steps, key=lambda s: s.at)
            last_at = pending[-1].at if pending else 0
            quiet = stalled = 0
            for _ in range(story.max_ticks * 2):
                tick = store.plant(plant_id).tick - start
                while pending and pending[0].at <= tick:
                    _apply(platform, automation, plant_id, pending.pop(0))
                if automation.state(plant_id).enabled:
                    await automation.step(force=True)
                else:
                    platform.sample(plant_id)
                running = [t for t in automation.tasks.values() if not t.done()]
                if running:
                    await asyncio.gather(*running, return_exceptions=True)
                tick = store.plant(plant_id).tick - start
                if tick >= story.max_ticks:
                    break
                state = automation.state(plant_id)
                active = any(
                    e.domain == "fault"
                    for e in platform.faults.events(plant_id, include_cleared=False)
                )
                busy = state.enabled and state.phase in (
                    "planning",
                    "verifying",
                    "awaiting_approval",
                )
                stalled = stalled + 1 if (active and not state.enabled) else 0
                quiet = quiet + 1 if not pending and not busy and not active else 0
                if not story.steps and tick < story.max_ticks:
                    continue  # the control run always plays its full length
                if tick > last_at and (quiet >= SETTLE_TICKS or stalled >= STALL_TICKS):
                    break
            await automation.close()
            metrics = _measure(platform, plant_id, story)
        checks = _checks(story, metrics)
        return {
            "story": story.id,
            "title": story.title,
            "harness": harness,
            "agents": agents,
            "passed": all(c["ok"] for c in checks),
            "checks": checks,
            "metrics": metrics,
        }
    finally:
        store.close()


async def run_all(
    only: str | None = None, harness: str = "reference", *, agents: bool = False
) -> list[dict[str, Any]]:
    if only is not None and only not in STORIES:
        raise KeyError(f"Unknown scenario '{only}'. Available: {', '.join(STORIES)}")
    chosen = [STORIES[only]] if only else list(STORIES.values())
    return [await run_scenario(story, harness, agents=agents) for story in chosen]
