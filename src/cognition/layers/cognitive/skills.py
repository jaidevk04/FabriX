"""Skills visible to a main-harness incident: its industry skill plus shared harness skills."""

from importlib.resources import files
from pathlib import Path

from cognition.agentkit.skills import RESOURCE_DIRS, Skill, list_skills, read_resource
from cognition.domain import Industry

HARNESS_SKILLS = Path(__file__).parent / "skills"


def industry_skills(industry: Industry) -> Path:
    return Path(str(files(f"cognition.industries.{industry}"))) / "skills"


def available(industry: Industry) -> dict[str, Skill]:
    """Skills the incident may read; an industry never sees another industry's skill."""
    found = {skill.name: skill for skill in list_skills(industry_skills(industry))}
    found.update({skill.name: skill for skill in list_skills(HARNESS_SKILLS)})
    return found


def summaries(industry: Industry) -> list[dict]:
    result = []
    for skill in available(industry).values():
        resources = sorted(
            f"{folder}/{item.name}"
            for folder in RESOURCE_DIRS
            if (skill.directory / folder).is_dir()
            for item in (skill.directory / folder).iterdir()
        )
        result.append(
            {"name": skill.name, "description": skill.description, "resources": resources}
        )
    return result


def read(industry: Industry, name: str) -> str:
    skill = available(industry).get(name)
    if skill is None:
        raise PermissionError("Skill is outside the incident scope")
    return skill.body


def read_file(industry: Industry, name: str, path: str) -> str:
    skill = available(industry).get(name)
    if skill is None:
        raise PermissionError("Skill is outside the incident scope")
    return read_resource(skill, path)
