"""Build real SDK objects without making model calls. Run in each SDK environment."""

import argparse
import asyncio
import os
from importlib.metadata import version

from cognition.domain import Industry, PlantSpec, Request
from cognition.harnesses.base import ModelSettings
from cognition.harnesses.factory import create
from cognition.layers.cognitive.tools import Tools
from cognition.persistence.store import Store
from cognition.simulation.thermal import onboard


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", choices=["deepagents", "adk", "antigravity"])
    args = parser.parse_args()
    os.environ["GOOGLE_API_KEY"] = "offline-construction-only"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
    # Construction accepts a model identifier without checking account availability.
    settings = ModelSettings(model="gemini-3.8-flash")
    store = Store()
    try:
        request = Request(
            incident_id="sdk-smoke",
            snapshot=onboard(PlantSpec(id="unit", name="Unit", industry=Industry.CEMENT)),
        )
        harness = create(args.name, settings, isolated=False)
        native = harness.build(Tools(request, store))
        if args.name == "antigravity":
            from google.antigravity import Agent
            from google.antigravity.types import (
                BuiltinTools,
                CustomSystemInstructions,
                McpStreamableHttpServer,
            )

            native = harness.build(
                Tools(request, store),
                McpStreamableHttpServer(
                    name="incident",
                    url="http://127.0.0.1:1/mcp",
                    enabled_tools=[fn.__name__ for fn in Tools(request, store).functions()],
                ),
            )

            # Agent construction copies configuration; this must preserve tool closures.
            Agent(native)
            assert isinstance(native.system_instructions, CustomSystemInstructions)
            assert native.capabilities.enabled_tools == [BuiltinTools.FINISH]
            assert native.capabilities.enable_subagents is False
            assert native.retry_config.api_retry.max_retries == 0
            assert native.retry_config.model_output_retry.max_retries == 2
            assert native.tools == []
            assert len(native.mcp_servers) == 1
        if args.name == "adk":
            asyncio.run(native.close())
        package = {"adk": "google-adk", "antigravity": "google-antigravity"}.get(
            args.name, args.name
        )
        print(f"{package} {version(package)}: SDK construction passed; no model request")
    finally:
        store.close()


if __name__ == "__main__":
    main()
