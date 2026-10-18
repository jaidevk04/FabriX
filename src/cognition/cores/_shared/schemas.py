"""Structured outputs for core agents. Nothing here is a platform contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindingItem(Schema):
    statement: str = Field(min_length=1, max_length=400)
    equipment: str | None = Field(default=None, max_length=64)
    evidence: list[str] = Field(default_factory=list, max_length=6)


class CoreFinding(Schema):
    """What an analysis run returns. The platform turns it into a CoreReport."""

    summary: str = Field(min_length=1, max_length=1000)
    status: Literal["normal", "watch", "alert"]
    confidence: float = Field(ge=0, le=1)
    findings: list[FindingItem] = Field(default_factory=list, max_length=8)
    next_checks: list[str] = Field(default_factory=list, max_length=5)


class OrderResult(Schema):
    """What an order run returns. The receipt comes from the bound tool, not from this."""

    decision: Literal["executed", "refused"]
    reason: str = Field(default="", max_length=400)
