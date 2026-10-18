"""The four cores and their monitors and reference analysers."""

from cognition.cores.base import CoreSpec
from cognition.cores.learning.monitor import monitor as learning_monitor
from cognition.cores.learning.reference import reference as learning_reference
from cognition.cores.optimization.monitor import monitor as optimization_monitor
from cognition.cores.optimization.reference import reference as optimization_reference
from cognition.cores.robot.monitor import monitor as robot_monitor
from cognition.cores.robot.reference import reference as robot_reference
from cognition.cores.vision.monitor import monitor as vision_monitor
from cognition.cores.vision.reference import reference as vision_reference

SPECS = {
    "learning": CoreSpec(
        "learning",
        "Fuses multi-rate sensor channels through a simulated sensor language model.",
        learning_monitor,
        learning_reference,
    ),
    "vision": CoreSpec(
        "vision",
        "Reads camera feeds with a simulated detector to find defects and deviations.",
        vision_monitor,
        vision_reference,
    ),
    "robot": CoreSpec(
        "robot",
        "Plans inspection, verification and maintenance work for the simulated fleet.",
        robot_monitor,
        robot_reference,
    ),
    "optimization": CoreSpec(
        "optimization",
        "Searches the twin for candidate actions and trade-offs when asked.",
        optimization_monitor,
        optimization_reference,
    ),
}
