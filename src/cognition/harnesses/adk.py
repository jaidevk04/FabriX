"""ADK runner adapter; session state does not cross the platform boundary."""

from cognition.domain import Capabilities, Proposal, Request
from cognition.harnesses.base import INSTRUCTIONS, ModelSettings, prompt
from cognition.layers.cognitive.tools import Tools


class ADKHarness:
    def __init__(self, settings: ModelSettings) -> None:
        settings.validate()
        self.settings = settings

    def capabilities(self) -> Capabilities:
        return Capabilities(name="adk", live_model=True)

    def build(self, tools: Tools, functions=None):
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner

        agent = LlmAgent(
            name="process_investigator",
            model=self.settings.model,
            instruction=INSTRUCTIONS,
            tools=functions if functions is not None else [*tools.functions()],
            output_schema=Proposal,
        )
        return InMemoryRunner(agent=agent, app_name="industrial_cognition")

    async def propose(self, request: Request, tools: Tools) -> Proposal:
        from cognition.mcp.adapters import tool_functions

        async with tool_functions(tools) as functions:
            return await self._run(request, tools, functions)

    async def _run(self, request: Request, tools: Tools, functions) -> Proposal:
        from google.genai import types

        runner = self.build(tools, functions)
        try:
            session = await runner.session_service.create_session(
                app_name="industrial_cognition", user_id="platform", session_id=request.incident_id
            )
            output = ""
            async for event in runner.run_async(
                user_id="platform",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=prompt(request))]),
            ):
                if event.is_final_response() and event.content:
                    output = "".join(part.text or "" for part in event.content.parts or [])
            return Proposal.model_validate_json(output)
        finally:
            await runner.close()
