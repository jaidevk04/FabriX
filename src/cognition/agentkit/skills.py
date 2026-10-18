"""Agent Skills loader and validator (agentskills.io specification), harness neutral."""

import re
from dataclasses import dataclass
from pathlib import Path

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
RESOURCE_DIRS = ("references", "assets", "scripts")
MAX_BODY_LINES = 500
MAX_RESOURCE_BYTES = 200_000


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    directory: Path
    metadata: dict[str, str]


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse the flat YAML subset used by skills: scalars plus one level of metadata."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with a frontmatter block")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("Frontmatter block is not closed") from None
    fields: dict[str, object] = {}
    current: dict[str, str] | None = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] in " \t":
            if current is None or ":" not in raw:
                raise ValueError(f"Unexpected indented line: {raw.strip()}")
            key, _, value = raw.strip().partition(":")
            current[key.strip()] = value.strip().strip("\"'")
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            raise ValueError(f"Invalid frontmatter line: {raw}")
        key, value = key.strip(), value.strip()
        if key == "metadata" and not value:
            current = {}
            fields[key] = current
        else:
            current = None
            fields[key] = value.strip("\"'")
    return fields, "\n".join(lines[end + 1 :]).lstrip("\n")


def check_name(name: str) -> bool:
    return 1 <= len(name) <= 64 and NAME_PATTERN.fullmatch(name) is not None


def validate_skill(directory: Path) -> list[str]:
    """Return every spec violation for one skill folder; empty means valid."""
    problems: list[str] = []
    path = directory / "SKILL.md"
    if not path.is_file():
        return [f"{directory.name}: SKILL.md is missing"]
    try:
        fields, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except ValueError as error:
        return [f"{directory.name}: {error}"]
    label = directory.name
    for key in sorted(set(fields) - ALLOWED_KEYS):
        problems.append(f"{label}: unknown frontmatter key '{key}'")
    name = fields.get("name")
    if not isinstance(name, str) or not check_name(name):
        problems.append(f"{label}: name must be 1 to 64 lowercase letters, digits and hyphens")
    elif name != directory.name:
        problems.append(f"{label}: name '{name}' must equal the folder name")
    description = fields.get("description")
    if not isinstance(description, str) or not 1 <= len(description) <= 1024:
        problems.append(f"{label}: description must be 1 to 1024 characters")
    compatibility = fields.get("compatibility")
    if isinstance(compatibility, str) and len(compatibility) > 500:
        problems.append(f"{label}: compatibility is longer than 500 characters")
    if len(body.splitlines()) >= MAX_BODY_LINES:
        problems.append(f"{label}: body must stay under {MAX_BODY_LINES} lines")
    if not body.strip():
        problems.append(f"{label}: body is empty")
    for child in sorted(directory.iterdir()):
        if child.name == "SKILL.md":
            continue
        if child.name not in RESOURCE_DIRS or not child.is_dir():
            problems.append(f"{label}: unexpected entry '{child.name}'")
            continue
        if any(item.is_dir() for item in child.iterdir()):
            problems.append(f"{label}: {child.name}/ must not contain nested folders")
    return problems


def load_skill(directory: Path) -> Skill:
    problems = validate_skill(directory)
    if problems:
        raise ValueError("; ".join(problems))
    fields, body = split_frontmatter((directory / "SKILL.md").read_text(encoding="utf-8"))
    metadata = fields.get("metadata")
    return Skill(
        name=str(fields["name"]),
        description=str(fields["description"]),
        body=body,
        directory=directory,
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def skill_directories(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").exists())


def list_skills(root: Path) -> list[Skill]:
    return [load_skill(directory) for directory in skill_directories(root)]


def read_resource(skill: Skill, relative: str) -> str:
    """Read one file from references/, assets/ or scripts/; never anything else."""
    parts = Path(relative).parts
    if (
        len(parts) != 2
        or parts[0] not in RESOURCE_DIRS
        or ".." in parts
        or relative.startswith("/")
    ):
        raise PermissionError("Resource must be <references|assets|scripts>/<file>")
    target = skill.directory / parts[0] / parts[1]
    if not target.is_file() or target.is_symlink():
        raise FileNotFoundError(f"No resource {relative} in skill {skill.name}")
    if target.stat().st_size > MAX_RESOURCE_BYTES:
        raise ValueError("Resource is too large to read")
    return target.read_text(encoding="utf-8")


def all_skill_directories(package_root: Path) -> list[Path]:
    """Every skill folder under a package tree (``**/skills/<name>/SKILL.md``)."""
    return sorted(path.parent for path in package_root.glob("**/skills/*/SKILL.md"))
