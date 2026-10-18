"""Tool decorator, registry, response helpers and lint rules for agent tools."""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_type_hints

Kind = Literal["read", "fleet", "action"]  # fleet = T0/T1 missions via FleetGateway
DOC_MARKERS = ("Use when", "Do not", "Returns")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    core: str
    kind: Kind
    function: Callable[..., Any]

    @property
    def read_only(self) -> bool:
        return self.kind == "read"


REGISTRY: dict[str, ToolSpec] = {}


def tool(core: str, kind: Kind = "read") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a function as a core tool. Names must start with ``<core>_``."""

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        if not function.__name__.startswith(f"{core}_"):
            raise ValueError(f"Tool {function.__name__} must be prefixed with '{core}_'")
        if function.__name__ in REGISTRY:
            raise ValueError(f"Duplicate tool name {function.__name__}")
        spec = ToolSpec(function.__name__, core, kind, function)
        REGISTRY[spec.name] = spec
        function.__tool_spec__ = spec  # type: ignore[attr-defined]
        return function

    return decorate


def tools_for(core: str, kind: Kind | None = None) -> list[ToolSpec]:
    return [
        spec
        for spec in REGISTRY.values()
        if spec.core == core and (kind is None or spec.kind == kind)
    ]


def tool_error(error: str, hint: str) -> dict[str, str]:
    """Fixable input mistakes are returned to the agent, not raised."""
    return {"status": "error", "error": error, "hint": hint}


def truncate(items: list[Any], limit: int, hint: str) -> dict[str, Any]:
    """Cut a long list and say how to narrow the request; response hygiene, not a budget."""
    shown = items[: max(limit, 0)]
    result: dict[str, Any] = {
        "items": shown,
        "total": len(items),
        "truncated": len(shown) < len(items),
    }
    if result["truncated"]:
        result["hint"] = hint
    return result


def choose_format(concise: Any, detailed: Any, response_format: str = "concise") -> Any:
    if response_format not in ("concise", "detailed"):
        return tool_error(
            f"Unknown response_format '{response_format}'", "Use 'concise' or 'detailed'."
        )
    return concise if response_format == "concise" else detailed


def kind_of(function: Callable[..., Any]) -> str:
    spec = getattr(function, "__tool_spec__", None)
    return spec.kind if spec is not None else "read"


def bind_tool(ctx: Any, function: Callable[..., Any], before: Callable[[str], None] | None = None):
    """Hide the context argument from the model and audit each call. Keeps sync or async."""
    signature = inspect.signature(function)
    shown = signature.replace(parameters=list(signature.parameters.values())[1:])
    annotations = {k: v for k, v in function.__annotations__.items() if k != "ctx"}

    if inspect.iscoroutinefunction(function):

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if before:
                before(function.__name__)
            return await function(ctx, *args, **kwargs)

    else:

        def wrapper(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
            if before:
                before(function.__name__)
            return function(ctx, *args, **kwargs)

    wrapper.__name__ = function.__name__
    wrapper.__doc__ = function.__doc__
    wrapper.__annotations__ = annotations
    wrapper.__signature__ = shown  # type: ignore[attr-defined]
    return wrapper


def lint_tool(function: Callable[..., Any], core: str) -> list[str]:
    """Return lint problems: name prefix, docstring shape and typed arguments."""
    name = function.__name__
    problems: list[str] = []
    if not name.startswith(f"{core}_"):
        problems.append(f"{name}: name must start with '{core}_'")
    doc = inspect.getdoc(function) or ""
    for marker in DOC_MARKERS:
        if marker not in doc:
            problems.append(f"{name}: docstring is missing '{marker}'")
    signature = inspect.signature(function)
    if kind_of(function) == "action" and [p for p in signature.parameters if p != "ctx"]:
        problems.append(f"{name}: action tools take no arguments")
    try:
        hints = get_type_hints(function)
    except Exception:
        hints = {}
    for parameter in signature.parameters.values():
        if parameter.name == "ctx":
            continue
        if parameter.name not in hints:
            problems.append(f"{name}: argument '{parameter.name}' has no type annotation")
        elif parameter.name not in doc:
            problems.append(f"{name}: argument '{parameter.name}' is not described")
    if "return" not in hints:
        problems.append(f"{name}: missing return annotation")
    return problems
