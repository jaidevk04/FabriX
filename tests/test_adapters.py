import sys
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest

from cognition.domain import Proposal, Request
from cognition.harnesses.antigravity import sdk_functions
from cognition.harnesses.base import ModelSettings
from cognition.harnesses.factory import create
from cognition.harnesses.process import ProcessHarness
from cognition.harnesses.reference import ReferenceHarness
from cognition.layers.cognitive.tools import Tools


@pytest.mark.parametrize("isolated", [False, True])
async def test_native_and_worker_share_contract(platform, isolated):
    platform.connector.disturb("kiln", "heat_load")
    harness = (
        ProcessHarness("reference", sys.executable, ModelSettings())
        if isolated
        else ReferenceHarness()
    )
    incident = await platform.resolve("kiln", harness)
    assert incident.status == "resolved"
    assert incident.proposal.action.value == 36
    calls = [e for e in platform.store.events(incident.id) if e["kind"] == "tool_called"]
    assert len(calls) == 31  # 28 plant tools + 3 core reads
    assert {"read_skill", "read_layers", "read_kiln_process", "simulate_kiln_duty"} <= {
        e["body"]["name"] for e in calls
    }


def test_tool_permissions_budget_and_frozen_snapshot(platform):
    request = Request(incident_id="test", snapshot=platform.store.plant("kiln"))
    tools = Tools(request, platform.store, budget=2)
    platform.connector.disturb("kiln", "heat_load")
    assert tools.read_snapshot()["revision"] == 0
    assert tools.discover("control")
    with pytest.raises(PermissionError):
        tools.simulate_action(36)
    assert "execute" not in {fn.__name__ for fn in tools.functions()}


def test_factory_rejects_unknown_and_missing_credentials(monkeypatch):
    with pytest.raises(ValueError, match="Unknown"):
        create("unknown")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API_KEY"):
        ModelSettings(model="configured-model").validate()
    with pytest.raises(ValueError, match="PROJECT"):
        replace(ModelSettings(model="configured-model"), vertex=True).validate()


def test_installed_plugin_selection_without_core_changes():
    class Plugin:
        name = "custom"

        def load(self):
            return lambda settings: ReferenceHarness()

    with patch("cognition.harnesses.factory.entry_points", return_value=[Plugin()]):
        assert create("custom").capabilities().name == "reference"


async def test_malformed_adapter_output_never_executes(platform):
    class Malformed(ReferenceHarness):
        async def propose(self, request, tools):
            return {"action": {"value": 36}}

    incident = await platform.resolve("kiln", Malformed())
    assert incident.status == "failed"
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0


async def test_wrong_scope_proposal_is_rejected(platform):
    class WrongScope(ReferenceHarness):
        async def propose(self, request, tools):
            result = await super().propose(request, tools)
            return Proposal.model_validate(result.model_dump() | {"plant_id": "other"})

    platform.connector.disturb("kiln", "heat_load")
    incident = await platform.resolve("kiln", WrongScope())
    assert incident.status == "escalated"
    assert "scope" in incident.reason


def test_antigravity_config_copy_keeps_scoped_tools_and_shared_budget(platform):
    request = Request(incident_id="sdk-copy", snapshot=platform.store.plant("kiln"))
    tools = Tools(request, platform.store, budget=2)
    functions = {fn.__name__: fn for fn in deepcopy(sdk_functions(tools))}
    platform.connector.disturb("kiln", "heat_load")
    assert functions["read_snapshot"]()["revision"] == request.snapshot.revision
    assert functions["read_control"]()["max_change"] == 20
    with pytest.raises(PermissionError, match="budget"):
        functions["simulate_action"](36)
    assert "execute" not in functions
