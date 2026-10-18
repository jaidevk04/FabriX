"""Agent estate read model: who exists, how they connect, what each is doing, and a readable log.

Everything here reads the audit trail. It writes nothing. The log for a plant starts again after
the plant is reset, so it persists exactly as long as the plant state does.
"""

import json
from datetime import UTC, datetime
from importlib.resources import files

from cognition.agentkit.adk import SHARED_SKILLS
from cognition.cores.registry import SPECS
from cognition.domain import now

AGENTS = ("harness", "learning", "vision", "robot", "optimization", "gateway", "fleet")
CORES = tuple(SPECS)
RECENT_SECONDS = 8.0
MAX_INCIDENTS = 30
DETAIL_LIMIT = 900

# (id, from, to, label). Edges describe authority and evidence paths, not network calls.
EDGES = (
    ("harness>learning", "harness", "learning", "asks for evidence"),
    ("harness>vision", "harness", "vision", "asks for evidence"),
    ("harness>robot", "harness", "robot", "asks for evidence, orders repairs"),
    ("harness>optimization", "harness", "optimization", "asks for a plan, orders duty changes"),
    ("harness>gateway", "harness", "gateway", "proposal for validation"),
    ("optimization>gateway", "optimization", "gateway", "executes thermal duty orders"),
    ("robot>gateway", "robot", "gateway", "executes repairs"),
    ("robot>fleet", "robot", "fleet", "missions"),
    ("bus:learning-vision", "learning", "vision", "evidence bus"),
    ("bus:vision-robot", "vision", "robot", "evidence bus"),
    ("bus:robot-optimization", "robot", "optimization", "evidence bus"),
)


def _seconds_ago(iso: str) -> float:
    try:
        stamp = datetime.fromisoformat(iso)
    except ValueError:
        return 1e9
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return max(0.0, (now() - stamp).total_seconds())


def _text(value, limit: int = DETAIL_LIMIT) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _floor(store, plant_id: str) -> int:
    resets = [e["seq"] for e in store.events(f"world:{plant_id}") if e["kind"] == "plant_reset"]
    return resets[-1] if resets else 0


def _incident_ids(platform, plant_id: str) -> list[str]:
    return [i.id for i in platform.store.incidents() if i.plant_id == plant_id][:MAX_INCIDENTS]


# ---------- turning audit events into readable entries ----------


def _entry(
    e: dict, agent: str, tag: str, title: str, level: str = "info", detail=None, group=""
) -> dict:
    return {
        "seq": e["seq"],
        "time": e["time"],
        "agent": agent,
        "tag": tag,
        "level": level,
        "title": title,
        "detail": _text(detail) if detail not in (None, "", {}, []) else "",
        "group": group,
    }


