"""Async MCP-backed functions for SDKs whose native tool surface is callable-based."""

import inspect
from contextlib import asynccontextmanager

from mcp import Client

from cognition.layers.cognitive.catalog import sdk_functions
from cognition.layers.cognitive.tools import Tools
from cognition.mcp.incident import build_incident_server


def proxy(client: Client, function):
    signature = inspect.signature(function)

    async def invoke(*args, **kwargs):
        arguments = signature.bind(*args, **kwargs)
        arguments.apply_defaults()
        result = await client.call_tool(function.__name__, dict(arguments.arguments))
        if result.is_error:
            raise RuntimeError("Scoped MCP tool rejected the request")
        data = result.structured_content
        if data is None:
            raise RuntimeError("MCP tool did not return typed data")
        # Official SDK wraps list output in the result member.
        if set(data) == {"result"} and isinstance(data["result"], list):
            return data["result"]
        return data

    invoke.__name__ = function.__name__
    invoke.__doc__ = function.__doc__
    invoke.__annotations__ = function.__annotations__
    invoke.__signature__ = signature  # type: ignore[attr-defined]
    return invoke


@asynccontextmanager
async def tool_functions(tools: Tools):
    async with Client(build_incident_server(tools)) as client:
        yield [proxy(client, function) for function in sdk_functions(tools)]
