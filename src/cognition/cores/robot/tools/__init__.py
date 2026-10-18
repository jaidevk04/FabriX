"""Robot core tools: one operation per file, registered by import."""

from cognition.agentkit.tools import tools_for
from cognition.cores.robot.tools.robot_check_mission import robot_check_mission
from cognition.cores.robot.tools.robot_execute_order import robot_execute_order
from cognition.cores.robot.tools.robot_read_fleet import robot_read_fleet
from cognition.cores.robot.tools.robot_read_mission_result import robot_read_mission_result
from cognition.cores.robot.tools.robot_read_zones import robot_read_zones
from cognition.cores.robot.tools.robot_request_evidence import robot_request_evidence
from cognition.cores.robot.tools.robot_run_mission import robot_run_mission

READ = [spec.function for spec in tools_for("robot", "read")]
FLEET = [spec.function for spec in tools_for("robot", "fleet")]
ACTION = [spec.function for spec in tools_for("robot", "action")]
__all__ = [
    "ACTION",
    "FLEET",
    "READ",
    "robot_check_mission",
    "robot_execute_order",
    "robot_read_fleet",
    "robot_read_mission_result",
    "robot_read_zones",
    "robot_request_evidence",
    "robot_run_mission",
]