def _from_incident(e: dict, incident: str) -> list[dict]:
    """Events on an investigation stream belong to the main harness, except the command ones."""
    b, k = e["body"], e["kind"]
    g = incident
    if k == "started":
        return [_entry(e, "harness", "RUN", "Investigation started", detail=b, group=g)]
    if k == "tool_called":
        return [
            _entry(e, "harness", "TOOL", f"Called {b.get('name')}", detail=b.get("args"), group=g)
        ]
    if k == "tool_result":
        level = "ok" if b.get("recovered") else "info"
        return [_entry(e, "harness", "RESULT", f"{b.get('name')} returned", level, b, g)]
    if k == "agent_text":
        return [_entry(e, "harness", "TEXT", b.get("text", ""), group=g)]
    if k == "proposed":
        action = b.get("action") or {}
        title = b.get("summary") or "Proposal ready"
        out = [
            _entry(
                e,
                "harness",
                "PROPOSAL",
                title[:220],
                "ok",
                {"evidence": b.get("evidence"), "action": action},
                g,
            )
        ]
        return out
    if k == "approval_requested":
        return [
            _entry(e, "harness", "APPROVAL", "Waiting for an operator decision", "warn", group=g)
        ]
    if k == "core_answer":
        return [
            _entry(
                e,
                "harness",
                "BUS",
                f"Answer received from the {b.get('core', 'core')} core",
                detail=b,
                group=g,
            )
        ]
    if k == "command_dispatch":
        return [_entry(e, "gateway", "COMMAND", "Validated command dispatched", detail=b, group=g)]
    if k == "command_committed":
        return [
            _entry(
                e,
                "gateway",
                "COMMAND",
                "Command committed with a receipt",
                "ok",
                {"revision": b.get("revision"), "verification": b.get("verification")},
                g,
            )
        ]
    if k in ("action_applied", "maintenance_applied"):
        title = (
            f"Thermal duty {b.get('previous_value')} → {b.get('commanded_value')}"
            if b.get("control") == "thermal_duty"
            else f"Applied {b.get('control') or 'maintenance'}"
        )
        return [_entry(e, "gateway", "ACTION", title, "ok", b, g)]
    if k == "verified":
        return [_entry(e, "harness", "VERIFY", "Recovery verified", "ok", b, g)]
    if k == "completed":
        status = b.get("status", "")
        level = "ok" if status == "resolved" else "crit" if status == "failed" else "warn"
        return [_entry(e, "harness", "RUN", f"Investigation {status}", level, group=g)]
    if k == "cancelled":
        return [_entry(e, "harness", "RUN", "Investigation cancelled", "warn", group=g)]
    return []  # measurements and other per-tick records are too noisy for a log


CORE_KINDS = {
    "core_alert": ("ALERT", "warn"),
    "core_alert_cleared": ("ALERT", "ok"),
    "core_query": ("ASK", "info"),
    "core_request": ("BUS", "info"),
    "core_answer": ("BUS", "info"),
    "core_refused": ("BUS", "crit"),
    "core_run_started": ("RUN", "info"),
    "core_run_completed": ("RUN", "ok"),
    "core_run_interrupted": ("RUN", "warn"),
    "core_run_failed": ("RUN", "crit"),
    "core_run_timeout": ("RUN", "crit"),
    "core_report": ("REPORT", "info"),
    "core_degraded": ("WARN", "warn"),
    "core_stop": ("RUN", "warn"),
    "core_stop_all": ("RUN", "warn"),
    "order_created": ("ORDER", "info"),
    "order_receipt": ("ORDER", "ok"),
    "order_refused": ("ORDER", "crit"),
    "order_failed": ("ORDER", "crit"),
    "order_interrupted": ("ORDER", "warn"),
    "followup_pending": ("ORDER", "warn"),
    "followup_executed": ("ORDER", "ok"),
    "followup_rejected": ("ORDER", "crit"),
    "followup_declined": ("ORDER", "warn"),
    "mission_completed": ("MISSION", "ok"),
    "mission_refused": ("MISSION", "crit"),
    "fleet_recalled": ("MISSION", "warn"),
}


def _core_title(k: str, b: dict) -> str:
    kind = (b.get("kind") or "").replace("_", " ")
    titles = {
        "core_alert": lambda: f"{b.get('title')} ({b.get('level')})",
        "core_alert_cleared": lambda: f"Alert cleared: {b.get('alert')}",
        "core_query": lambda: f"Asked to analyse: {str(b.get('question', ''))[:140]}",
        "core_request": lambda: f"{b.get('from')} asked {b.get('to')} for {kind}",
        "core_answer": lambda: (
            f"Answered a bus request{' from ' + b['from'] if b.get('from') else ''}"
        ),
        "core_refused": lambda: f"Bus request refused: {b.get('reason')}",
        "core_run_started": lambda: f"Agent {kind} run started",
        "core_run_completed": lambda: "Agent run finished",
        "core_run_interrupted": lambda: "Agent run stopped",
        "core_run_failed": lambda: f"Agent run failed ({b.get('type')}). No automatic retry",
        "core_run_timeout": lambda: "Agent run hit its time ceiling",
        "core_report": lambda: f"Report ready: {b.get('status')}",
        "core_degraded": lambda: f"Degraded: {b.get('reason')}",
        "core_stop": lambda: "Stop pressed",
        "core_stop_all": lambda: "Stop pressed for all cores",
        "order_created": lambda: f"Order received: {str(b.get('control', '')).replace('_', ' ')}",
        "order_receipt": lambda: "Order completed with a receipt",
        "order_refused": lambda: f"Order refused: {b.get('reason')}",
        "order_failed": lambda: f"Order failed ({b.get('type')}). No automatic retry",
        "order_interrupted": lambda: "Order interrupted",
        "followup_pending": lambda: "Follow-up waiting for approval",
        "followup_executed": lambda: "Follow-up applied",
        "followup_rejected": lambda: f"Follow-up rejected: {b.get('reason')}",
        "followup_declined": lambda: "Follow-up declined",
        "mission_completed": lambda: (
            f"{str(b.get('kind', '')).title()} {b.get('target', '')} ({b.get('tier')})"
        ),
        "mission_refused": lambda: f"Mission refused: {b.get('reason')}",
        "fleet_recalled": lambda: "Robots recalled to the dock",
    }
    return titles[k]()


