"""Antigravity SDK adapter: supplied tools only, with a typed output schema."""

import os

from cognition.config import tool_cap
from cognition.domain import Capabilities, Proposal, Request
from cognition.harnesses.base import INSTRUCTIONS, ModelSettings, prompt
from cognition.harnesses.streaming import PublicTextStream
from cognition.layers.cognitive.catalog import sdk_functions
from cognition.layers.cognitive.tools import Tools

# Bounded in-conversation correction of malformed tool calls (Gemini MALFORMED_FUNCTION_CALL).
# Provider/API errors are never retried, and the incident itself is never re-run.
MODEL_OUTPUT_RETRIES = 2


class AntigravityHarness:
    def __init__(self, settings: ModelSettings) -> None:
        settings.validate()
        self.settings = settings

    def capabilities(self) -> Capabilities:
        return Capabilities(name="antigravity", live_model=True, streaming=True)

    def build(self, tools: Tools, mcp_server=None):
        from google.antigravity import CapabilitiesConfig, LocalAgentConfig
        from google.antigravity.hooks.policy import allow, deny
        from google.antigravity.types import (
            BudgetConfig,
            BuiltinTools,
            CustomSystemInstructions,
            GeminiAPIEndpoint,
            GeminiModelOptions,
            ModelAPIRetryConfig,
            ModelOutputRetryConfig,
            ModelTarget,
            RetryConfig,
            ThinkingLevel,
            VertexEndpoint,
        )

        functions = sdk_functions(tools)
        names = ", ".join(fn.__name__ for fn in functions)
        # Antigravity reaches MCP tools through its generic call_mcp_tool(ServerName, ToolName,
        # Arguments). Without the server name the model guesses it (e.g. the industry id).
        transport = (
            f"\nEvery tool below is served by the single MCP server named "
            f"'{mcp_server.name}'. Call each through call_mcp_tool with "
            f"ServerName='{mcp_server.name}' and ToolName set to one exact identifier. "
            "The industry id is not a server name. Never probe other server names."
            if mcp_server
            else ""
        )
        model = self.settings.model
        if model.startswith("gemini-3."):
            options = GeminiModelOptions(thinking_level=ThinkingLevel.LOW)
            endpoint = (
                VertexEndpoint(
                    project=self.settings.project, location=self.settings.location, options=options
                )
                if self.settings.vertex
                else GeminiAPIEndpoint(
                    api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
                    options=options,
                )
            )
            model = ModelTarget(name=self.settings.model, endpoint=endpoint)
        return LocalAgentConfig(
            model=model,
            system_instructions=CustomSystemInstructions(
                text=INSTRUCTIONS
                + "\nComplete with the finish tool and required Proposal."
                + transport
                + "\nAvailable tool identifiers: "
                + names
            ),
            tools=[] if mcp_server else functions,
            mcp_servers=[mcp_server] if mcp_server else [],
            response_schema=Proposal,
            capabilities=CapabilitiesConfig(
                enabled_tools=[BuiltinTools.FINISH], enable_subagents=False
            ),
            budget_config=BudgetConfig(max_model_calls=30, max_tool_calls=tool_cap()),
            retry_config=RetryConfig(
                api_retry=ModelAPIRetryConfig(max_retries=0),
                model_output_retry=ModelOutputRetryConfig(max_retries=MODEL_OUTPUT_RETRIES),
            ),
            policies=[deny("*"), allow("finish")]
            + (
                allow(mcp_server, mcp_tools=[fn.__name__ for fn in functions])
                if mcp_server
                else [allow(fn.__name__) for fn in functions]
            ),
            vertex=self.settings.vertex,
            project=self.settings.project or None,
            location=self.settings.location,
            api_key=None
            if self.settings.vertex
            else (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")),
        )

    async def propose(self, request: Request, tools: Tools) -> Proposal:
        from google.antigravity import Agent

        from cognition.mcp.incident import incident_mcp

        async with incident_mcp(tools) as server, Agent(self.build(tools, server)) as agent:
            response = await agent.chat(prompt(request))
            stream = PublicTextStream(tools.emit)
            try:
                async for text in response:
                    stream.push(text)
            finally:
                stream.push("", final=True)
            return Proposal.model_validate(await response.structured_output())
