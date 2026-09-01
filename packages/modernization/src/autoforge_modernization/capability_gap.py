"""
Capability Gap and Installation Workflow.

Models the lifecycle when AutoForge encounters a technology it cannot
process. The system must:

1. Detect the missing capability (capability gap)
2. Identify the required tool/package/environment
3. Provide installation instructions
4. Verify installation (the tool is NOT installed until verified)
5. Update the capability registry

This is the G.1 contract; the actual installation executor belongs to G.2+.

Reuses:
- capability_registry: TechnologyCapability, TechnologyCapabilityRegistry
- tooling: SpecialistTool, SpecialistToolingInventory
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Gap State ──────────────────────────────────────────────────────────────


class GapState(str, Enum):
    """Lifecycle state of a capability gap."""

    DETECTED = "detected"
    """Gap has been identified and recorded."""

    INSTRUCTIONS_PROVIDED = "instructions_provided"
    """Installation instructions are available."""

    INSTALLATION_IN_PROGRESS = "installation_in_progress"
    """Installation is being attempted."""

    INSTALLED = "installed"
    """Tool was installed but not yet verified."""

    VERIFIED = "verified"
    """Tool installation was verified; capability gap resolved."""

    FAILED = "failed"
    """Installation or verification failed."""

    BLOCKED = "blocked"
    """Cannot install (license, environment, etc.)."""


class GapSeverity(str, Enum):
    """Severity of a capability gap."""

    CRITICAL = "critical"  # Blocks modernization entirely
    HIGH = "high"  # Reduces quality of modernization
    MEDIUM = "medium"  # Specific feature unavailable
    LOW = "low"  # Minor limitation


# ── Capability Gap Record ──────────────────────────────────────────────────


class CapabilityGap(BaseModel):
    """
    A record of a single capability gap.

    Models the entire lifecycle from detection to resolution. The gap
    is NOT considered resolved until the tool installation has been
    verified and the capability state is updated.
    """

    gap_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    technology: str
    technology_version: str | None = None

    # What's missing
    current_capability_state: str  # Snapshot of state when detected
    required_capability_state: str  # What's needed to proceed
    missing_capability: str  # Human-readable description

    # What would resolve the gap
    required_tool_name: str | None = None
    required_package_name: str | None = None
    required_environment: str | None = None
    installation_instructions: str = ""
    installation_command: str | None = None

    # State machine
    state: GapState = GapState.DETECTED
    severity: GapSeverity = GapSeverity.HIGH

    # Lifecycle
    detected_at: datetime = Field(default_factory=_utc_now)
    resolved_at: datetime | None = None
    resolution_notes: str = ""

    # Blockers
    blocked_reason: str | None = None  # license, environment, etc.

    # Verification
    verification_command: str | None = None
    last_verification_error: str | None = None

    # Provenance
    detected_by: str = "autoforge-core"  # analyzer_id, worker_id, etc.
    affected_components: list[str] = Field(default_factory=list)
    affected_artifact_ids: list[str] = Field(default_factory=list)

    def is_resolved(self) -> bool:
        """Return True if the gap has been verified as resolved."""
        return self.state == GapState.VERIFIED

    def blocks_modernization(self) -> bool:
        """Return True if this gap blocks transformation."""
        return self.severity in (GapSeverity.CRITICAL, GapSeverity.HIGH) and not self.is_resolved()


# ── Capability Gap Workflow ────────────────────────────────────────────────


class CapabilityGapReport(BaseModel):
    """
    Aggregate report of all capability gaps in a project.

    This is the surface for the planning gate to inspect and decide
    whether the project can proceed.
    """

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    generated_at: datetime = Field(default_factory=_utc_now)

    gaps: list[CapabilityGap] = Field(default_factory=list)

    @property
    def has_critical_gaps(self) -> bool:
        return any(g.blocks_modernization() for g in self.gaps)

    @property
    def unresolved_gaps(self) -> list[CapabilityGap]:
        return [g for g in self.gaps if not g.is_resolved()]

    @property
    def critical_unresolved(self) -> list[CapabilityGap]:
        return [
            g for g in self.gaps
            if g.severity == GapSeverity.CRITICAL and not g.is_resolved()
        ]

    def add_gap(self, gap: CapabilityGap) -> None:
        """Add a gap to the report."""
        self.gaps.append(gap)

    def by_technology(self, technology: str) -> list[CapabilityGap]:
        """Get all gaps for a specific technology."""
        return [g for g in self.gaps if g.technology == technology]

    def can_proceed(self) -> bool:
        """Return True if the project can proceed to modernization."""
        return not self.has_critical_gaps
