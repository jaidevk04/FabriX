"""Vision core agent assembly: model, instruction, tools, skills, output schema."""

from pathlib import Path
from typing import Any

from cognition.agentkit.adk import build_core_agent
from cognition.cores.registry import SPECS
from cognition.cores.vision import tools
from cognition.cores.vision.schemas import ANALYSIS_OUTPUT, ORDER_OUTPUT


def build_agent(ctx: Any, model: Any, mode: str = "analysis") -> Any:
    """Analysis runs may read; order runs add the one bound action tool."""
    ordering = mode == "order"
    return build_core_agent(
        ctx,
        model,
        root=Path(__file__).parent,
        description=SPECS["vision"].description,
        tools=[*tools.READ, *tools.ACTION] if ordering else [*tools.READ],
        output_schema=ORDER_OUTPUT if ordering else ANALYSIS_OUTPUT,
        mode=mode,
    )
