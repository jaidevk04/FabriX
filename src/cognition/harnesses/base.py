"""Minimal adapter contract v1. Switching occurs between incidents."""

import os
from dataclasses import dataclass
from typing import Protocol

from cognition.domain import Capabilities, Proposal, Request
from cognition.layers.cognitive.prompt import SYSTEM_PROMPT as INSTRUCTIONS
from cognition.layers.cognitive.prompt import prompt
from cognition.layers.cognitive.tools import Tools


class Harness(Protocol):
    def capabilities(self) -> Capabilities: ...
    async def propose(self, request: Request, tools: Tools) -> Proposal: ...


@dataclass(frozen=True)
class ModelSettings:
    model: str = ""
    vertex: bool = False
    project: str = ""
    location: str = "us-central1"

    @classmethod
    def from_env(cls) -> "ModelSettings":
        return cls(
            model=os.getenv("GEMINI_MODEL", ""),
            vertex=os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true",
            project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )

    def validate(self) -> None:
        if not self.model:
            raise ValueError("GEMINI_MODEL is required for live harnesses")
        if self.vertex:
            if not self.project:
                raise ValueError("GOOGLE_CLOUD_PROJECT is required with enterprise endpoints")
        elif not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
            raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY is required")


# Re-exported for adapter compatibility; policy lives in the cognitive layer.
__all__ = ["Harness", "ModelSettings", "INSTRUCTIONS", "prompt"]
