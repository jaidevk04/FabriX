from datetime import timedelta

import pytest

from cognition.control.gateway import Rejected
from cognition.cores.context import CoreContext
from cognition.cores.optimization.objectives import (
    GOALS,
    golden_section,
    optimize,
    predict,
    recovery_ticks,
)
from cognition.cores.optimization.solvers import (
    assign_robots,
    assign_spares,
    diagnosed_repairs,
    plan_maintenance_window,
)
from cognition.cores.optimization.tools.optimization_solve_assignment import (
    optimization_solve_assignment,
)
from cognition.domain import Action, MaintenanceAction, Proposal, now


def hurt(platform, ticks=10, bearing=1.0):
    platform.faults.inject("kiln", "flame_instability", severity=0.8, ramp_ticks=0)
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=bearing, ramp_ticks=0)
    for _ in range(ticks):
        platform.sample("kiln")
    return platform.store.plant("kiln")


def proposal(platform, value):
    state = platform.store.plant("kiln")
    return Proposal(
        plant_id="kiln",
        revision=state.revision,
        expires_at=now() + timedelta(seconds=60),
        summary="candidate",
        action=Action(value=value),
    )


def test_golden_section_and_recovery_ticks():
    assert golden_section(lambda x: (x - 41.3) ** 2, 30, 60, tol=0.05) == pytest.approx(
        41.3, abs=0.2
    )
    assert recovery_ticks([10, 9, 3, 1, 0, 1], 0, 3) == 2
    assert recovery_ticks([10, 9, 8], 0, 3) is None
    assert recovery_ticks([0, 9, 0], 0, 3) == 2


def test_predict_adds_business_effects_to_the_forecast(platform):
    state = hurt(platform)
    result = predict(platform, state, 45.0)
    assert result["recovered"] and result["safe"] and result["recovery_ticks"] is not None
    assert result["fuel_gj_per_h"] > 0 and result["co2e_kg_per_h"] > 0
    assert predict(platform, state, 50.0)["value"] == 50.0
    with pytest.raises(ValueError):
        predict(platform, state, 95.0)


def test_every_goal_returns_executable_safe_candidates_the_gateway_accepts(platform):
    state = hurt(platform)
    for goal in GOALS:
        result = optimize(platform, state, goal)
        assert result["best"] and all(c["safe"] for c in result["candidates"])
        assert result["best"]["executable"], goal
        platform.gateway.validate(proposal(platform, result["best"]["value"]), "kiln")
        scores = [c["score"] for c in result["candidates"]]
        assert scores == sorted(scores)
    assert platform.store.records("commands") == []


def test_goals_pull_the_answer_in_different_directions(platform):
    state = hurt(platform)
    best = {g: optimize(platform, state, g)["best"] for g in GOALS}
    rows = [c for c in optimize(platform, state, "recovery")["candidates"] if c["executable"]]
    assert best["recovery"]["recovery_ticks"] <= min(c["recovery_ticks"] for c in rows)
    assert best["energy"]["energy_cost_per_h"] <= best["recovery"]["energy_cost_per_h"]
    assert best["co2e"]["co2e_kg_per_h"] <= best["recovery"]["co2e_kg_per_h"]
    assert best["scrap"]["scrap_fraction"] <= best["recovery"]["scrap_fraction"]
    only_scrap = optimize(platform, state, "balanced", weights={"scrap": 1.0})["best"]
    assert only_scrap["scrap_fraction"] == best["scrap"]["scrap_fraction"]


def test_tradeoffs_say_what_runner_ups_give_up_and_range_is_respected(platform):
    state = hurt(platform)
    result = optimize(platform, state, "energy", max_change=6)
    assert all(abs(c["value"] - state.duty) <= 6 for c in result["candidates"])
    assert result["tradeoffs"] and "GJ/h" in result["tradeoffs"][0]["summary"]
    assert result["reference"]["value"] == state.duty


def test_assign_spares_maximises_priority_within_stock():
    requests = [
        {"id": "a", "part": "bearing", "priority": 9},
        {"id": "b", "part": "bearing", "priority": 5},
        {"id": "c", "part": "seal", "priority": 4},
        {"id": "d", "part": None, "priority": 1},
    ]
    result = assign_spares(requests, {"bearing": 1, "seal": 1})
    assert {r["id"] for r in result["served"]} == {"a", "c", "d"}
    assert [r["id"] for r in result["unserved"]] == ["b"]
    assert assign_spares(requests, {})["total_priority"] == 1
    assert assign_spares([], {"x": 1}) == {"served": [], "unserved": [], "total_priority": 0.0}


