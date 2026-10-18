import importlib
import json
from pathlib import Path

import pytest

from cognition.agentkit.evals import expected_tools, load_evalset, scripted_model, trajectory_ok
from cognition.agentkit.tools import REGISTRY, tools_for
from cognition.cores.agents import CoreAgents
from cognition.cores.runs import CoreBusy  # noqa: F401  (import check)

CORES = ("learning", "vision", "robot", "optimization")
HERE = Path(__file__).parent
FINDING = {"summary": "ok", "status": "watch", "confidence": 0.5, "findings": [], "next_checks": []}
EXECUTED = {"decision": "executed", "reason": ""}
for core in CORES:
    importlib.import_module(f"cognition.cores.{core}.tools")


def cases(core):
    return load_evalset(HERE / core / f"{core}.evalset.json")["eval_cases"]


@pytest.mark.parametrize("core", CORES)
def test_evalsets_are_valid_adk_format_and_use_real_tools(core):
    config = json.loads((HERE / core / "test_config.json").read_text())
    assert config["criteria"]["tool_trajectory_avg_score"] == 1.0
    for case in cases(core):
        turn = case["conversation"][0]
        assert turn["user_content"]["parts"][0]["text"] and turn["final_response"]["parts"]
        assert case["session_input"]["app_name"] == "fabrix_cores"
        for name in expected_tools(case):
            assert name in REGISTRY and REGISTRY[name].core == core


@pytest.mark.parametrize("core", CORES)
def test_every_tool_appears_in_at_least_one_eval_case(core):
    used = {name for case in cases(core) for name in expected_tools(case)}
    assert used == {spec.name for spec in tools_for(core)}


@pytest.mark.parametrize("core", CORES)
async def test_eval_cases_replay_offline_through_the_real_agent_without_tool_errors(platform, core):
    """Scripted model: proves names, arguments and wiring. It does not test reasoning."""
    from datetime import timedelta

    from cognition.domain import MaintenanceAction, Proposal, now

    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(3):
        platform.sample("kiln")
    agents = CoreAgents(platform)
    agents.override = True
    for case in cases(core):
        steps = [
            (u["name"], u["args"])
            for u in case["conversation"][0]["intermediate_data"]["tool_uses"]
        ]
        ordering = any(REGISTRY[n].kind == "action" for n, _ in steps)
        model = scripted_model(steps, EXECUTED if ordering else FINDING)
        agents.model_factory = lambda c, m, model=model: model
        if not ordering:
            await agents.analyse("kiln", core, "replay")
        else:
            action = MaintenanceAction(equipment="drive", remedy="bearing_swap")
            from cognition.domain import ActionOrder

            proposal = Proposal(
                plant_id="kiln",
                revision=platform.store.plant("kiln").revision,
                expires_at=now() + timedelta(seconds=60),
                summary="replay",
                action=action,
            )
            order = ActionOrder(
                incident_id="replay",
                plant_id="kiln",
                core=core,  # type: ignore[arg-type]
                control="maintenance",
                expires_at=now() + timedelta(seconds=60),
            )

            async def bound():
                from cognition.domain import Receipt

                return Receipt(
                    command_id="replay",
                    plant_id="kiln",
                    digest="x",
                    revision=0,
                    recovered=False,
                    trajectory=[],
                    verification="pending",
                )

            try:
                await agents.execute_order(order, proposal, bound)
            except Exception as error:  # a bound tool may legitimately reject this replay order
                assert type(error).__name__ in {"Rejected", "OrderRefused"}
        assert trajectory_ok([n for n, _ in steps], model.seen[:-1], "exact")
