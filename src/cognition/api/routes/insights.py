"""Insight routes: KPIs, impact, reports, work orders, recommendations. Loopback, no auth."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from cognition.api.context import ApiContext
from cognition.api.schemas import WorkOrderRequest
from cognition.domain import RecommendationDecision
from cognition.insights import impact, kpi, recommendations, reports


def build(context: ApiContext) -> APIRouter:
    router = APIRouter(tags=["insights"])
    platform, require = context.platform, context.require

    @router.get("/api/plants/{plant_id}/kpis")
    def plant_kpis(plant_id: str):
        require(plant_id)
        return kpi.plant_kpis(platform(), plant_id)

    @router.get("/api/plants/{plant_id}/kpis/history")
    def kpi_history(plant_id: str, limit: int = 200):
        require(plant_id)
        return kpi.history(platform(), plant_id, limit)

    @router.get("/api/plants/{plant_id}/impact")
    def plant_impact(plant_id: str):
        require(plant_id)
        return {
            "summary": impact.summary(platform(), plant_id),
            "records": impact.records(platform(), plant_id),
        }

    @router.get("/api/incidents/{incident_id}/report")
    def report(incident_id: str, format: str = "json"):
        try:
            data = reports.incident_report(platform(), incident_id)
        except KeyError as exc:
            raise HTTPException(404, "Incident not found") from exc
        if format == "markdown":
            return PlainTextResponse(reports.to_markdown(data), media_type="text/markdown")
        return data

    @router.get("/api/plants/{plant_id}/work-orders")
    def work_orders(plant_id: str, status: str | None = None):
        require(plant_id)
        return platform().workorders.all(plant_id, status)

    @router.post("/api/plants/{plant_id}/work-orders", status_code=201)
    def create_work_order(plant_id: str, body: WorkOrderRequest):
        require(plant_id)
        try:
            return platform().workorders.create(
                plant_id, body.equipment, body.remedy, source="operator", note=body.note
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/work-orders/{order_id}/cancel")
    def cancel_work_order(order_id: str):
        try:
            return platform().workorders.cancel(order_id)
        except KeyError as exc:
            raise HTTPException(404, "Work order not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/plants/{plant_id}/recommendations")
    def list_recommendations(plant_id: str):
        require(plant_id)
        return recommendations.recommendations(platform(), plant_id)

    def decide(rec_id: str, status: str):
        plant_id = rec_id.split(":", 1)[0]
        require(plant_id)
        found = next(
            (r for r in recommendations.recommendations(platform(), plant_id) if r.id == rec_id),
            None,
        )
        if found is None:
            raise HTTPException(404, "Recommendation not found or already decided")
        platform().store.put(
            "recommendations", rec_id, RecommendationDecision(id=rec_id, status=status)
        )
        platform().store.audit(
            f"cores:{plant_id}", f"recommendation_{status}", {"correlation_id": rec_id}
        )
        return found

    @router.post("/api/recommendations/{rec_id}/dismiss")
    def dismiss(rec_id: str):
        return decide(rec_id, "dismissed")

    @router.post("/api/recommendations/{rec_id}/accept")
    def accept(rec_id: str):
        found = decide(rec_id, "accepted")
        if found.kind != "repair":
            return {"recommendation": found, "work_order": None}
        _, _, equipment = found.id.split(":", 2)
        remedy = next(a for a in found.actions if a.startswith("Propose ")).split()[1]
        order = platform().workorders.create(
            found.plant_id, equipment, remedy, source="recommendation", source_ref=found.id
        )
        return {"recommendation": found, "work_order": order}

    return router
