"""Vision core tools: one operation per file, registered by import."""

from cognition.agentkit.tools import tools_for
from cognition.cores.vision.tools.vision_apply_monitor_config import vision_apply_monitor_config
from cognition.cores.vision.tools.vision_compare_reference import vision_compare_reference
from cognition.cores.vision.tools.vision_list_cameras import vision_list_cameras
from cognition.cores.vision.tools.vision_measure_defect import vision_measure_defect
from cognition.cores.vision.tools.vision_read_detections import vision_read_detections
from cognition.cores.vision.tools.vision_request_evidence import vision_request_evidence

READ = [spec.function for spec in tools_for("vision", "read")]
ACTION = [spec.function for spec in tools_for("vision", "action")]
__all__ = [
    "ACTION",
    "READ",
    "vision_apply_monitor_config",
    "vision_compare_reference",
    "vision_list_cameras",
    "vision_measure_defect",
    "vision_read_detections",
    "vision_request_evidence",
]
