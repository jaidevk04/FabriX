"""Incident-scoped steel MCP tool bindings."""

from typing import Any


def bind(tools):
    def read_furnace_process() -> dict[str, Any]:
        """Read steel process signals, provenance, layer status and constraints."""
        return tools.read_industry_process("steel", "read_furnace_process")

    def simulate_furnace_duty(value: float) -> dict[str, Any]:
        """Forecast steel thermal duty percent; never bypass interlocks or execute."""
        return tools.simulate_industry_action("steel", "simulate_furnace_duty", value)

    return [read_furnace_process, simulate_furnace_duty]
