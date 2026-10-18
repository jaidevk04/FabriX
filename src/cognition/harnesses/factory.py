"""Trusted installed plugins and lazy built-in harness selection."""

from importlib.metadata import entry_points
from importlib.util import find_spec

from cognition.config import worker_interpreter
from cognition.harnesses.base import Harness, ModelSettings


def create(name: str, settings: ModelSettings | None = None, *, isolated: bool = True) -> Harness:
    settings = settings or ModelSettings.from_env()
    interpreter = worker_interpreter(name) if isolated else None
    if interpreter:
        from cognition.harnesses.process import ProcessHarness

        if name != "reference":
            settings.validate()
        return ProcessHarness(name, interpreter, settings)
    if name == "reference":
        from cognition.harnesses.reference import ReferenceHarness

        return ReferenceHarness()
    if name == "deepagents":
        if find_spec("deepagents") is None:
            raise ValueError("Deep Agents is not installed. Run: pip install -e '.[deepagents]'")
        from cognition.harnesses.deepagents import DeepAgentsHarness

        return DeepAgentsHarness(settings)
    if name == "adk":
        from cognition.harnesses.adk import ADKHarness

        return ADKHarness(settings)
    if name == "antigravity":
        from cognition.harnesses.antigravity import AntigravityHarness

        return AntigravityHarness(settings)
    for plugin in entry_points(group="cognition.harnesses"):
        if plugin.name == name:
            return plugin.load()(settings)
    raise ValueError(f"Unknown harness: {name}")
