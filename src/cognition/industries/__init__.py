"""Explicit industry catalog. Add one package here to extend every harness."""

from importlib.resources import files

from cognition.domain import Industry
from cognition.industries import cement, chemical, steel
from cognition.industries.business_events import BUSINESS_EVENTS
from cognition.industries.cement.business import PARAMETERS as cement_business
from cognition.industries.cement.channels import CAMERAS as cement_cameras
from cognition.industries.cement.channels import CHANNELS as cement_channels
from cognition.industries.cement.channels import ZONES as cement_zones
from cognition.industries.cement.faults import FAULTS as cement_faults
from cognition.industries.cement.tools import bind as cement_tools
from cognition.industries.chemical.business import PARAMETERS as chemical_business
from cognition.industries.chemical.channels import CAMERAS as chemical_cameras
from cognition.industries.chemical.channels import CHANNELS as chemical_channels
from cognition.industries.chemical.channels import ZONES as chemical_zones
from cognition.industries.chemical.faults import FAULTS as chemical_faults
from cognition.industries.chemical.tools import bind as chemical_tools
from cognition.industries.steel.business import PARAMETERS as steel_business
from cognition.industries.steel.channels import CAMERAS as steel_cameras
from cognition.industries.steel.channels import CHANNELS as steel_channels
from cognition.industries.steel.channels import ZONES as steel_zones
from cognition.industries.steel.faults import FAULTS as steel_faults
from cognition.industries.steel.tools import bind as steel_tools

INDUSTRIES = {Industry.CEMENT: cement, Industry.STEEL: steel, Industry.CHEMICAL: chemical}
TOOL_BINDINGS = {
    Industry.CEMENT: cement_tools,
    Industry.STEEL: steel_tools,
    Industry.CHEMICAL: chemical_tools,
}
PACKS = {key: module.PROFILE.thermal for key, module in INDUSTRIES.items()}
DEFINITIONS = {key: module.DEFINITIONS for key, module in INDUSTRIES.items()}
FAULTS = {
    Industry.CEMENT: cement_faults,
    Industry.STEEL: steel_faults,
    Industry.CHEMICAL: chemical_faults,
}


def get_industry(industry: Industry):
    return INDUSTRIES[industry]


BUSINESS = {
    Industry.CEMENT: cement_business,
    Industry.STEEL: steel_business,
    Industry.CHEMICAL: chemical_business,
}


CHANNELS = {
    Industry.CEMENT: cement_channels,
    Industry.STEEL: steel_channels,
    Industry.CHEMICAL: chemical_channels,
}
CAMERAS = {
    Industry.CEMENT: cement_cameras,
    Industry.STEEL: steel_cameras,
    Industry.CHEMICAL: chemical_cameras,
}
ZONES = {
    Industry.CEMENT: cement_zones,
    Industry.STEEL: steel_zones,
    Industry.CHEMICAL: chemical_zones,
}


def catalogue(industry: Industry) -> dict:
    """Injectable world events for an industry: its plant faults plus shared business events."""
    return {**FAULTS[industry], **BUSINESS_EVENTS}


def read_skill(industry: Industry, name: str) -> str:
    profile = get_industry(industry).PROFILE
    if name != profile.skill:
        raise PermissionError("Skill is outside the incident industry")
    return (
        files(f"cognition.industries.{industry}")
        .joinpath(f"skills/{name}/SKILL.md")
        .read_text(encoding="utf-8")
    )
