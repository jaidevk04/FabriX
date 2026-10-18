"""Incident reports: the decision story, read back from the append-only audit log."""

from cognition.insights import impact as impact_ledger
from cognition.insights.kpi import incident_timings

SKIP = {"tool_called", "tool_result", "agent_text", "measurement", "command_dispatch"}


def _line(kind: str, body: dict) -> str:
    texts = {
        "core_alert": lambda b: f"{b.get('core')} core raised {b.get('level')}: {b.get('title')}",
        "core_alert_cleared": lambda b: f"{b.get('core')} core cleared {b.get('alert')}",
        "fault_injected": lambda b: (
            f"Fault injected: {b.get('kind')} (severity {b.get('severity')})"
        ),
        "business_injected": lambda b: f"Business event: {b.get('kind')}",
        "started": lambda b: f"Investigation started at revision {b.get('revision')}",
        "proposed": lambda b: f"Proposal: {b.get('summary')}",
        "approval_requested": lambda b: "Waiting for operator approval",
        "approval_decided": lambda b: f"Operator {'approved' if b.get('accepted') else 'declined'}",
        "order_created": lambda b: f"Order for the {b.get('core')} core ({b.get('control')})",
        "order_receipt": lambda b: "Order completed with a committed receipt",
        "order_refused": lambda b: f"Order refused: {b.get('reason')}",
        "mission_completed": lambda b: f"Robot mission {b.get('kind')} on {b.get('target')}",
        "mission_refused": lambda b: f"Mission refused: {b.get('reason')}",
        "command_committed": lambda b: "Gateway committed the command",
        "action_applied": lambda b: (
            f"Duty {b.get('previous_value')} to {b.get('commanded_value')}; "
            f"temperature {round(b.get('temperature_after', 0), 1)}"
        ),
        "maintenance_applied": lambda b: (
            f"Repair {b.get('remedy')} on {b.get('equipment')}; spare {b.get('spare_used')}; "
            f"downtime {b.get('downtime_hours')} h"
        ),
        "verified": lambda b: f"Recovery verified over {b.get('samples')} samples",
        "fault_ramping": lambda b: f"Fault ramping in: {b.get('kind')}",
        "fault_active": lambda b: f"Fault at full strength: {b.get('kind')}",
        "fault_cleared": lambda b: f"Fault cleared by {b.get('cleared_by')}: {b.get('kind')}",
        "core_query": lambda b: f"Asked the {b.get('core')} core to analyse",
        "core_answer": lambda b: "A core answered with its analysis",
        "work_order_started": lambda b: "Work order started",
        "work_order_released": lambda b: "Work order put back to open",
        "work_order_cancelled": lambda b: "Work order cancelled",
        "work_order_created": lambda b: "Work order created",
        "work_order_completed": lambda b: "Work order completed",
        "impact_recorded": lambda b: f"Impact recorded ({b.get('outcome')})",
        "completed": lambda b: (
            "Investigation finished; command applied, verifying with fresh samples"
            if b.get("status") == "verifying"
            else f"Incident ended: {b.get('status')}"
        ),
    }
    make = texts.get(kind)
    return make(body) if make else kind.replace("_", " ")


def incident_report(platform, incident_id: str) -> dict:
    from cognition.domain import Incident

    incident = Incident.model_validate_json(platform.store.get("incidents", incident_id))
    plant = incident.plant_id
    own = platform.store.events(incident_id)
    started_at = next(
        (e["time"] for e in own if e["kind"] == "started"), incident.created_at.isoformat()
    )
    # Core and world events join the story when they share a correlation id with this incident
    # or with an alert that fired before it started.
    linked = {incident_id}
    for event in platform.store.events(f"cores:{plant}"):
        if event["kind"] == "core_alert" and event["time"] <= started_at:
            linked.add(event["body"].get("correlation_id", ""))
    steps = [(e["time"], e["kind"], e["body"], "incident") for e in own if e["kind"] not in SKIP]
    for stream, label in ((f"cores:{plant}", "core"), (f"world:{plant}", "world")):
        for event in platform.store.events(stream):
            if event["body"].get("correlation_id") in linked and event["kind"] not in SKIP:
                steps.append((event["time"], event["kind"], event["body"], label))
    steps.sort(key=lambda s: s[0])
    story = [
        {"time": t, "kind": k, "stream": s, "text": _line(k, b)}
        for t, k, b, s in steps
        if k != "core_tool_called"
    ]
    tools = [e["body"]["name"] for e in own if e["kind"] == "tool_called"]
    proposal = incident.proposal.model_dump(mode="json") if incident.proposal else None
    record = None
    try:
        record = platform.store.get("impact_ledger", incident_id)
    except KeyError:
        pass
    return {
        "incident": incident.model_dump(mode="json", exclude={"trajectory"}),
        "title": f"{plant}: {incident.status}",
        "story": story,
        "tools_used": {name: tools.count(name) for name in dict.fromkeys(tools)},
        "decision": proposal,
        "evidence": (proposal or {}).get("evidence", []),
        "timings": incident_timings(platform, incident),
        "impact": record and __import__("json").loads(record),
        "work_orders": [
            w.model_dump(mode="json")
            for w in platform.workorders.all(plant)
            if w.source_ref == incident_id
        ],
        "basis": "Read from the append-only audit log. All models and prices are simulated.",
    }


def to_markdown(report: dict) -> str:
    inc = report["incident"]
    lines = [
        f"# Incident report: {report['title']}",
        "",
        f"- Incident: `{inc['id']}`",
        f"- Harness: {inc['harness']}",
        f"- Status: **{inc['status']}**",
        f"- Reason: {inc['reason']}",
        "",
    ]
    if report["decision"]:
        d = report["decision"]
        action = d.get("action") or {}
        lines += ["## Decision", "", d["summary"], ""]
        if action:
            lines.append(f"- Action: `{action}`")
        if d.get("escalation"):
            lines.append(f"- Escalation: {d['escalation']}")
        lines += [f"- Evidence: {item}" for item in report["evidence"]] + [""]
    lines += (
        ["## Story", ""] + [f"{i}. {s['text']}" for i, s in enumerate(report["story"], 1)] + [""]
    )
    timing = {k: v for k, v in report["timings"].items() if k.endswith("_s") and v is not None}
    if timing:
        lines += (
            ["## Timings (simulated seconds)", ""]
            + [f"- {k}: {v}" for k, v in timing.items()]
            + [""]
        )
    if report["impact"]:
        lines += ["## Impact", "", f"- Deltas: `{report['impact']['deltas']}`"]
        if report["impact"].get("projected"):
            lines.append(f"- Projected: `{report['impact']['projected']}`")
        lines.append("")
    lines += [f"_{report['basis']}_", ""]
    return "\n".join(lines)


__all__ = ["impact_ledger", "incident_report", "to_markdown"]
