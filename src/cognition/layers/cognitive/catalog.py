"""Plain function closures shared by native MCP and optional provider adapters."""

from typing import Any

from cognition.industries import TOOL_BINDINGS


def bind(tools, *, specialist: bool = False, cores: bool = False):
    def discover(query: str = "") -> list[dict]:
        """Discover approved capabilities for this incident."""
        return tools.discover(query)

    def read_snapshot() -> dict[str, Any]:
        """Read the immutable revisioned incident snapshot."""
        return tools.read_snapshot()

    def read_time() -> dict[str, Any]:
        """Read simulated process time, wall-clock time and forecast horizon."""
        return tools.read_time()

    def read_instruments() -> dict[str, Any]:
        """Read simulator-derived process instruments with units and bands."""
        return tools.read_instruments()

    def forecast_instruments(value: float) -> dict[str, Any]:
        """Forecast instrument values over simulated time for a duty percent, on a twin copy."""
        return tools.forecast_instruments(value)

    def read_control() -> dict[str, Any]:
        """Read permitted control bounds, units and operating mode."""
        return tools.read_control()

    def read_sop() -> dict[str, Any]:
        """Read operating procedure and measurable recovery criteria."""
        return tools.read_sop()

    def simulate_action(value: float) -> dict[str, Any]:
        """Forecast duty percent on a twin copy without executing controls."""
        return tools.simulate_action(value)

    def read_layers() -> dict[str, Any]:
        """Read reflexive status, perceptual evidence and conflicts."""
        return tools.read_layers()

    def list_skills() -> list[dict[str, Any]]:
        """List the skills available to this incident."""
        return tools.list_skills()

    def read_skill(name: str) -> dict[str, Any]:
        """Load an available skill (industry operations or shared) on demand."""
        return tools.read_skill(name)

    def read_skill_resource(name: str, path: str) -> dict[str, Any]:
        """Read a file from a skill's references, assets or scripts folder."""
        return tools.read_skill_resource(name, path)

    functions = [
        discover,
        read_snapshot,
        read_time,
        read_instruments,
        forecast_instruments,
        read_control,
        read_sop,
        simulate_action,
        read_layers,
        list_skills,
        read_skill,
        read_skill_resource,
    ]
    functions.extend(TOOL_BINDINGS[tools.request.snapshot.spec.industry](tools))
    if cores:

        def read_core_live(
            core: str, scope: str = "", response_format: str = "concise"
        ) -> dict[str, Any]:
            """Read a core's current monitor state (learning, vision, robot, optimization)."""
            return tools.read_core_live(core, scope, response_format)

        async def ask_core(
            core: str, question: str, response_format: str = "concise"
        ) -> dict[str, Any]:
            """Ask a core to analyse one focused question; it never orders actions."""
            return await tools.ask_core(core, question, response_format)

        def read_core_reports() -> dict[str, Any]:
            """Read the core reports frozen when this incident started."""
            return tools.read_core_reports()

        def request_optimization(
            goal: str = "recovery", max_duty_change: float = 20.0
        ) -> dict[str, Any]:
            """Rank thermal-duty candidates on a twin copy for recovery, energy or scrap."""
            return tools.request_optimization(goal, max_duty_change)

        def read_business() -> dict[str, Any]:
            """Read simulated production, orders, inventory and spare availability."""
            return tools.read_business()

        def read_kpis() -> dict[str, Any]:
            """Read OEE, orders at risk and production totals."""
            return tools.read_kpis()

        def read_sustainability() -> dict[str, Any]:
            """Read energy, fuel, CO2e and cost rates and totals (placeholder factors)."""
            return tools.read_sustainability()

        functions.extend(
            [
                read_core_live,
                ask_core,
                read_core_reports,
                request_optimization,
                read_business,
                read_kpis,
                read_sustainability,
            ]
        )
    if specialist:

        async def delegate_specialist(specialist_id: str, objective: str) -> dict[str, Any]:
            """Request advisory evidence from an approved scoped A2A specialist."""
            return await tools.delegate_specialist(specialist_id, objective)

        functions.append(delegate_specialist)
    return functions


def sdk_functions(tools):
    names = {fn.__name__ for fn in tools.functions()}
    return bind(tools, specialist="delegate_specialist" in names, cores="read_core_live" in names)
