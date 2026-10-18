import sys

import pytest
from mcp import Client

from cognition.domain import Request
from cognition.harnesses.base import ModelSettings
from cognition.harnesses.process import ProcessHarness
from cognition.harnesses.reference import ReferenceHarness
from cognition.layers.cognitive.catalog import sdk_functions
from cognition.layers.cognitive.tools import Tools
from cognition.mcp.incident import build_incident_server

CORE_TOOLS = {
    "read_core_live",
    "ask_core",
    "read_core_reports",
    "request_optimization",
    "read_business",
    "read_kpis",
    "read_sustainability",
}


def tools_for(platform, incident="core-tools", **kwargs):
    request = Request(incident_id=incident, snapshot=platform.store.plant("kiln"))
    return Tools(request, platform.store, services=platform, **kwargs)


def fault_and_sample(platform, ticks=3):
    platform.faults.inject("kiln", "kiln_drive_bearing_wear", severity=1.0, ramp_ticks=0)
    for _ in range(ticks):
        platform.sample("kiln")


def test_core_tools_exist_only_when_services_are_attached(platform):
    request = Request(incident_id="bare", snapshot=platform.store.plant("kiln"))
    assert not CORE_TOOLS & {fn.__name__ for fn in Tools(request, platform.store).functions()}
    assert CORE_TOOLS <= {fn.__name__ for fn in tools_for(platform).functions()}
    assert CORE_TOOLS <= {fn.__name__ for fn in sdk_functions(tools_for(platform))}
    with pytest.raises(PermissionError, match="not attached"):
        Tools(request, platform.store).read_kpis()


def test_read_core_live_is_stamped_filtered_and_helpful_on_mistakes(platform):
    fault_and_sample(platform)
    tools = tools_for(platform)
    concise = tools.read_core_live("learning")
    assert concise["status"] == "alert" and concise["alerts"][0]["equipment"] == "drive"
    assert "evidence" not in concise["alerts"][0] and concise["stamp"]["revisions_behind"] == 0
    detailed = tools.read_core_live("learning", response_format="detailed")
    assert detailed["alerts"][0]["evidence"] and "assessment" in detailed
    assert tools.read_core_live("learning", scope="burner")["alerts"] == []
    assert tools.read_core_live("warp")["status"] == "error"
    assert tools.read_core_live("learning", response_format="huge")["status"] == "error"


def test_reports_are_frozen_but_live_reads_keep_moving(platform):
    tools = tools_for(platform)
    fault_and_sample(platform)
    frozen = tools.read_core_reports()
    assert {r["core"] for r in frozen["reports"]} == {"learning", "vision", "robot", "optimization"}
    assert all(r["status"] == "normal" for r in frozen["reports"])
    assert tools.read_core_live("learning")["status"] == "alert"
    assert tools.read_core_live("learning")["stamp"]["revisions_behind"] == 0
    platform.sample("kiln")
    live = tools.read_core_live("learning")["stamp"]
    assert live["revision"] == platform.store.plant("kiln").revision
    assert tools.read_core_reports()["frozen_at_revision"] == 0


async def test_ask_core_uses_the_reference_analyser_and_audits(platform):
    fault_and_sample(platform)
    tools = tools_for(platform)
    answer = await tools.ask_core("learning", "Which fault fits the drive vibration?")
    assert answer["stamp"]["source"] == "reference"
    detailed = await tools.ask_core("learning", "Which fault?", "detailed")
    assert detailed["assessment"]["candidates"][0]["fault"] == "kiln_drive_bearing_wear"
    assert (await tools.ask_core("warp", "x"))["status"] == "error"
    assert (await tools.ask_core("learning", " "))["status"] == "error"
    kinds = [e["kind"] for e in platform.store.events("cores:kiln")]
    assert kinds.count("core_query") == 2
    assert platform.store.records("commands") == []


def test_request_optimization_ranks_safe_candidates_and_writes_nothing(platform):
    platform.connector.disturb("kiln", "heat_load")
    tools = tools_for(platform)
    recovery = tools.request_optimization("recovery")
    assert recovery["candidates"] and all(c["safe"] for c in recovery["candidates"])
    assert recovery["best"]["executable"] and recovery["best"]["recovery_ticks"] is not None
    energy = tools.request_optimization("energy")["candidates"]
    executable = [c for c in energy if c["executable"]]
    assert executable[0]["fuel_gj_per_h"] <= min(c["fuel_gj_per_h"] for c in executable)
    assert tools.request_optimization("luck")["status"] == "error"
    narrow = tools.request_optimization("recovery", 5)["candidates"]
    assert all(abs(c["value"] - 50) <= 5 for c in narrow)
    assert platform.store.records("commands") == []


def test_business_kpi_and_sustainability_reads(platform):
    for _ in range(5):
        platform.sample("kiln")
    tools = tools_for(platform)
    business = tools.read_business()
    assert business["metrics"]["production_rate_tph"] > 0 and business["next_orders"]
    kpi = tools.read_kpis()
    assert 0 < kpi["oee"] <= 1 and "placeholder" in kpi["basis"] or "Simulated" in kpi["basis"]
    green = tools.read_sustainability()
    assert green["rates"]["co2e_kg_per_h"] > 0 and "placeholder" in green["basis"]


async def test_core_tools_are_read_only_mcp_tools(platform):
    tools = tools_for(platform)
    async with Client(build_incident_server(tools)) as client:
        listed = (await client.list_tools()).tools
        names = {t.name for t in listed}
        assert CORE_TOOLS <= names and "apply_validated_action" not in names
        assert all(
            t.annotations.read_only_hint for t in listed if t.name in CORE_TOOLS - {"ask_core"}
        )
        result = await client.call_tool("read_core_live", {"core": "vision"})
        assert result.structured_content["core"] == "vision"
        asked = await client.call_tool("ask_core", {"core": "robot", "question": "Fleet ready?"})
        assert asked.structured_content["stamp"]["source"] == "reference"


async def test_reference_harness_cites_core_evidence_when_a_spare_is_missing(platform):
    fault_and_sample(platform, 4)
    ledger = platform.business.ledger(platform.store.plant("kiln"))
    ledger.spares["bearing_set"] = 0
    platform.store.put("business_state", "kiln", ledger)
    incident = await platform.resolve("kiln", ReferenceHarness(), live=True)
    assert incident.status == "escalated"
    assert incident.proposal is not None
    assert "bearing_set" in (incident.proposal.escalation or "")
    assert "learning core" in (incident.proposal.escalation or "")
    assert any(item.startswith("learning core") for item in incident.proposal.evidence)
    assert platform.store.records("commands") == []


async def test_core_tools_work_through_the_worker_process(platform):
    fault_and_sample(platform, 4)
    harness = ProcessHarness("reference", sys.executable, ModelSettings())
    incident = await platform.resolve("kiln", harness, live=True)
    assert incident.status == "verifying"
    assert incident.proposal is not None and incident.proposal.action is not None
    assert incident.proposal.action.control == "maintenance"


def test_tool_cap_is_high_and_configurable(platform, monkeypatch):
    assert tools_for(platform).budget == 200
    monkeypatch.setenv("COGNITION_TOOL_CAP", "7")
    assert tools_for(platform).budget == 7
    monkeypatch.setenv("COGNITION_TOOL_CAP", "junk")
    assert tools_for(platform).budget == 200
