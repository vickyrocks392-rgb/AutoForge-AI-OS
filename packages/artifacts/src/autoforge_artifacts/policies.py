"""Artifact policies — Phase 12.

Deterministic policy evaluation for publication and rollback governance.

Design rules
------------
- Policies are deterministic — no AI evaluates policy.
- HITL requirements are explicit and configurable.
- Compatible with Phase 9 ApprovalGate pattern (does not create second framework).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from autoforge_artifacts.models import CanonicalArtifactType


class PublicationPolicy(BaseModel):
    """Policy governing which artifact publications require HITL approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hitl_required_types: frozenset[CanonicalArtifactType] = Field(
        default_factory=lambda: frozenset({
            CanonicalArtifactType.DEPLOYMENT,
        }),
        description="Artifact types that always require HITL for publication.",
    )
    hitl_required_destinations: frozenset[str] = Field(
        default_factory=lambda: frozenset({
            "production",
            "release",
        }),
        description="Destinations that always require HITL for publication.",
    )
    auto_publish_allowed: bool = Field(
        default=False,
        description="If False, all publications require explicit action.",
    )

    def requires_hitl(
        self,
        artifact_type: CanonicalArtifactType,
        destination: str = "default",
    ) -> bool:
        """Deterministic check: does this publication require HITL?"""
        if artifact_type in self.hitl_required_types:
            return True
        if destination in self.hitl_required_destinations:
            return True
        return False


class RollbackPolicy(BaseModel):
    """Policy governing rollback authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hitl_required_for_published: bool = Field(
        default=True,
        description="Require HITL to rollback a published artifact.",
    )
    hitl_required_types: frozenset[CanonicalArtifactType] = Field(
        default_factory=lambda: frozenset({
            CanonicalArtifactType.DEPLOYMENT,
        }),
        description="Artifact types that require HITL for rollback.",
    )

    def requires_hitl(
        self,
        artifact_type: CanonicalArtifactType,
        is_published: bool = False,
    ) -> bool:
        """Deterministic check: does this rollback require HITL?"""
        if artifact_type in self.hitl_required_types:
            return True
        if is_published and self.hitl_required_for_published:
            return True
        return False


class ArtifactPolicy(BaseModel):
    """Top-level artifact governance policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    publication: PublicationPolicy = Field(default_factory=PublicationPolicy)
    rollback: RollbackPolicy = Field(default_factory=RollbackPolicy)
