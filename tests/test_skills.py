from pathlib import Path

import pytest

import cognition
from cognition.agentkit.skills import (
    all_skill_directories,
    load_skill,
    read_resource,
    split_frontmatter,
    validate_skill,
)
from cognition.domain import Industry, Request
from cognition.layers.cognitive.tools import Tools

PACKAGE = Path(cognition.__file__).parent


def test_every_skill_in_the_repo_is_valid():
    directories = all_skill_directories(PACKAGE)
    assert len(directories) >= 3
    problems = [issue for directory in directories for issue in validate_skill(directory)]
    assert problems == []


def write_skill(root: Path, name: str, front: str, body: str = "Procedure.") -> Path:
    directory = root / name
    directory.mkdir()
    (directory / "SKILL.md").write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8")
    return directory


def test_validator_rejects_spec_violations(tmp_path):
    folder = write_skill(tmp_path, "good-name", "name: other-name\ndescription: Something.")
    assert any("equal the folder name" in p for p in validate_skill(folder))
    folder = write_skill(tmp_path, "Bad_Name", "name: Bad_Name\ndescription: Something.")
    assert any("lowercase" in p for p in validate_skill(folder))
    folder = write_skill(tmp_path, "no-desc", "name: no-desc\ndescription:")
    assert any("description" in p for p in validate_skill(folder))
    folder = write_skill(tmp_path, "extra-key", "name: extra-key\ndescription: x\nfoo: bar")
    assert any("unknown frontmatter key" in p for p in validate_skill(folder))
    folder = write_skill(tmp_path, "long-body", "name: long-body\ndescription: x", "x\n" * 500)
    assert any("500 lines" in p for p in validate_skill(folder))
    folder = write_skill(tmp_path, "nested", "name: nested\ndescription: x")
    (folder / "references" / "deep").mkdir(parents=True)
    assert any("nested" in p for p in validate_skill(folder))
    with pytest.raises(ValueError):
        split_frontmatter("no frontmatter")


def test_metadata_block_and_resource_access(tmp_path):
    folder = write_skill(
        tmp_path, "with-files", "name: with-files\ndescription: x\nmetadata:\n  owner: team"
    )
    (folder / "references").mkdir()
    (folder / "references" / "guide.md").write_text("detail", encoding="utf-8")
    skill = load_skill(folder)
    assert skill.metadata == {"owner": "team"}
    assert read_resource(skill, "references/guide.md") == "detail"
    for bad in ("../SKILL.md", "references/../SKILL.md", "/etc/passwd", "SKILL.md", "a/b/c"):
        with pytest.raises(PermissionError):
            read_resource(skill, bad)
    with pytest.raises(FileNotFoundError):
        read_resource(skill, "references/missing.md")


@pytest.mark.parametrize("industry", list(Industry))
def test_incident_skill_tools_are_scoped(platform, industry):
    identifier = f"skills-{industry}"
    from cognition.domain import PlantSpec

    platform.onboard(PlantSpec(id=identifier, name=identifier, industry=industry))
    tools = Tools(
        Request(incident_id=identifier, snapshot=platform.store.plant(identifier)), platform.store
    )
    listed = {item["name"] for item in tools.list_skills()}
    assert listed == {
        f"{industry}-operations",
        "core-coordination",
        "evidence-assessment",
        "proposal-and-escalation",
    }
    assert tools.read_skill(f"{industry}-operations")["content"]
    for other in Industry:
        if other != industry:
            with pytest.raises(PermissionError):
                tools.read_skill(f"{other}-operations")
    with pytest.raises(PermissionError):
        tools.read_skill_resource(f"{industry}-operations", "../SKILL.md")
