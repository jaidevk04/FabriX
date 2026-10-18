"""CoreContext: what one core run may touch. Tools receive it; the model never sees it."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from cognition.domain import ActionOrder, CoreName, Proposal, State


@dataclass
class CoreContext:
    platform: Any
    plant_id: str
    core: CoreName
    correlation_id: str = "analysis"
    order: ActionOrder | None = None
    proposal: Proposal | None = None
    bound: Callable[[], Awaitable[Any]] | None = None
    called: bool = False
    outcome: Any = None
    error: Exception | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def state(self) -> State:
        return self.platform.store.plant(self.plant_id)

    def audit_tool(self, tool: str) -> None:
        self.platform.store.audit(
            f"cores:{self.plant_id}",
            "core_tool_called",
            {"core": self.core, "tool": tool, "correlation_id": self.correlation_id},
        )
