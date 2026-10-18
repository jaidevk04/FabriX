"""Offline native MCP transport smoke check; never calls a model or controls."""

import asyncio

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from cognition.domain import Industry, PlantSpec, Request
from cognition.harnesses.antigravity import AntigravityHarness
from cognition.harnesses.base import ModelSettings
from cognition.layers.cognitive.tools import Tools
from cognition.mcp.incident import build_incident_server, incident_mcp
from cognition.mcp.runtime import serve
from cognition.persistence.store import Store
from cognition.simulation.thermal import onboard


async def main():
    from google.antigravity import Agent

    store = Store()
    try:
        request = Request(
            incident_id="native-mcp-check",
            snapshot=onboard(PlantSpec(id="unit", name="Unit", industry=Industry.CEMENT)),
        )
        tools = Tools(request, store)
        async with serve(build_incident_server(tools)) as endpoint:
            async with httpx.AsyncClient() as http:
                denied = await http.post(endpoint.url, json={})
                assert denied.status_code == 401
            async with httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {endpoint.token}"}
            ) as http:
                client_transport = streamable_http_client(endpoint.url, http_client=http)
                async with Client(client_transport) as client:
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    assert "read_kiln_process" in names and "apply_validated_action" not in names
                    result = await client.call_tool("read_kiln_process", {})
                    assert result.structured_content["industry"] == "cement"
                    assert not result.is_error
        # Construct and connect the real native SDK without sending chat requests.
        import os

        os.environ["GOOGLE_API_KEY"] = "offline-construction-only"
        harness = AntigravityHarness(ModelSettings(model="gemini-3.8-flash"))
        async with incident_mcp(tools) as server, Agent(harness.build(tools, server)):
            print(
                "Official MCP HTTP scope, bearer guard and native Antigravity connection passed; "
                "no model request."
            )
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
