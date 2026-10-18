"""Regenerate each core's README tool and skill tables from the code. Run after adding a tool."""

import importlib
from pathlib import Path

from cognition.agentkit.skills import list_skills
from cognition.agentkit.tools import tools_for

ROOT = Path(__file__).resolve().parents[1] / "src" / "cognition" / "cores"
CORES = ("learning", "vision", "robot", "optimization")
for core in CORES:
    importlib.import_module(f"cognition.cores.{core}.tools")


def table(core: str) -> str:
    lines = ["## Tools", "", "| Tool | Kind | What it does |", "|---|---|---|"]
    for spec in tools_for(core):
        summary = (spec.function.__doc__ or "").strip().splitlines()[0]
        lines.append(f"| `{spec.name}` | {spec.kind} | {summary} |")
    lines += ["", "## Skills", "", "| Skill | Use |", "|---|---|"]
    for skill in list_skills(ROOT / core / "skills"):
        lines.append(f"| `{skill.name}` | {skill.description.split('. ')[0]}. |")
    lines.append("| `core-report-writing`, `bus-requests` | shared by every core |")
    return "\n".join(lines) + "\n"


for core in CORES:
    path = ROOT / core / "README.md"
    text = path.read_text(encoding="utf-8")
    head = text[: text.index("## Tools")]
    tail = text[text.index("## Testing") :]
    path.write_text(head + table(core) + "\n" + tail, encoding="utf-8")
    print("updated", path.relative_to(ROOT.parent.parent.parent))
