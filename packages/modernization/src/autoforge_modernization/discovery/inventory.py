"""Authoritative Project Technology Inventory for AutoForge.

Enforces Section 4 of the architectural mandate:
Produce a generalized ProjectTechnologyInventory containing:
- detected technology
- evidence
- affected files
- LOC
- confidence
- detection provider
- capability requirements implied by the technology
Simultaneously represents multi-technology enterprise systems.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.models import (
    CapabilityRequirement,
    _utc_now,
)
from autoforge_modernization.discovery.evidence import TechnologyEvidenceRecord


class DetectedTechnologySummary(BaseModel):
    """Authoritative record of a detected technology within a project."""

    technology: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    detection_method: str = "multi_provider_evidence"
    files_count: int = 0
    physical_loc: int = 0
    logical_loc: int = 0
    sample_files: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    evidence: list[TechnologyEvidenceRecord] = Field(default_factory=list)
    implied_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    is_primary: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectTechnologyInventory(BaseModel):
    """Authoritative technology inventory of an entire analyzed project codebase."""

    inventory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_path: str
    scanned_at: datetime = Field(default_factory=_utc_now)
    total_files_scanned: int = 0
    total_physical_loc: int = 0
    technologies: dict[str, DetectedTechnologySummary] = Field(default_factory=dict)
    primary_technology: str | None = None
    all_implied_requirements: list[CapabilityRequirement] = Field(default_factory=list)
    detection_providers_used: list[str] = Field(default_factory=list)

    def add_technology(self, summary: DetectedTechnologySummary) -> None:
        self.technologies[summary.technology.upper()] = summary
        self._recalculate()

    def get(self, technology: str) -> DetectedTechnologySummary | None:
        return self.technologies.get(technology.upper())

    def has_technology(self, technology: str) -> bool:
        return technology.upper() in self.technologies

    def detected_technology_names(self) -> list[str]:
        return sorted(list(self.technologies.keys()))

    def _recalculate(self) -> None:
        if not self.technologies:
            self.primary_technology = None
            self.all_implied_requirements = []
            return

        # Determine primary technology based on LOC and file count
        best_tech = max(
            self.technologies.values(),
            key=lambda t: (t.physical_loc, t.files_count, t.confidence),
        )
        self.primary_technology = best_tech.technology
        for tech in self.technologies.values():
            tech.is_primary = (tech.technology == best_tech.technology)

        # Aggregate all implied capability requirements (deduplicating by capability_name)
        req_map: dict[str, CapabilityRequirement] = {}
        for tech in self.technologies.values():
            for req in tech.implied_requirements:
                req_map[f"{req.technology}:{req.capability_name}"] = req
        self.all_implied_requirements = list(req_map.values())
