"""Deep Agents with Gemini and an in-memory virtual filesystem."""

import os
from typing import Any

from cognition.domain import Capabilities, Proposal, Request
from cognition.harnesses.base import INSTRUCTIONS, ModelSettings, prompt
from cognition.layers.cognitive.tools import Tools


class DeepAgentsHarness:
    def __init__(self, settings: ModelSettings) -> None:
        settings.validate()
        self.settings = settings

    def capabilities(self) -> Capabilities:
        return Capabilities(name="deepagents", live_model=True)

    def build(self, tools: Tools, functions=None):
        from deepagents import create_deep_agent
        from deepagents.backends import StateBackend
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs: dict[str, Any] = {"model": self.settings.model}
        if self.settings.vertex:
            kwargs.update(
                vertexai=True, project=self.settings.project, location=self.settings.location
            )
        else:
            kwargs["api_key"] = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        return create_deep_agent(
            model=ChatGoogleGenerativeAI(**kwargs),
            tools=functions if functions is not None else tools.functions(),
            system_prompt=INSTRUCTIONS,
            backend=StateBackend(),
            response_format=Proposal,
        )

    async def propose(self, request: Request, tools: Tools) -> Proposal:
        from cognition.mcp.adapters import tool_functions

        async with tool_functions(tools) as functions:
            result = await self.build(tools, functions).ainvoke(
                {"messages": [{"role": "user", "content": prompt(request)}]},
                config={"recursion_limit": 80},
            )
        return Proposal.model_validate(result["structured_response"])
