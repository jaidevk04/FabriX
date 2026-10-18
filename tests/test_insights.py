import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from cognition.api import create_app
from cognition.domain import MaintenanceAction, Proposal, now
from cognition.harnesses.reference import ReferenceHarness
from cognition.insights import impact, kpi, recommendations, reports
from cognition.runtime.automation import Automation, AutomationConfig


def wear(platform, ticks=4, severity=1.0):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=severity, ramp_ticks=0)
    for _ in range(ticks):
        platform.sample("kiln")


async def autopilot_until_done(platform, steps=200):
    automation = Automation(platform)
    automation.enable("kiln", AutomationConfig(mode="autopilot", cooldown_seconds=0))
    await automation.step(force=True)
    await asyncio.gather(*automation.tasks.values())
    for _ in range(steps):
        await automation.step(force=True)
        if automation.state("kiln").phase in ("cooldown", "attention"):
            break
    await automation.disable("kiln")
    return automation


# KPI samples and plant KPIs


def test_kpi_samples_are_stored_every_five_ticks_pruned_and_cleared_on_reset(platform):
    for _ in range(23):
        platform.sample("kiln")
    rows = kpi.history(platform, "kiln")
    assert [r.tick for r in rows] == [0, 5, 10, 15, 20]
    assert all(0 < r.oee <= 1 for r in rows) and rows == sorted(rows, key=lambda r: r.tick)
    assert len(kpi.history(platform, "kiln", limit=2)) == 2
    platform.reset("kiln")
    assert kpi.history(platform, "kiln") == []


def test_plant_kpis_report_totals_and_incident_counts(platform):
    for _ in range(12):
        platform.sample("kiln")
    result = kpi.plant_kpis(platform, "kiln")
    assert result["energy_per_t_gj"] > 0 and result["co2e_kg"] > 0 and result["simulated_cost"] > 0
    assert result["downtime_hours"] == 0 and result["incidents"]["total"] == 0
    assert "placeholder" in result["basis"] or "Simulated" in result["basis"]


# Impact, reports, timings and work orders through a real autopilot repair


async def test_repair_produces_impact_report_timings_and_a_completed_work_order(platform):
    wear(platform, ticks=3)
    assert [w.source for w in platform.workorders.all("kiln")] == ["alert"]
    await autopilot_until_done(platform)
    incident = platform.store.incidents()[0]
    assert incident.status == "resolved"
    record = impact.records(platform, "kiln")[0]
    assert record.control == "maintenance" and record.outcome == "resolved"
    assert record.deltas["downtime_hours"] > 0 and "value" in record.deltas
    assert record.projected and record.projected["advantage"] > 0
    assert record.projected["breakdown_avoided_hours"] is not None
    assert "totals" not in record.baseline
    work = platform.workorders.all("kiln")
    assert len(work) == 1 and work[0].status == "completed" and work[0].completed_tick is not None
    timings = kpi.incident_timings(platform, incident)
    assert timings["time_to_detect_s"] is not None and timings["time_to_recover_s"] > 0
    assert kpi.plant_kpis(platform, "kiln")["maintenance_cost"] == work[0].est_cost
    report = reports.incident_report(platform, incident.id)
    text = " | ".join(step["text"] for step in report["story"])
    for needle in (
        "raised",
        "Investigation started",
        "Proposal",
        "Repair bearing_swap",
        "verified",
    ):
        assert needle in text, needle
    assert (
        report["impact"]["id"] == incident.id and report["work_orders"][0]["status"] == "completed"
    )
    markdown = reports.to_markdown(report)
    assert (
        markdown.startswith("# Incident report")
        and "## Story" in markdown
        and "## Impact" in markdown
    )


async def test_duty_incident_records_excursion_avoided_against_the_no_action_forecast(platform):
    platform.connector.disturb("kiln", "heat_load")
    await autopilot_until_done(platform)
    record = impact.records(platform, "kiln")[0]
    assert record.control == "thermal_duty" and record.outcome == "resolved"
    assert record.baseline["no_action_recovers"] is False
    assert record.deltas["excursion_ticks_avoided"] > 0
    assert impact.summary(platform, "kiln")["excursion_ticks_avoided"] > 0


async def test_manual_run_records_impact_without_claiming_business_deltas(platform):
    platform.connector.disturb("kiln", "heat_load")
    incident = await platform.resolve("kiln", ReferenceHarness())
    record = impact.records(platform, "kiln")[0]
    assert incident.status == "resolved" and record.id == incident.id
    assert "No live business samples" in record.deltas["note"] and "value" not in record.deltas
    assert impact.close(platform, incident) is None  # idempotent


async def test_escalations_and_pure_escalations_leave_no_impact_record(platform):
    platform.connector.disturb("kiln", "actuator_stuck")
    incident = await platform.resolve("kiln", ReferenceHarness())
    assert incident.status == "escalated" and impact.records(platform, "kiln") == []


# Work orders


def test_alerts_draft_one_work_order_and_duplicates_are_merged(platform):
    wear(platform, ticks=6)
    drafts = platform.workorders.all("kiln")
    assert len(drafts) == 1
    draft = drafts[0]
    assert (draft.equipment, draft.remedy, draft.status) == ("drive", "bearing_swap", "open")
    assert draft.source == "alert" and draft.part == "bearing_set" and draft.est_hours == 0.4
    assert platform.workorders.create("kiln", "drive", "bearing_swap").id == draft.id


