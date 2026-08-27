"""
Legacy System, Evidence, and Business Rule models.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class FactState(str, Enum):
    """
    Distinguishes the level of certainty of a claimed fact in legacy system reconstruction.
    """
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


class LegacyEvidence(BaseModel):
    """
    Traceable evidence backing a claim about a legacy system.
    """
    evidence_id: str
    source_file: str
    line_range: Optional[str] = None # e.g. "120-145"
    analyzer_id: str # The analyzer tool or agent name that extracted it
    observation: str # What was exactly observed
    confidence: float = Field(..., ge=0.0, le=1.0)
    validation_state: str = "unvalidated" # e.g. "validated", "rejected", "unvalidated"
    metadata: dict[str, Any] = Field(default_factory=dict)


class BusinessRule(BaseModel):
    """
    Reconstructed business rule with traceability to source code, data, tests, etc.
    """
    rule_id: str
    statement: str
    evidence: list[LegacyEvidence] = Field(default_factory=list)
    contradictory_evidence: list[LegacyEvidence] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    validation_status: str = "unvalidated" # e.g. "approved", "rejected", "unvalidated"
    state: FactState = FactState.UNKNOWN


class LegacySystemModel(BaseModel):
    """
    Canonical representation of a discovered legacy system.
    """
    system_id: str
    name: str
    description: str = ""

    # Elements of the system
    components: dict[str, FactState] = Field(default_factory=dict) # component_name -> state
    technologies: dict[str, FactState] = Field(default_factory=dict) # technology -> state
    data_stores: dict[str, FactState] = Field(default_factory=dict) # datastore -> state
    interfaces: dict[str, FactState] = Field(default_factory=dict) # interface_name -> state
    jobs: dict[str, FactState] = Field(default_factory=dict) # job/schedule -> state
    dependencies: dict[str, list[str]] = Field(default_factory=dict) # component -> dependent components
    business_processes: dict[str, FactState] = Field(default_factory=dict)
    business_rules: list[BusinessRule] = Field(default_factory=list)
    runtime_behavior: dict[str, Any] = Field(default_factory=dict)
    deployment_topology: dict[str, Any] = Field(default_factory=dict)

    # Gaps where information is missing or technology is unknown
    analysis_gaps: list[dict[str, Any]] = Field(default_factory=list)

    # Global evidence registry
    evidence_ledger: list[LegacyEvidence] = Field(default_factory=list)

    def record_evidence(self, evidence: LegacyEvidence) -> None:
        self.evidence_ledger.append(evidence)

    def record_gap(self, area: str, description: str, severity: str = "low") -> None:
        self.analysis_gaps.append({
            "area": area,
            "description": description,
            "severity": severity,
            "status": "open"
        })