def _owner(k: str, b: dict) -> list[str]:
    """Which agent rows a cores-stream event appears in."""
    if k in ("mission_completed", "mission_refused", "fleet_recalled"):
        return ["fleet", "robot"]
    if k == "core_request":
        return [str(x) for x in (b.get("from"), b.get("to")) if x in CORES]
    core = b.get("core")
    owners: list[str] = [str(core)] if core in CORES else []
    if k == "order_receipt":
        owners.append("gateway")
    return owners


def _from_cores(e: dict) -> list[dict]:
    k, b = e["kind"], e["body"]
    if k not in CORE_KINDS:
        return []
    tag, level = CORE_KINDS[k]
    title = _core_title(k, b)
    detail = {key: val for key, val in b.items() if key not in ("correlation_id",)}
    group = b.get("run") or ""
    return [_entry(e, agent, tag, title, level, detail, group) for agent in _owner(k, b)]


def _from_agent_stream(e: dict, core: str) -> list[dict]:
    k, b = e["kind"], e["body"]
    g = b.get("run", "")
    if k == "llm_text":
        return [_entry(e, core, "TEXT", b.get("text", ""), group=g)]
    if k == "llm_thought":
        return [_entry(e, core, "THINK", b.get("text", ""), group=g)]
    if k == "final":
        return [_entry(e, core, "FINAL", "Structured answer", "ok", b.get("text"), g)]
    if k == "tool_call":
        return [_entry(e, core, "TOOL", f"Called {b.get('name')}", detail=b.get("args"), group=g)]
    if k == "tool_result":
        return [
            _entry(e, core, "RESULT", f"{b.get('name')} returned", detail=b.get("result"), group=g)
        ]
    if k == "reference_answer":
        return [
            _entry(e, core, "REFERENCE", f"Reference analyser: {b.get('summary')}", "info", b, g)
        ]
    if k == "reference_order":
        return [
            _entry(
                e,
                core,
                "ORDER",
                f"Reference executor ran {str(b.get('control', '')).replace('_', ' ')}",
                "info",
                b,
                g,
            )
        ]
    return []


def _from_automation(e: dict) -> list[dict]:
    k, b = e["kind"], e["body"]
    if k == "automation_enabled":
        return [
            _entry(
                e,
                "harness",
                "AUTO",
                f"Automation on ({b.get('mode')}, {b.get('harness')})",
                "ok",
                b,
            )
        ]
    if k == "run_complete":
        title = f"Run complete: {b.get('verified')} of {b.get('limit')} investigations verified"
        return [_entry(e, "harness", "AUTO", title + ". Agents stopped", "ok", b)]
    if k == "automation_stopped":
        return [_entry(e, "harness", "AUTO", "Automation stopped", "warn")]
    if k == "operator_marked_fixed":
        return [_entry(e, "harness", "AUTO", "Operator marked the fault fixed", "ok", b)]
    if k == "attention_resumed":
        return [_entry(e, "harness", "AUTO", "Operator asked for a fresh investigation", "info")]
    if k == "attention_dismissed":
        return [_entry(e, "harness", "AUTO", "Operator dismissed the alert", "info")]
    if k == "attention_required":
        return [_entry(e, "harness", "AUTO", f"Needs attention: {b.get('reason')}", "warn")]
    if k == "observation_received":
        return [_entry(e, "harness", "OBS", f"Observation from {b.get('id')}", "info", b)]
    return []


