"""Stamped, size-limited views of core reports for the main harness."""

from cognition.agentkit.tools import choose_format, tool_error
from cognition.domain import CoreReport, now


def stamp(report: CoreReport, current_revision: int) -> dict:
    return {
        "revision": report.revision,
        "tick": report.tick,
        "revisions_behind": max(0, current_revision - report.revision),
        "age_seconds": round((now() - report.observed_at).total_seconds(), 2),
        "source": report.source,
        "model": report.model,
        "trained_model": report.trained_model,
        "degraded": report.degraded,
    }


def view(report: CoreReport, current_revision: int, scope: str = "", fmt: str = "concise"):
    alerts = [a for a in report.alerts if not scope or a.equipment == scope]
    concise = {
        "core": report.core,
        "status": report.status,
        "summary": report.summary,
        "alerts": [
            {"id": a.id, "level": a.level, "title": a.title, "equipment": a.equipment}
            for a in alerts
        ],
        "stamp": stamp(report, current_revision),
        "hint": "Use response_format='detailed' for evidence and assessment.",
    }
    detailed = concise | {
        "alerts": [a.model_dump(mode="json") for a in alerts],
        "assessment": report.assessment,
        "hint": "",
    }
    if scope and not alerts:
        concise["note"] = f"No alerts for '{scope}'."
    return (
        choose_format(concise, detailed, fmt)
        if fmt in ("concise", "detailed")
        else tool_error(f"Unknown response_format '{fmt}'", "Use 'concise' or 'detailed'.")
    )
