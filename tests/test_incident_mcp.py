from mcp import Client

from cognition.domain import Request
from cognition.harnesses.mcp_runtime import BearerGuard, build_incident_server
from cognition.layers.cognitive.tools import Tools


async def test_incident_mcp_preserves_scope_and_budget(platform):
    snapshot = platform.store.plant("kiln")
    tools = Tools(Request(incident_id="mcp-scope", snapshot=snapshot), platform.store, budget=2)
    platform.connector.disturb("kiln", "heat_load")
    async with Client(build_incident_server(tools)) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert names == {
            "discover",
            "read_snapshot",
            "read_time",
            "read_instruments",
            "forecast_instruments",
            "read_control",
            "read_sop",
            "simulate_action",
            "read_layers",
            "list_skills",
            "read_skill",
            "read_skill_resource",
            "read_kiln_process",
            "simulate_kiln_duty",
        }
        result = await client.call_tool("read_snapshot", {})
        assert result.structured_content["revision"] == snapshot.revision
        await client.call_tool("read_control", {})
        denied = await client.call_tool("read_sop", {})
        assert denied.is_error
    assert tools.calls == 2
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0


async def test_mcp_guard_rejects_missing_and_wrong_bearer():
    reached = []
    output = []

    async def app(scope, receive, send):
        reached.append(True)

    async def send(value):
        output.append(value)

    guard = BearerGuard(app, "incident-secret")
    for headers in ([], [(b"authorization", b"Bearer wrong")]):
        await guard({"type": "http", "headers": headers}, None, send)
    assert not reached
    assert all(item["status"] == 401 for item in output if item["type"] == "http.response.start")
    await guard(
        {"type": "http", "headers": [(b"authorization", b"Bearer incident-secret")]}, None, send
    )
    assert reached == [True]


async def test_time_and_instrument_tools_follow_simulation(platform):
    snapshot = platform.connector.tick("kiln", 3)
    tools = Tools(Request(incident_id="clock", snapshot=snapshot), platform.store)
    clock = tools.read_time()
    assert clock["simulated_elapsed_seconds"] == snapshot.sim_seconds > 0
    live = {i["id"]: i["value"] for i in tools.read_instruments()["indicators"]}
    forecast = tools.forecast_instruments(snapshot.duty)
    assert len(forecast["points"]) == 10
    assert forecast["points"][-1]["simulated_elapsed_seconds"] == snapshot.sim_seconds + 600
    assert set(forecast["points"][0]["values"]) == set(live)
