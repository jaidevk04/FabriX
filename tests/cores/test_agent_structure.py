import importlib
import inspect
from pathlib import Path

import pytest

import cognition
from cognition.agentkit.skills import list_skills
from cognition.agentkit.tools import REGISTRY, bind_tool, lint_tool, tools_for
from cognition.cores.context import CoreContext

CORES = ("learning", "vision", "robot", "optimization")
ROOT = Path(cognition.__file__).parent / "cores"
for core in CORES:
    importlib.import_module(f"cognition.cores.{core}.tools")


@pytest.mark.parametrize("core", CORES)
def test_each_core_folder_follows_the_standard_layout(core):
    folder = ROOT / core
    for name in (
        "instruction.md",
        "agent.py",
        "schemas.py",
        "monitor.py",
        "reference.py",
        "README.md",
    ):
        assert (folder / name).is_file(), f"{core}/{name}"
    assert (folder / "tools" / "__init__.py").is_file()
    assert list_skills(folder / "skills"), f"{core} has no skills"
    assert (ROOT / "_shared" / "skills" / "core-report-writing" / "SKILL.md").is_file()
    assert "Boundaries" in (folder / "instruction.md").read_text()


@pytest.mark.parametrize("core", CORES)
def test_one_tool_per_file_with_the_core_prefix(core):
    files = {p.stem for p in (ROOT / core / "tools").glob("*.py") if p.stem != "__init__"}
    registered = {spec.name for spec in tools_for(core)}
    assert files == registered
    assert all(name.startswith(f"{core}_") for name in registered)
    for spec in tools_for(core):
        assert spec.function.__module__.endswith(spec.name)


@pytest.mark.parametrize("core", CORES)
def test_every_core_has_exactly_one_bound_action_tool_and_a_readme_that_lists_everything(core):
    assert len(tools_for(core, "action")) == 1
    readme = (ROOT / core / "README.md").read_text()
    for spec in tools_for(core):
        assert f"`{spec.name}`" in readme
    for skill in list_skills(ROOT / core / "skills"):
        assert f"`{skill.name}`" in readme


def test_all_core_tools_pass_lint_and_names_are_unique():
    assert len(REGISTRY) >= 25
    assert [p for spec in REGISTRY.values() for p in lint_tool(spec.function, spec.core)] == []


def test_action_tools_are_zero_argument_once_the_context_is_hidden(platform):
    for core in CORES:
        ctx = CoreContext(platform, "kiln", core)
        (spec,) = tools_for(core, "action")
        bound = bind_tool(ctx, spec.function)
        assert list(inspect.signature(bound).parameters) == []
        assert "ctx" not in bound.__annotations__


def test_bound_action_tools_do_nothing_without_an_order(platform):
    import asyncio

    for core in CORES:
        ctx = CoreContext(platform, "kiln", core)
        (spec,) = tools_for(core, "action")
        result = asyncio.run(spec.function(ctx))
        assert result["status"] == "error" and not ctx.called
    assert platform.store.records("commands") == []


READ_CALLS = {
    "learning_list_channels": {},
    "learning_read_features": {"channel": "drive_vibration", "response_format": "detailed"},
    "learning_read_encoder_scores": {},
    "learning_compare_baseline": {"channel": "drive_current"},
    "learning_estimate_remaining_life": {"equipment": "drive"},
    "learning_request_evidence": {
        "to_core": "vision",
        "kind": "read_detections",
        "target": "burner",
        "question": "q",
    },
    "vision_list_cameras": {},
    "vision_read_detections": {},
    "vision_measure_defect": {"camera": "flame_cam", "label": "flame instability"},
    "vision_compare_reference": {"camera": "flame_cam"},
    "vision_request_evidence": {
        "to_core": "learning",
        "kind": "read_signal_evidence",
        "target": "drive",
        "question": "q",
    },
    "robot_read_fleet": {},
    "robot_read_zones": {},
    "robot_check_mission": {"kind": "inspect", "target": "drive", "tool_name": "acoustic"},
    "robot_read_mission_result": {"mission_id": "mis-none"},
    "robot_request_evidence": {
        "to_core": "learning",
        "kind": "read_signal_evidence",
        "target": "drive",
        "question": "q",
    },
    "optimization_read_problem_context": {},
    "optimization_search_duty": {},
    "optimization_evaluate_candidate": {"value": 45},
    "optimization_solve_assignment": {"problem": "maintenance_window"},
    "optimization_read_followup_status": {"incident_id": "none"},
    "optimization_request_evidence": {
        "to_core": "robot",
        "kind": "read_fleet_state",
        "target": "drive",
        "question": "q",
    },
}


def tables(platform):
    names = (
        "commands",
        "business_state",
        "missions",
        "world_events",
        "action_orders",
        "core_config",
    )
    return {n: platform.store.records(n) for n in names} | {"plants": platform.store.plants()}


def test_read_tools_write_nothing_and_return_data(platform):
    platform.faults.inject("kiln", "flame_instability", severity=1.0, ramp_ticks=0)
    for _ in range(3):
        platform.sample("kiln")
    before = tables(platform)
    read_tools = [s for s in REGISTRY.values() if s.kind == "read"]
    assert {s.name for s in read_tools} == set(READ_CALLS)
    for spec in read_tools:
        ctx = CoreContext(platform, "kiln", spec.core)
        result = spec.function(ctx, **READ_CALLS[spec.name])
        assert isinstance(result, dict) and result
    assert tables(platform) == before


def test_read_tools_give_actionable_errors_not_exceptions(platform):
    ctx = CoreContext(platform, "kiln", "learning")
    assert REGISTRY["learning_read_features"].function(ctx, "nope")["hint"]
    assert REGISTRY["learning_read_features"].function(ctx, "draft")["status"] == "error"
    vision = CoreContext(platform, "kiln", "vision")
    assert REGISTRY["vision_measure_defect"].function(vision, "flame_cam", "x")["status"] == "error"
    bad = REGISTRY["learning_request_evidence"].function(
        ctx, "learning", "read_detections", "drive", "q"
    )
    assert bad["status"] == "error"
    opt = CoreContext(platform, "kiln", "optimization")
    assert REGISTRY["optimization_evaluate_candidate"].function(opt, 999)["status"] == "error"


def test_fleet_tool_only_runs_t0_and_t1_missions(platform):
    ctx = CoreContext(platform, "kiln", "robot")
    run = REGISTRY["robot_run_mission"].function
    assert run(ctx, "lockout", "drive")["status"] == "error"
    assert run(ctx, "inspect", "drive", "acoustic")["tier"] == "T0"
    assert platform.fleet.state("kiln").lockouts == []
