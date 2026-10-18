import json

import pytest

from cognition.agentkit import tools as kit
from cognition.agentkit.evals import expected_tools, load_evalset, trajectory_ok


def test_every_registered_tool_passes_lint():
    problems = [
        issue for spec in kit.REGISTRY.values() for issue in kit.lint_tool(spec.function, spec.core)
    ]
    assert problems == []


def test_decorator_enforces_prefix_and_lint_checks_docstring():
    with pytest.raises(ValueError, match="prefixed"):

        @kit.tool("demo")
        def wrong_name() -> dict:
            """x"""
            return {}

    def demo_bad(value) -> dict:
        """Does something."""
        return {}

    problems = kit.lint_tool(demo_bad, "demo")
    assert any("Use when" in p for p in problems)
    assert any("no type annotation" in p for p in problems)

    def demo_good(window: int) -> dict:
        """Read a window.

        Use when you need recent data. Do not use for history.
        Args: window: number of samples.
        Returns: a dict of features.
        """
        return {}

    assert kit.lint_tool(demo_good, "demo") == []


def test_truncate_choose_format_and_error():
    cut = kit.truncate(list(range(10)), 3, "Pass a smaller scope.")
    assert cut["items"] == [0, 1, 2] and cut["truncated"] and "hint" in cut
    assert not kit.truncate([1], 3, "x")["truncated"]
    assert kit.choose_format("a", "b", "detailed") == "b"
    assert kit.choose_format("a", "b") == "a"
    assert kit.choose_format("a", "b", "huge")["status"] == "error"
    assert kit.tool_error("bad", "fix")["status"] == "error"


def test_trajectory_matching_and_evalset_loading(tmp_path):
    assert trajectory_ok(["a", "c"], ["a", "b", "c"])
    assert not trajectory_ok(["c", "a"], ["a", "b", "c"])
    assert trajectory_ok(["c", "a"], ["a", "b", "c"], "any_order")
    assert not trajectory_ok(["a"], ["a", "b"], "exact")
    path = tmp_path / "x.evalset.json"
    case = {"conversation": [{"intermediate_data": {"tool_uses": [{"name": "t1"}]}}]}
    path.write_text(json.dumps({"eval_set_id": "x", "eval_cases": [case]}))
    assert expected_tools(load_evalset(path)["eval_cases"][0]) == ["t1"]
    path.write_text("{}")
    with pytest.raises(ValueError):
        load_evalset(path)
