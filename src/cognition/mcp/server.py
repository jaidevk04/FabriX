"""Read/simulate MCP facade over the running API; no control-write tools."""

import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from cognition.domain import Action, Industry, PlantSpec, State
from cognition.simulation.thermal import simulate


def build(base_url: str = "http://127.0.0.1:8000"):
    from mcp.server import MCPServer
    from mcp.types import ToolAnnotations

    mcp = MCPServer("Fabrix simulator catalog")

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def list_plants() -> list[dict]:
        """List revisioned plant telemetry from the running platform."""
        with urlopen(f"{base_url}/api/plants", timeout=10) as response:
            return json.load(response)

    @mcp.tool(
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def predict_action(plant_id: str, value: float) -> dict[str, Any]:
        """Predict a duty setpoint without writing controls; include source revision."""
        with urlopen(f"{base_url}/api/plants", timeout=10) as response:
            plants = json.load(response)
        for item in plants:
            state = State.model_validate(item)
            if state.spec.id == plant_id:
                return {
                    "revision": state.revision,
                    "prediction": simulate(state, Action(value=value)).model_dump(),
                }
        raise ValueError("Plant not found")

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    def discover_capabilities(plant_id: str, query: str = "") -> list[dict]:
        """Discover the local connector, tool, agent-role and control catalog."""
        PlantSpec(id=plant_id, name="validation", industry=Industry.CEMENT)
        url = f"{base_url}/api/plants/{plant_id}/capabilities?{urlencode({'query': query})}"
        with urlopen(url, timeout=10) as response:
            return json.load(response)

    return mcp


def main() -> None:
    build(os.getenv("COGNITION_API_URL", "http://127.0.0.1:8000")).run(transport="stdio")
