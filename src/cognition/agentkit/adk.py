"""Thin Google ADK helpers for core agents. ADK is imported lazily, only when an agent runs."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cognition.agentkit.tools import bind_tool

SHARED_SKILLS = Path(__file__).resolve().parent.parent / "cores" / "_shared" / "skills"


def build_core_agent(
    ctx: Any,
    model: Any,
    *,
    root: Path,
    description: str,
    tools: list[Callable[..., Any]],
    output_schema: type[BaseModel],
    mode: str,
) -> Any:
    """Assemble an LlmAgent: instruction, bound tools, skills and a structured output."""
    from google.adk.agents import LlmAgent
    from google.adk.skills import load_skill_from_dir
    from google.adk.tools.skill_toolset import SkillToolset

    skills = [
        load_skill_from_dir(path.parent)
        for base in (root / "skills", SHARED_SKILLS)
        for path in sorted(base.glob("*/SKILL.md"))
    ]
    instruction = (root / "instruction.md").read_text(encoding="utf-8")
    instruction += f"\n\nRun type: {mode}. Plant: {ctx.plant_id}."
    bound = [bind_tool(ctx, fn, ctx.audit_tool) for fn in tools]
    return LlmAgent(
        name=f"{ctx.core}_core",
        model=model,
        description=description,
        instruction=instruction,
        tools=[*bound, SkillToolset(skills=skills)],
        output_schema=output_schema,
    )


def _clip(value: Any, limit: int = 600) -> Any:
    """Make a tool argument or result safe to log: JSON types only, bounded in size."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= limit:
        return json.loads(text) if text[:1] in "{[" else text.strip('"')
    return text[: limit - 1] + "…"


def narrate(event: Any, emit: Callable[[str, dict], None]) -> None:
    """Turn one ADK event into log entries: model text, thoughts, tool calls and tool results."""
    for part in (getattr(event.content, "parts", None) or []) if event.content else []:
        call = getattr(part, "function_call", None)
        response = getattr(part, "function_response", None)
        if call is not None:
            emit("tool_call", {"name": call.name, "args": _clip(dict(call.args or {}))})
        elif response is not None:
            emit("tool_result", {"name": response.name, "result": _clip(response.response)})
        elif getattr(part, "text", None):
            kind = "llm_thought" if getattr(part, "thought", False) else "llm_text"
            if event.is_final_response() and kind == "llm_text":
                kind = "final"
            emit(kind, {"text": part.text[:1200]})


async def run_structured(
    agent: Any,
    prompt: str,
    schema: type[BaseModel],
    session: str,
    emit: Callable[[str, dict], None] | None = None,
) -> Any:
    """Run an agent once and parse its structured answer. There is no retry.

    `emit(kind, body)` receives each step as it happens so the UI can stream it. It never
    receives exception text.
    """
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=agent, app_name="avenor_cores")
    try:
        created = await runner.session_service.create_session(
            app_name="avenor_cores", user_id="platform", session_id=session
        )
        output = ""
        async for event in runner.run_async(
            user_id="platform",
            session_id=created.id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            if emit is not None:
                narrate(event, emit)
            if event.is_final_response() and event.content:
                output = "".join(part.text or "" for part in event.content.parts or [])
        return schema.model_validate_json(output)
    finally:
        await runner.close()
