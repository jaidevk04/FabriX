"""Learning core tools: one operation per file, registered by import."""

from cognition.agentkit.tools import tools_for
from cognition.cores.learning.tools.learning_apply_monitor_config import (
    learning_apply_monitor_config,
)
from cognition.cores.learning.tools.learning_compare_baseline import learning_compare_baseline
from cognition.cores.learning.tools.learning_estimate_remaining_life import (
    learning_estimate_remaining_life,
)
from cognition.cores.learning.tools.learning_list_channels import learning_list_channels
from cognition.cores.learning.tools.learning_read_encoder_scores import (
    learning_read_encoder_scores,
)
from cognition.cores.learning.tools.learning_read_features import learning_read_features
from cognition.cores.learning.tools.learning_request_evidence import learning_request_evidence

READ = [spec.function for spec in tools_for("learning", "read")]
ACTION = [spec.function for spec in tools_for("learning", "action")]
__all__ = [
    "ACTION",
    "READ",
    "learning_apply_monitor_config",
    "learning_compare_baseline",
    "learning_estimate_remaining_life",
    "learning_list_channels",
    "learning_read_encoder_scores",
    "learning_read_features",
    "learning_request_evidence",
]