def test_assign_robots_minimises_travel_respects_role_and_battery():
    robots = [
        {"name": "Near", "kind": "inspector", "zone": "z1", "battery": 90},
        {"name": "Far", "kind": "inspector", "zone": "z3", "battery": 90},
        {"name": "Low", "kind": "inspector", "zone": "z1", "battery": 10},
        {"name": "Carry", "kind": "carrier", "zone": "z1", "battery": 90},
    ]
    missions = [{"id": "m1", "role": "inspector", "zone": "z1"}]
    hops = lambda a, b: abs(int(a[1]) - int(b[1]))  # noqa: E731
    result = assign_robots(missions, robots, hops)
    assert result["assignments"] == [{"mission": "m1", "robot": "Near"}]
    two = assign_robots(missions + [{"id": "m2", "role": "inspector", "zone": "z3"}], robots, hops)
    assert {a["robot"] for a in two["assignments"]} == {"Near", "Far"}
    none = assign_robots([{"id": "m3", "role": "maintainer", "zone": "z1"}], robots, hops)
    assert none["unassigned"] == ["m3"]


def test_maintenance_window_prefers_repairing_before_a_predicted_breakdown(platform):
    state = hurt(platform)
    repairs = diagnosed_repairs(platform, "kiln", [])
    assert {r["equipment"] for r in repairs} >= {"drive", "burner"}
    plan = plan_maintenance_window(platform, state, repairs)
    names = [p["plan"] for p in plan["plans"]]
    assert names[:2] == ["no_repair", "repair_now"]
    by_name = {p["plan"]: p for p in plan["plans"]}
    assert by_name["no_repair"]["breakdown_at_hours"] == 1.0
    assert plan["best"] == "repair_now"
    assert plan["best"] == max(plan["plans"], key=lambda p: p["net_value"])["plan"]
    assert plan["downtime_hours"] > 0 and plan["parts_cost"] > 0


def test_solve_assignment_tool_covers_three_problems_and_explains_failures(platform):
    hurt(platform)
    ctx = CoreContext(platform, "kiln", "optimization")
    window = optimization_solve_assignment(ctx, "maintenance_window", horizon_hours=99)
    assert window["best"] and window["plans"]
    spares = optimization_solve_assignment(ctx, "spares", "drive")
    assert [s["id"] for s in spares["served"]] == ["drive"] and spares["stock"]["bearing_set"] == 2
    robots = optimization_solve_assignment(ctx, "robots")
    assert robots["assignments"]
    assert optimization_solve_assignment(ctx, "dance")["status"] == "error"
    assert optimization_solve_assignment(ctx, "spares", "warp-core")["status"] == "error"


def test_solve_assignment_without_evidence_asks_for_a_diagnosis_first(platform):
    ctx = CoreContext(platform, "kiln", "optimization")
    result = optimization_solve_assignment(ctx, "maintenance_window")
    assert result["status"] == "error" and "learning" in result["hint"]


def test_spare_shortage_leaves_the_repair_unserved_in_the_plan(platform):
    hurt(platform)
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.spares["bearing_set"] = 0
    platform.store.put("business_state", "kiln", ledger)
    ctx = CoreContext(platform, "kiln", "optimization")
    spares = optimization_solve_assignment(ctx, "spares")
    assert "drive" in [s["id"] for s in spares["unserved"]]


def test_optimization_reference_analyser_summarises_duty_window_and_spares(platform):
    report = platform.cores.live("kiln", "optimization", reference=True)
    assert "Idle" in report.summary or "duty" in report.summary
    hurt(platform)
    report = platform.cores.live("kiln", "optimization", reference=True)
    assert report.source == "reference" and report.alerts == []
    assert {"duty", "maintenance", "spares"} <= set(report.assessment)


def test_repair_downtime_stops_production_then_it_resumes(platform):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(3):
        platform.sample("kiln")
    before = platform.business.read("kiln")["metrics"].production_rate_tph
    platform.fleet_gateway.run("kiln", "lockout", "drive")
    state = platform.store.plant("kiln")
    proposal_ = Proposal(
        plant_id="kiln",
        revision=state.revision,
        expires_at=now() + timedelta(seconds=60),
        summary="repair",
        action=MaintenanceAction(equipment="drive", remedy="bearing_swap"),
    )
    platform.gateway.execute(proposal_, "downtime", "kiln", live=True)
    platform.sample("kiln")
    assert platform.business.read("kiln")["metrics"].production_rate_tph == 0
    for _ in range(150):  # 0.4 simulated hours is 144 ticks
        platform.sample("kiln")
    after = platform.business.read("kiln")
    assert after["metrics"].production_rate_tph > before
    assert after["ledger"].downtime_ticks >= 140
    with pytest.raises(Rejected):
        platform.gateway.execute(
            proposal_.model_copy(update={"summary": "again"}), "downtime", "kiln"
        )