def test_work_order_validation_and_cancel_rules(platform):
    with pytest.raises(ValueError, match="Unknown equipment"):
        platform.workorders.create("kiln", "warp-core", "bearing_swap")
    with pytest.raises(ValueError, match="does not apply"):
        platform.workorders.create("kiln", "drive", "burner_retune")
    order = platform.workorders.create("kiln", "drive", "bearing_swap")
    assert platform.workorders.cancel(order.id).status == "cancelled"
    with pytest.raises(ValueError, match="Only open"):
        platform.workorders.cancel(order.id)
    again = platform.workorders.create("kiln", "drive", "bearing_swap")
    assert again.id != order.id and again.status == "open"


async def test_a_refused_repair_puts_the_work_order_back_to_open(platform):
    wear(platform, ticks=2)
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.spares["bearing_set"] = 0
    platform.store.put("business_state", "kiln", ledger)

    class Forced(ReferenceHarness):
        async def propose(self, request, tools):
            return Proposal(
                plant_id="kiln",
                revision=request.snapshot.revision,
                expires_at=now() + timedelta(seconds=60),
                summary="forced",
                action=MaintenanceAction(equipment="drive", remedy="bearing_swap"),
            )

    incident = await platform.resolve("kiln", Forced(), live=True)
    assert incident.status == "escalated"
    (work,) = platform.workorders.all("kiln")
    assert work.status == "open" and "Not done" in work.note
    assert impact.records(platform, "kiln")[0].outcome == "escalated"


# Recommendations


def test_repair_recommendation_is_ranked_with_value_urgency_and_actions(platform):
    wear(platform)
    items = recommendations.recommendations(platform, "kiln")
    repair = next(i for i in items if i.kind == "repair")
    assert repair.id == "kiln:repair:drive" and repair.urgency > 0.9 and repair.expected_value > 0
    assert any(a.startswith("Propose bearing_swap") for a in repair.actions)
    assert [i.score for i in items] == sorted((i.score for i in items), reverse=True)
    assert all(0 <= i.score <= 1 for i in items) and not repair.blocked


def test_missing_spare_blocks_the_repair_and_adds_a_reorder_recommendation(platform):
    wear(platform)
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.spares["bearing_set"] = 0
    platform.store.put("business_state", "kiln", ledger)
    items = {i.kind: i for i in recommendations.recommendations(platform, "kiln")}
    assert "lead time 72 h" in items["repair"].blocked
    assert items["spare_reorder"].title == "Order spare 'bearing_set'"


def test_orders_at_risk_recommendation_and_healthy_plant_is_quiet(platform):
    for _ in range(3):
        platform.sample("kiln")
    assert not [i for i in recommendations.recommendations(platform, "kiln") if i.kind == "repair"]
    platform.faults.inject("kiln", "rush_order", severity=1.0)
    platform.faults.inject("kiln", "demand_surge", severity=1.0)
    for _ in range(3):
        platform.sample("kiln")
    kinds = [i.kind for i in recommendations.recommendations(platform, "kiln")]
    assert "orders_at_risk" in kinds


# API


def test_insight_api_round_trip():
    with TestClient(create_app(":memory:")) as client:
        plant = "cement-demo"
        client.post(
            f"/api/plants/{plant}/faults",
            json={"kind": "kiln_drive_bearing_wear", "severity": 1, "ramp_ticks": 0},
        )
        client.post(f"/api/plants/{plant}/world/start", json={"interval_seconds": 0.2})
        import time

        time.sleep(1.6)
        client.post(f"/api/plants/{plant}/world/stop")
        assert client.get(f"/api/plants/{plant}/kpis").json()["energy_per_t_gj"] >= 0
        assert client.get(f"/api/plants/{plant}/kpis/history?limit=3").json()
        assert client.get(f"/api/plants/{plant}/impact").json()["summary"]["records"] == 0
        orders = client.get(f"/api/plants/{plant}/work-orders").json()
        assert orders and orders[0]["status"] == "open"
        assert (
            client.post(f"/api/work-orders/{orders[0]['id']}/cancel").json()["status"]
            == "cancelled"
        )
        assert client.post(f"/api/work-orders/{orders[0]['id']}/cancel").status_code == 409
        assert client.post("/api/work-orders/wo-none/cancel").status_code == 404
        bad = client.post(
            f"/api/plants/{plant}/work-orders", json={"equipment": "drive", "remedy": "x"}
        )
        assert bad.status_code == 422
        made = client.post(
            f"/api/plants/{plant}/work-orders",
            json={"equipment": "drive", "remedy": "bearing_swap"},
        )
        assert made.status_code == 201
        recs = client.get(f"/api/plants/{plant}/recommendations").json()
        repair = next(r for r in recs if r["kind"] == "repair")
        accepted = client.post(f"/api/recommendations/{repair['id']}/accept").json()
        assert accepted["work_order"]["equipment"] == "drive"
        assert client.post(f"/api/recommendations/{repair['id']}/accept").status_code == 404
        rest = client.get(f"/api/plants/{plant}/recommendations").json()
        assert all(r["id"] != repair["id"] for r in rest)
        if rest:
            assert client.post(f"/api/recommendations/{rest[0]['id']}/dismiss").status_code == 200
        assert client.get("/api/incidents/none/report").status_code == 404
        candidates = client.get(
            f"/api/plants/{plant}/cores/optimization/candidates?goal=energy"
        ).json()
        assert candidates["goal"] == "energy" and "reference" in candidates
        assert (
            client.get(f"/api/plants/{plant}/cores/optimization/candidates?goal=x").status_code
            == 422
        )
        plan = client.get(f"/api/plants/{plant}/cores/optimization/plan?problem=spares").json()
        assert "served" in plan
        assert (
            client.get(f"/api/plants/{plant}/cores/optimization/plan?problem=zzz").status_code
            == 422
        )
        assert client.get("/api/plants/missing/kpis").status_code == 404
