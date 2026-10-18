"""One implementation behind each core's `<core>_request_evidence` tool."""

import uuid
from datetime import timedelta

from pydantic import ValidationError

from cognition.agentkit.tools import tool_error
from cognition.cores.context import CoreContext
from cognition.domain import BusRequest, now


def request_evidence(ctx: CoreContext, to_core: str, kind: str, target: str, question: str) -> dict:
    try:
        request = BusRequest(
            id=f"req-{uuid.uuid4().hex[:12]}",
            correlation_id=ctx.correlation_id,
            plant_id=ctx.plant_id,
            from_core=ctx.core,
            to_core=to_core,  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            target=target,
            question=question[:200] or "evidence",
            revision=ctx.state.revision,
            expires_at=now() + timedelta(seconds=30),
            chain=[ctx.core],
        )
    except ValidationError:
        return tool_error(
            "Invalid evidence request",
            "to_core is learning, vision or robot; kind is read_signal_evidence, "
            "read_detections or read_fleet_state; target is an equipment id.",
        )
    response = ctx.platform.cores.bus.request(request)
    if response.status == "refused":
        return tool_error(response.reason, "Check the allowed kinds and the equipment id.")
    return response.evidence
