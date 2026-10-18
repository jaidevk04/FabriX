import json

import pytest
from fastapi.testclient import TestClient

from cognition import cli
from cognition.api import create_app
from cognition.evaluation.stories import STORIES, run_story
from cognition.evaluation.suite import run_all, run_scenario
from cognition.industries import catalogue


def test_every_story_step_names_a_real_event():
    for story in STORIES.values():
        known = catalogue(story.industry)
        assert all(step.kind in known for step in story.steps if step.action != "automation")


async def test_control_run_stays_quiet():
    result = await run_scenario(STORIES["cement-quiet"])
    assert result["passed"], result["checks"]
    assert result["metrics"]["false_alarms"] == 0
    assert result["metrics"]["incidents"] == []


async def test_fault_story_detects_and_recovers_offline():
    result = await run_scenario(STORIES["cement-bearing-wear"])
    assert result["passed"], result["checks"]
    assert result["metrics"]["detection_ticks"]["drive"] is not None
    assert result["metrics"]["cost"]["agent_runs"] == 0


async def test_unknown_scenario_is_rejected():
    with pytest.raises(KeyError):
        await run_all("nope")


def test_story_runner_plays_every_step(monkeypatch):
    monkeypatch.setenv("COGNITION_CORE_AGENTS", "false")
    story = STORIES["cement-bearing-wear"]
    with TestClient(create_app(":memory:")) as client:
        lines = run_story(client, story, "cement-demo", sleep=lambda _: None, say=lambda _: None)
        assert any("injected kiln_drive_bearing_wear" in line for line in lines)
        kinds = {e["kind"] for e in client.get("/api/plants/cement-demo/faults").json()}
        assert "kiln_drive_bearing_wear" in kinds
        assert client.get("/api/automation").json()
        client.delete("/api/plants/cement-demo/automation")
        client.post("/api/plants/cement-demo/world/stop")


def test_live_evaluation_needs_confirmation(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(cli.asyncio, "run", lambda coro: called.append(coro) or coro.close())
    for argv in (["--harness", "adk"], ["--agents"]):
        args = cli.argparse.Namespace(
            scenario=None, list=False, json=False, harness="reference", agents=False, yes=False
        )
        for flag, value in zip(argv[::2], argv[1::2] or [True], strict=False):
            setattr(args, flag.lstrip("-"), value)
        assert cli.evaluate(args) == 2
    assert called == []
    assert "charges" in capsys.readouterr().err


def test_evaluate_lists_and_reports_json(capsys):
    args = cli.argparse.Namespace(
        scenario="cement-quiet",
        list=False,
        json=True,
        harness="reference",
        agents=False,
        yes=False,
    )
    assert cli.evaluate(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["story"] == "cement-quiet" and data[0]["passed"]
