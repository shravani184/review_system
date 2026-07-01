"""Pydantic schemas shared across the pipeline.

These models are the *contract* between layers:

* detectors (pylint / bandit / custom rules) -> :class:`RawFinding`
* normalizer                                  -> :class:`NormalizedFinding`
* llm + confidence                            -> :class:`Issue`
* api                                         -> :class:`ReviewResponse`

Keeping a single shared schema is what lets the LLM layer operate on a closed
set of verified findings rather than free-form text.
"""
from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, enum.Enum):
    """Normalized severity levels (ordered low -> high)."""

    INFO = "Info"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"

    @property
    def rank(self) -> int:
        order = [
            Severity.INFO,
            Severity.LOW,
            Severity.MEDIUM,
            Severity.HIGH,
            Severity.CRITICAL,
        ]
        return order.index(self)


class ToolSource(str, enum.Enum):
    """Which detector produced a finding."""

    PYLINT = "Pylint"
    BANDIT = "Bandit"
    CUSTOM = "CustomRule"


# --------------------------------------------------------------------------- #
# Detection-time models
# --------------------------------------------------------------------------- #
class RawFinding(BaseModel):
    """Loosely-structured finding straight from a single detector.

    The normalizer converts these into :class:`NormalizedFinding`. Kept
    permissive (``extra`` allowed) because each tool has its own native fields.
    """

    model_config = {"extra": "allow"}

    tool: ToolSource
    code: str | None = None          # native rule id, e.g. "B105" / "C0114"
    message: str
    line: int = 0
    column: int | None = None
    raw_severity: str | None = None  # native severity string, pre-normalization
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedFinding(BaseModel):
    """A finding mapped onto the system's common schema.

    This is the single shape the LLM layer reasons about.
    """

    tool: ToolSource
    type: str                        # human-readable issue category
    severity: Severity
    line: int
    column: int | None = None
    message: str
    code: str | None = None          # native rule id (provenance)
    filename: str | None = None

    # Static reliability of the detector for this finding, 0..1. Used by the
    # confidence engine. Populated by the normalizer from a reliability table.
    tool_reliability: float = 0.8


# --------------------------------------------------------------------------- #
# Output models
# --------------------------------------------------------------------------- #
class Issue(BaseModel):
    """Final, user-facing issue: a verified finding enriched by the LLM."""

    tool: ToolSource
    type: str
    severity: Severity
    line: int
    column: int | None = None
    filename: str | None = None
    code: str | None = None
    message: str                          # original detector message
    explanation: str                      # LLM/offline explanation
    suggestion: str                       # LLM/offline fix suggestion
    confidence: float = Field(ge=0.0, le=1.0)


class FileReview(BaseModel):
    """Review result for a single source file."""

    filename: str
    syntax_valid: bool
    issues: list[Issue] = Field(default_factory=list)
    issue_count: int = 0
    error: str | None = None              # set when the file was rejected


class ReviewResponse(BaseModel):
    """Top-level response returned by ``POST /review``."""

    status: str = "ok"
    files: list[FileReview] = Field(default_factory=list)
    total_issues: int = 0
    llm_mode: str = "offline"             # "openai" | "offline"


class HealthResponse(BaseModel):
    """Response returned by ``GET /health``."""

    status: str
    app: str
    version: str
    llm_mode: str
    analyzers: dict[str, bool]