def entries(platform, plant_id: str, agent: str, after: int = 0, limit: int = 400) -> dict:
    """Log entries for one agent, oldest first, after `after` and after the last plant reset."""
    store = platform.store
    lo = max(after, _floor(store, plant_id))
    found: list[dict] = []
    for e in store.events(f"world:{plant_id}", lo):
        if e["kind"] == "kill_switch_tripped":
            after = e["body"].get("after_seconds", 0)
            title = f"Kill switch tripped after {after:g} s: this agent was stopped"
            found.append(_entry(e, agent, "KILL", title, "crit"))
    if agent == "harness":
        for incident in _incident_ids(platform, plant_id):
            for e in store.events(incident, lo):
                found += [x for x in _from_incident(e, incident) if x["agent"] == "harness"]
        for e in store.events(f"automation:{plant_id}", lo):
            found += _from_automation(e)
    if agent == "gateway":
        for incident in _incident_ids(platform, plant_id):
            for e in store.events(incident, lo):
                found += [x for x in _from_incident(e, incident) if x["agent"] == "gateway"]
    if agent in CORES:
        for e in store.events(f"agent:{plant_id}:{agent}", lo):
            found += _from_agent_stream(e, agent)
    if agent in (*CORES, "fleet", "gateway"):
        for e in store.events(f"cores:{plant_id}", lo):
            found += [x for x in _from_cores(e) if x["agent"] == agent]
    found.sort(key=lambda x: x["seq"])
    found = found[-limit:]
    return {
        "agent": agent,
        "entries": found,
        "last_seq": found[-1]["seq"] if found else after,
        "floor": _floor(store, plant_id),
    }


# ---------- estate overview ----------


def _tool_names(core: str) -> list[str]:
    folder = files("cognition").joinpath("cores", core, "tools")
    if not folder.is_dir():
        return []
    return sorted(
        p.name[:-3]
        for p in folder.iterdir()
        if p.name.endswith(".py") and not p.name.startswith("_")
    )


def _skill_names(core: str) -> list[str]:
    names: set[str] = set()
    for base in (files("cognition").joinpath("cores", core, "skills"), SHARED_SKILLS):
        try:
            names.update(p.name for p in base.iterdir() if p.is_dir())
        except (FileNotFoundError, NotADirectoryError):
            continue
    return sorted(names)


def _recent(platform, plant_id: str) -> list[dict]:
    """Every normalised entry from the last few seconds, for all agents."""
    out = []
    for agent in AGENTS:
        out += [
            x
            for x in entries(platform, plant_id, agent, limit=40)["entries"]
            if _seconds_ago(x["time"]) <= RECENT_SECONDS
        ]
    return out


def _last(platform, plant_id: str, agent: str) -> dict | None:
    items = entries(platform, plant_id, agent, limit=1)["entries"]
    return items[-1] if items else None


