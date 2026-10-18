"""Core bus: typed evidence requests between cores. No orders, no loops, every step audited."""

from cognition.cores._evidence import detection_evidence, fleet_evidence, signal_evidence
from cognition.cores.base import plant_equipment
from cognition.domain import BusKind, BusRequest, BusResponse, CoreName, now

ANSWERS = {
    "read_signal_evidence": ("learning", signal_evidence),
    "read_detections": ("vision", detection_evidence),
    "read_fleet_state": ("robot", fleet_evidence),
}
# Who may ask whom. Cores only ask each other for evidence; nobody asks optimization.
ALLOWED: dict[CoreName, set[BusKind]] = {
    "learning": {"read_detections", "read_fleet_state"},
    "vision": {"read_signal_evidence", "read_fleet_state"},
    "robot": {"read_signal_evidence", "read_detections"},
    "optimization": {"read_signal_evidence", "read_detections", "read_fleet_state"},
}


class CoreBus:
    def __init__(self, platform) -> None:
        self.platform = platform

    def _audit(self, request: BusRequest, kind: str, body: dict) -> None:
        self.platform.store.audit(
            f"cores:{request.plant_id}",
            kind,
            {"correlation_id": request.correlation_id, "request_id": request.id, **body},
        )

    def request(self, request: BusRequest) -> BusResponse:
        self._audit(
            request,
            "core_request",
            {"from": request.from_core, "to": request.to_core, "kind": request.kind},
        )
        reason = self._refusal(request)
        if reason:
            self._audit(request, "core_refused", {"reason": reason})
            return BusResponse(request_id=request.id, status="refused", reason=reason)
        owner, handler = ANSWERS[request.kind]
        evidence = handler(self.platform, request)
        self._audit(request, "core_answer", {"from": owner})
        return BusResponse(request_id=request.id, status="ok", evidence=evidence)

    def _refusal(self, request: BusRequest) -> str | None:
        owner = ANSWERS[request.kind][0]
        if request.to_core != owner:
            return f"{request.to_core} does not answer {request.kind}"
        if request.from_core == request.to_core or request.to_core in request.chain:
            return "Request would loop back to a core already in the chain"
        if request.kind not in ALLOWED[request.from_core]:
            return f"{request.from_core} may not ask for {request.kind}"
        try:
            state = self.platform.store.plant(request.plant_id)
        except KeyError:
            return "Unknown plant"
        if request.expires_at <= now():
            return "Request expired"
        if request.revision > state.revision:
            return "Request revision is in the future"
        if request.target not in plant_equipment(state):
            return f"Unknown equipment '{request.target}' for this plant"
        return None
