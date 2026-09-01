"""
Research and Market Intelligence Plane.

Defines the boundary for the separate research/market-intelligence capability.

This capability operates on sanitized public research questions:
- Public technology research
- Public migration documentation
- Public market benchmarks
- Public competitor information
- Public vendor pricing

It must NOT have implicit access to:
- Client source code
- Private requirements
- Private business rules
- Private RAG
- Client artifacts

G.1 establishes the contracts. G.4/G.5 will implement the actual
research capability.

Reuses:
- lockdown: DataPlane, DataPlaneBoundary
- jobs: OperatingMode, LockdownState
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Research Types ─────────────────────────────────────────────────────────────


class ResearchType(str, Enum):
    """Category of research being performed."""

    TECHNOLOGY_EVALUATION = "technology_evaluation"
    """Evaluating target technologies for modernization."""

    MIGRATION_DOCUMENTATION = "migration_documentation"
    """Public migration guides, best practices."""

    MARKET_BENCHMARK = "market_benchmark"
    """Public pricing, industry benchmarks."""

    COMPETITOR_RESEARCH = "competitor_research"
    """Competitor tooling and service research."""

    VENDOR_RESEARCH = "vendor_research"
    """Vendor pricing and capability research."""

    INDUSTRY_INFORMATION = "industry_information"
    """General industry trends and information."""


class ResearchStatus(str, Enum):
    """Status of a research task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED_BY_LOCKDOWN = "blocked_by_lockdown"
    FAILED = "failed"


# ── Research Query ─────────────────────────────────────────────────────────────


class ResearchQuery(BaseModel):
    """
    A single research query.

    Each query is explicit about:
    - What it is asking (public information only)
    - Whether it can proceed (depends on lockdown state)
    - What data it would access (external plane only)
    """

    query_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str | None = None  # For tracking; query itself must be sanitized

    research_type: ResearchType
    question: str
    """The research question. Must NOT contain client data."""

    # Sanitized context (no client source, no client requirements)
    sanitized_context: dict[str, Any] = Field(default_factory=dict)
    """
    Context for the query. Must be sanitized of client data.
    Allowed: technology name, language, framework, strategy type.
    Forbidden: source code, business rules, client identifiers.
    """

    status: ResearchStatus = ResearchStatus.PENDING
    result_artifact_id: str | None = None
    error: str | None = None

    created_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None

    def is_sanitized(self) -> bool:
        """
        Verify the query appears to be sanitized.

        Checks that the question does not contain common client data indicators.
        This is advisory — actual enforcement happens at the data plane boundary.
        """
        # Check for common client data patterns (advisory only)
        client_indicators = [
            "source code",
            "our system",
            "our application",
            "our codebase",
            "the client's",
        ]
        lower_q = self.question.lower()
        return not any(ind in lower_q for ind in client_indicators)


# ── Research Plane Config ──────────────────────────────────────────────────────


class ResearchPlaneConfig(BaseModel):
    """
    Configuration for the research/market-intelligence plane.

    Defines what the research capability can and cannot access.
    """

    plane_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # What research types are enabled
    enabled_types: list[ResearchType] = Field(default_factory=list)
    """Which research types are allowed."""

    # What the research plane can NOT access
    forbidden_data_types: list[str] = Field(default_factory=list)
    """
    Client data types that can never be used in research queries.
    Examples: "source_code", "business_rules", "private_requirements".
    """

    # Research scope
    requires_sanitization: bool = True
    """Whether queries must be sanitized before research."""

    last_updated: datetime = Field(default_factory=_utc_now)

    def can_research(self, research_type: ResearchType) -> bool:
        """Return True if this research type is enabled."""
        return research_type in self.enabled_types
