"""Industry-scoped official MCP server for cognitive data and simulation tools."""

from contextlib import asynccontextmanager

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from cognition.industries import get_industry
from cognition.layers.cognitive.catalog import sdk_functions
from cognition.layers.cognitive.tools import Tools
from cognition.mcp.runtime import BearerGuard, serve


def build_incident_server(tools: Tools) -> MCPServer:
    profile = get_industry(tools.request.snapshot.spec.industry).PROFILE
    server = MCPServer(
        f"Fabrix {profile.id} incident",
        instructions=(
            "Scoped observations and simulations only. "
            "Command execution is a separate gateway authority."
        ),
    )
    for function in sdk_functions(tools):
        server.tool(
            annotations=ToolAnnotations(
                # ask_core may run a T0 verification mission, so it is not read-only.
                read_only_hint=function.__name__ != "ask_core",
                open_world_hint=function.__name__ == "delegate_specialist",
            )
        )(function)
    return server


# The Antigravity harness uses an MCP server's `timeout_seconds` as the limit for each tool call.
# At 10 s, slow tools (ask_core runs a core agent and takes 30 to 60 s) were reported to the model
# as timed out while the server was still working, and the calls behind them queued up and timed
# out too. The investigation's own limit (COGNITION_TIMEOUT) still bounds the whole run.
TOOL_CALL_SECONDS = 300


@asynccontextmanager
async def incident_mcp(tools: Tools):
    from google.antigravity.types import McpStreamableHttpServer

    async with serve(build_incident_server(tools)) as endpoint:
        yield McpStreamableHttpServer(
            name="incident",
            url=endpoint.url,
            headers={"Authorization": f"Bearer {endpoint.token}"},
            enabled_tools=[fn.__name__ for fn in tools.functions()],
            timeout_seconds=TOOL_CALL_SECONDS,
            timeout=35,
            sse_read_timeout=TOOL_CALL_SECONDS,
        )


__all__ = ["BearerGuard", "build_incident_server", "incident_mcp"]
