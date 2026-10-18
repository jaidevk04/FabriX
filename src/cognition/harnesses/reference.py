"""Deterministic offline baseline, explicitly not an LLM agent."""

import inspect
from datetime import timedelta

from cognition.domain import (
    Action,
    Capabilities,
    ExpectedImpact,
    ImpactMetric,
    MaintenanceAction,
    Proposal,
    Request,
    now,
)
from cognition.industries import get_industry
from cognition.layers.cognitive.tools import Tools


class ReferenceHarness:
    def capabilities(self) -> Capabilities:
        return Capabilities(name="reference", live_model=False)

    @staticmethod
    async def _ask(functions, core: str, question: str) -> dict:
        result = functions["ask_core"](core, question, "detailed")
        return await result if inspect.isawaitable(result) else result

    async def _repair(self, request: Request, functions, cores: list[str]) -> Proposal | str | None:
        """Offline rule: act on a repair only when evidence is strong and the spare exists."""
        if not cores or "ask_core" not in functions:
            return None
        learning = await self._ask(functions, "learning", "Which fault signature fits?")
        vision = await self._ask(functions, "vision", "Which fault signature fits?")
        seen = {c["fault"] for c in vision.get("assessment", {}).get("candidates", [])}
        robot = await self._ask(functions, "robot", "Verify the suspected equipment in person.")
        confirmed = {
            f["fault"]
            for v in robot.get("assessment", {}).get("verification", [])
            for f in v.get("findings", [])
        }
        for found in learning.get("assessment", {}).get("candidates", []):
            strong = found["match"] >= 0.5 and found["strength"] >= 0.5
            strong = strong and (found["fault"] in seen or found["strength"] >= 0.7)
            if not (strong or found["fault"] in confirmed):
                continue
            business = functions["read_business"]()
            part = business["remedy_spare"].get(found["remedy"])
            if part and business["spares_available"].get(part, 0) <= 0:
                lead = business["spare_lead_hours"].get(part, 0)
                return (
                    f"Repair '{found['remedy']}' on {found['equipment']} needs spare '{part}', "
                    f"which is not in inventory (lead time {lead:.0f} h). Operator decision needed."
                )
            plan = await self._ask(functions, "optimization", "Is repairing now worthwhile?")
            window = plan.get("assessment", {}).get("maintenance")
            if window and window.get("best") == "no_repair":
                idle: dict = next((p for p in window["plans"] if p["plan"] == "no_repair"), {})
                return (
                    f"The optimization core's repair-window plan favours not repairing "
                    f"{found['equipment']} within the horizon (net value {idle.get('net_value')}); "
                    "no breakdown is predicted. Operator decision needed."
                )
            return Proposal(
                plant_id=request.snapshot.spec.id,
                revision=request.snapshot.revision,
                expires_at=now() + timedelta(seconds=120),
                summary=f"Repair {found['equipment']}: signature matches {found['fault']}.",
                action=MaintenanceAction(equipment=found["equipment"], remedy=found["remedy"]),
                expected_impact=ExpectedImpact(
                    summary=f"Clears {found['fault']} and its heat load and signal drift.",
                    metrics=[ImpactMetric(name="faults_cleared", value=1)],
                ),
                evidence=[
                    f"learning core: {found['fault']} match {found['match']} "
                    f"strength {found['strength']}",
                    "vision core corroborates" if found["fault"] in seen else "single modality",
                    "robot inspection confirmed it"
                    if found["fault"] in confirmed
                    else "no inspection",
                ],
            )
        return None

    async def propose(self, request: Request, tools: Tools) -> Proposal:
        tools.discover()
        profile = get_industry(request.snapshot.spec.industry).PROFILE
        tools.read_skill(profile.skill)
        layers = tools.read_layers()
        functions = {fn.__name__: fn for fn in tools.functions()}
        state = functions[profile.read_tool]()["snapshot"]
        cores = []
        if "read_core_live" in functions:
            for name in ("learning", "vision", "robot"):
                report = functions["read_core_live"](name)
                if report.get("alerts"):
                    behind = report["stamp"]["revisions_behind"]
                    cores.append(f"{name} core: {report['summary']} ({behind} revisions behind)")
        limits = tools.read_control()
        tools.read_time()
        tools.read_sop()
        candidates = []
        escalation = None
        if not layers["reflexive"]["cognitive_control_permitted"]:
            escalation = "Telemetry or operating mode requires operator inspection."
        elif (repair := await self._repair(request, functions, cores)) is not None:
            if isinstance(repair, Proposal):
                return repair
            escalation = repair
        elif layers["perceptual"]["conflicts"]:
            escalation = "Conflicting perceptual evidence requires cognitive or operator review."
        else:
            for delta in range(-20, 21, 2):
                value = state["duty"] + delta
                if not limits["minimum"] <= value <= limits["maximum"]:
                    continue
                result = functions[profile.simulate_tool](value)
                if result["recovered"] and result["safe"]:
                    candidates.append((abs(delta), result["final_error"], value))
            if not candidates:
                escalation = "No bounded simulated action predicts sustained recovery."
        if escalation:
            detail = escalation + (" Core evidence: " + " | ".join(cores) if cores else "")
            return Proposal(
                plant_id=request.snapshot.spec.id,
                revision=request.snapshot.revision,
                expires_at=now() + timedelta(seconds=120),
                summary=detail[:1900],
                escalation=detail[:1900],
                evidence=["read_snapshot / simulation criteria", *[c[:300] for c in cores][:10]],
            )
        _, error, value = min(candidates)
        return Proposal(
            plant_id=request.snapshot.spec.id,
            revision=request.snapshot.revision,
            expires_at=now() + timedelta(seconds=120),
            summary="Smallest tested adjustment that restores the operating band.",
            action=Action(value=value),
            evidence=[f"{profile.simulate_tool}({value}): final error {error:.3f} degC"],
        )
