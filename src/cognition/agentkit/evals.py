"""ADK-format eval sets: load, and score tool trajectories offline without a model."""

import json
from pathlib import Path
from typing import Any, Literal

Match = Literal["exact", "in_order", "any_order"]


def load_evalset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "eval_set_id" not in data or not data.get("eval_cases"):
        raise ValueError(f"{path.name}: eval set needs eval_set_id and eval_cases")
    return data


def expected_tools(case: dict[str, Any]) -> list[str]:
    turns = case.get("conversation", [])
    uses = [use for turn in turns for use in turn.get("intermediate_data", {}).get("tool_uses", [])]
    return [use["name"] for use in uses]


def trajectory_ok(expected: list[str], actual: list[str], match: Match = "in_order") -> bool:
    if match == "exact":
        return expected == actual
    if match == "any_order":
        return sorted(expected) == sorted(actual) or set(expected) <= set(actual)
    remaining = iter(actual)
    return all(name in remaining for name in expected)


def scripted_model(
    steps: list[tuple[str, dict[str, Any]]], final: dict[str, Any], delay: float = 0
):
    """An ADK model that replays tool calls, then returns a structured answer. No network.

    Used to run real agents offline: it proves tool names, arguments and wiring, not reasoning.
    """
    import asyncio

    from google.adk.models import BaseLlm, LlmResponse
    from google.genai import types

    class Scripted(BaseLlm):
        model: str = "scripted-offline"
        script: list = []
        answer: dict = {}
        pause: float = 0
        cursor: int = 0
        seen: list = []

        async def generate_content_async(self, llm_request, stream=False):
            if self.pause:
                await asyncio.sleep(self.pause)
            if self.cursor < len(self.script):
                name, args = self.script[self.cursor]
                self.cursor += 1
            else:
                name, args = "set_model_response", self.answer
            self.seen.append(name)
            part = types.Part.from_function_call(name=name, args=args)
            yield LlmResponse(content=types.Content(role="model", parts=[part]))

    return Scripted(script=list(steps), answer=final, pause=delay, seen=[])
