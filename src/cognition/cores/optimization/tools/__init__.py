"""Optimization core tools: one operation per file, registered by import."""

from cognition.agentkit.tools import tools_for
from cognition.cores.optimization.tools.optimization_evaluate_candidate import (
    optimization_evaluate_candidate,
)
from cognition.cores.optimization.tools.optimization_execute_order import (
    optimization_execute_order,
)
from cognition.cores.optimization.tools.optimization_read_followup_status import (
    optimization_read_followup_status,
)
from cognition.cores.optimization.tools.optimization_read_problem_context import (
    optimization_read_problem_context,
)
from cognition.cores.optimization.tools.optimization_request_evidence import (
    optimization_request_evidence,
)
from cognition.cores.optimization.tools.optimization_search_duty import optimization_search_duty
from cognition.cores.optimization.tools.optimization_solve_assignment import (
    optimization_solve_assignment,
)

READ = [spec.function for spec in tools_for("optimization", "read")]
ACTION = [spec.function for spec in tools_for("optimization", "action")]
__all__ = [
    "ACTION",
    "READ",
    "optimization_evaluate_candidate",
    "optimization_execute_order",
    "optimization_read_followup_status",
    "optimization_read_problem_context",
    "optimization_request_evidence",
    "optimization_search_duty",
    "optimization_solve_assignment",
]
