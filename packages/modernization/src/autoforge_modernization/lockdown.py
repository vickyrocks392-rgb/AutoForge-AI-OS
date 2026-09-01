"""
Lockdown Mode and Client/External Research Data-Plane Separation.

Defines:
1. LockdownMode: the operating mode that disables all external network access
2. DataPlane: strict separation between CLIENT DATA PLANE and EXTERNAL RESEARCH PLANE
3. Enforced boundaries that prevent client data from leaking to external services

CLIENT DATA PLANE contains:
- Client source code, requirements, business rules
- Private documentation, private RAG, project artifacts
- Execution state

EXTERNAL RESEARCH PLANE may contain:
- Public technology research
- Public migration documentation
- Public market benchmarks, competitor information, vendor pricing

Reuses:
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


# ── Data Plane ────────────────────────────────────────────────────────────────


class DataPlane(str, Enum):
    """
    The data plane a piece of data belongs to.

    Strict boundary: CLIENT data must NEVER flow to EXTERNAL plane.
    """

    CLIENT = "client"
    """Private client data. Must never leave local environment."""

    EXTERNAL = "external"
    """Public/external research data. Sanitized, no client data."""

    SHARED = "shared"
    """Data that can cross planes (e.g., anonymized metrics)."""


class DataPlaneBoundary(BaseModel):
    """
    The data-plane boundary configuration.

    Defines which data types belong to which plane, and the enforcement
    points that prevent client data from flowing to the external plane.
    """

    boundary_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    enabled: bool = True

    # What belongs to each plane
    client_plane_fields: list[str] = Field(default_factory=list)
    external_plane_fields: list[str] = Field(default_factory=list)
    shared_plane_fields: list[str] = Field(default_factory=list)

    # Enforcement points
    enforcement_points: list[str] = Field(default_factory=list)
    """Where boundary enforcement is applied."""

    # Blocked data types (never can flow to external)
    client_blocked_fields: list[str] = Field(default_factory=list)

    last_updated: datetime = Field(default_factory=_utc_now)

    def is_client_data(self, field_name: str) -> bool:
        """Return True if a field is classified as client data."""
        return field_name in self.client_plane_fields

    def can_flow_to_external(self, field_name: str) -> bool:
        """Return True if a field can legally flow to external plane."""
        if field_name in self.client_blocked_fields:
            return False
        return field_name in self.shared_plane_fields or field_name in self.external_plane_fields
