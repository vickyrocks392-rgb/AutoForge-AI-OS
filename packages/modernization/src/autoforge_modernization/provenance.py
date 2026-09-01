"""
Provenance and Governance References.

Establishes the references to 18-F provenance and governance infrastructure.
The foundation supports:

source
→ analysis
→ evidence
→ business/requirements comparison
→ recommendation
→ plan
→ approval
→ transformation
→ verification
→ artifact
→ governance.

This module defines the ModernizationProvenanceChain which binds together
the source data, analysis, evidence, recommendations, plan, and approvals
into a single audit-able chain.

It does NOT create duplicate governance/review/audit infrastructure.
It reuses 18-F's GovernanceReportService, 18-C's evidence models, and
the canonical artifact lineage.

Reuses:
- autoforge_artifacts: Artifact, ArtifactLineageEntry, PublicationRecord
- autoforge_workforce: LegacyEvidence, FactState, BusinessRule
- 18-F: GovernanceReportService (referenced by id)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProvenanceStage(str, Enum):
    """Stages in the modernization provenance chain."""

    SOURCE = "source"
    """The original client source code or requirement."""

    ANALYSIS = "analysis"
    """Analysis of the source (reconnaissance, archaeology)."""

    EVIDENCE = "evidence"
    """Extracted evidence from analysis."""

    BUSINESS_COMPARISON = "business_comparison"
    """Comparison of current behavior vs business intent."""

    RECOMMENDATION = "recommendation"
    """Generated fix recommendation."""

    PLAN = "plan"
    """Migration plan binding recommendations to units."""

    APPROVAL = "approval"
    """Governance/HITL approval of the plan."""

    TRANSFORMATION = "transformation"
    """Code transformation (artifact produced)."""

    VERIFICATION = "verification"
    """Verification of the transformation."""

    ARTIFACT = "artifact"
    """Final published artifact."""

    GOVERNANCE = "governance"
    """Governance report covering the full chain."""


class ProvenanceLink(BaseModel):
    """A single link in the provenance chain."""

    link_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    stage: ProvenanceStage

    # Inputs to this stage
    input_artifact_ids: list[str] = Field(default_factory=list)
    input_evidence_ids: list[str] = Field(default_factory=list)

    # Outputs of this stage
    output_artifact_ids: list[str] = Field(default_factory=list)
    output_evidence_ids: list[str] = Field(default_factory=list)

    # Actor and metadata
    actor: str = ""
    tool_id: str | None = None
    worker_id: str | None = None
    rule_id: str | None = None
    finding_id: str | None = None

    timestamp: datetime = Field(default_factory=_utc_now)
    notes: str = ""


class ModernizationProvenanceChain(BaseModel):
    """
    The complete provenance chain for a modernization project.

    Tracks every input, transformation, and output. Reuses 18-F governance
    rather than duplicating it.
    """

    chain_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str

    # The chain itself
    links: list[ProvenanceLink] = Field(default_factory=list)

    # The source
    source_artifact_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)

    # The plan
    plan_id: str | None = None

    # Governance (18-F reference)
    governance_report_id: str | None = None
    hitl_approval_ids: list[str] = Field(default_factory=list)

    # The artifacts
    transformation_artifact_ids: list[str] = Field(default_factory=list)
    final_artifact_ids: list[str] = Field(default_factory=list)

    # Status
    is_complete: bool = False

    created_at: datetime = Field(default_factory=_utc_now)
    last_updated: datetime = Field(default_factory=_utc_now)

    def add_link(self, link: ProvenanceLink) -> None:
        """Add a link to the chain."""
        self.links.append(link)
        self.last_updated = _utc_now()

    def get_stages_completed(self) -> list[ProvenanceStage]:
        """Get the set of stages that have at least one link."""
        return list({link.stage for link in self.links})

    def is_chain_complete(self) -> bool:
        """Return True if the chain has progressed through all stages."""
        required_stages = {
            ProvenanceStage.SOURCE,
            ProvenanceStage.ANALYSIS,
            ProvenanceStage.EVIDENCE,
            ProvenanceStage.RECOMMENDATION,
            ProvenanceStage.PLAN,
            ProvenanceStage.APPROVAL,
            ProvenanceStage.TRANSFORMATION,
            ProvenanceStage.VERIFICATION,
            ProvenanceStage.ARTIFACT,
            ProvenanceStage.GOVERNANCE,
        }
        return required_stages.issubset(set(self.get_stages_completed()))
