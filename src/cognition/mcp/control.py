"""Private official MCP command surface, available only to the platform executor.

The model never receives this server. One approved request is bound in the server
closure; the sole tool has no user-controlled action arguments. In-process MCP
transport still performs SDK tool discovery, schema validation and RPC dispatch.
"""

from mcp import Client
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from cognition.control.gateway import Gateway, Rejected
from cognition.domain import Proposal, Receipt


async def execute_authorized(
    gateway: Gateway,
    proposal: Proposal,
    command_id: str,
    plant_id: str,
    *,
    live: bool,
    max_drift: int = 0,
) -> Receipt:
    server = MCPServer("Fabrix authorized command")
    rejection: list[Rejected] = []

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
        )
    )
    def apply_validated_action() -> Receipt:
        """Execute the platform-bound approved request through the independent gateway."""
        try:
            return gateway.execute(proposal, command_id, plant_id, live=live, max_drift=max_drift)
        except Rejected as error:
            rejection.append(error)
            raise

    gateway.store.audit(
        command_id,
        "command_dispatch",
        {
            "transport": "mcp-in-process",
            "sdk": "modelcontextprotocol/python-sdk",
            "tool": "apply_validated_action",
        },
    )
    async with Client(server) as client:
        result = await client.call_tool("apply_validated_action", {})
    if rejection:
        raise rejection[0]
    if result.is_error:
        raise Rejected("Authorized MCP execution failed")
    return Receipt.model_validate(result.structured_content)