def estate(platform, plant_id: str, auto=None) -> dict:
    from cognition.harnesses.base import ModelSettings

    agents_cfg = platform.core_agents
    ok, reason = agents_cfg.available()
    configured = auto.config.harness if auto else None
    settings = ModelSettings.from_env()
    recent = _recent(platform, plant_id)
    busy = plant_id in platform.busy
    active_runs = {
        core: run for (plant, core), (run, _t) in agents_cfg.active.items() if plant == plant_id
    }

    def live(agent: str) -> str:
        return "working" if any(x["agent"] == agent for x in recent) else "idle"

    nodes = []
    harness_state = (
        "working"
        if busy or (auto and auto.phase in ("planning", "verifying", "awaiting_approval"))
        else live("harness")
    )
    nodes.append(
        {
            "id": "harness",
            "kind": "harness",
            "name": "Main harness",
            "subtitle": configured or "antigravity",
            "model": settings.model or None,
            "mode": "live model"
            if (configured or "antigravity") not in ("reference",)
            else "offline reference",
            "state": harness_state,
            "phase": auto.phase if auto else "off",
            "detail": auto.reason if auto else "Automation has not been started for this plant.",
            "tools": [],
            "skills": ["read_skill (industry skills load on demand)"],
            "description": (
                "Investigates faults and returns exactly one typed proposal. "
                "It never writes plant state."
            ),
            "last": _last(platform, plant_id, "harness"),
        }
    )
    for core in CORES:
        run = active_runs.get(core)
        mode = "ADK agent" if (agents_cfg.enabled and ok) else "reference analyser"
        state = "working" if run else live(core)
        nodes.append(
            {
                "id": core,
                "kind": "core",
                "name": f"{core.title()} core",
                "subtitle": SPECS[core].description,
                "model": agents_cfg.status().get("model") if mode == "ADK agent" else None,
                "mode": mode,
                "state": state,
                "phase": f"{run.kind} run" if run else "waiting",
                "detail": reason if mode != "ADK agent" else "",
                "tools": _tool_names(core),
                "skills": _skill_names(core),
                "description": SPECS[core].description,
                "last": _last(platform, plant_id, core),
            }
        )
    nodes.append(
        {
            "id": "gateway",
            "kind": "gateway",
            "name": "Gateway",
            "subtitle": "Sole plant command writer",
            "mode": "deterministic",
            "model": None,
            "state": live("gateway"),
            "phase": "validating",
            "detail": "",
            "tools": [],
            "skills": [],
            "description": (
                "Validates every proposal, revalidates after approval and writes the receipt. "
                "Harnesses and cores never write plant state."
            ),
            "last": _last(platform, plant_id, "gateway"),
        }
    )
    nodes.append(
        {
            "id": "fleet",
            "kind": "gateway",
            "name": "Fleet gateway",
            "subtitle": "Robot missions only",
            "mode": "deterministic",
            "model": None,
            "state": live("fleet"),
            "phase": "dispatching",
            "detail": "",
            "tools": [],
            "skills": [],
            "description": (
                "Runs robot missions under authority tiers. It never writes plant state."
            ),
            "last": _last(platform, plant_id, "fleet"),
        }
    )

    active_edges: set[str] = set()
    for x in recent:
        a, tag = x["agent"], x["tag"]
        title = f"{x['title']} {x['detail']}".lower()
        if a == "harness" and tag in ("TOOL", "BUS"):
            for core in CORES:
                if core in title and ("ask_core" in title or "core" in title or "optimiz" in title):
                    active_edges.add(f"harness>{core}")
            if "request_optimization" in title:
                active_edges.add("harness>optimization")
        if a == "harness" and tag in ("PROPOSAL", "APPROVAL"):
            active_edges.add("harness>gateway")
        if a == "gateway":
            active_edges.add("harness>gateway")
        if a in CORES and tag in ("ASK", "ORDER", "RUN", "REFERENCE"):
            active_edges.add(f"harness>{a}")
        if a == "optimization" and tag == "ORDER":
            active_edges.add("optimization>gateway")
        if a == "robot" and tag == "ORDER":
            active_edges.add("robot>gateway")
        if a in ("robot", "fleet") and tag == "MISSION":
            active_edges.add("robot>fleet")
        if tag == "BUS":
            ends = [c for c in CORES if c in title]
            for edge_id, src, dst, _ in EDGES:
                if edge_id.startswith("bus:") and src in ends and dst in ends:
                    active_edges.add(edge_id)
    edges = [
        {"id": i, "from": s, "to": d, "label": label, "active": i in active_edges}
        for i, s, d, label in EDGES
    ]
    return {
        "plant_id": plant_id,
        "nodes": nodes,
        "edges": edges,
        "agents": {"enabled": agents_cfg.enabled, "available": ok, "reason": reason},
        "floor": _floor(platform.store, plant_id),
        "kill": platform.world.kill_state(plant_id),
    }
