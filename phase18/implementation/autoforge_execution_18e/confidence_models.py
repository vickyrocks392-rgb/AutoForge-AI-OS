"""Phase 18-E — Diagnosis & Repair Models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ConfidenceLevel(str, Enum):
    """
    Confidence levels for diagnosis and repair reliability.
    NOT statistical calibration — evidence-density-based confidence.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        if score < 0.3:
            return cls.LOW
        elif score < 0.6:
            return cls.MEDIUM
        elif score < 0.85:
            return cls.HIGH
        else:
            return cls.VERY_HIGH

    @property
    def min_score(self) -> float:
        return {
            cls.LOW: 0.0,
            cls.MEDIUM: 0.3,
            cls.HIGH: 0.6,
            cls.VERY_HIGH: 0.85,
        }[self]


class ConfidenceEvidence(str, Enum):
    """Types of evidence contributing to confidence score."""

    FAILURE_STDERR = "failure_stderr"
    FAILURE_STDOUT = "failure_stdout"
    TEST_FAILURES = "test_failures"
    ASSERTION_ERROR = "assertion_error"
    FILE_CHANGES = "file_changes"
    RAG_RETRIEVAL = "rag_retrieval"
    RAG_SCORE_HIGH = "rag_score_high"
    ROOT_CAUSE_DETERMINED = "root_cause_determined"
    AFFECTED_FILES = "affected_files"
    SUGGESTED_FIX = "suggested_fix"


@dataclass
class DiagnosisEvidence:
    """Structured evidence collected during diagnosis."""

    evidence_types: list[ConfidenceEvidence] = field(default_factory=list)
    evidence_count: int = 0
    rag_retrieval_count: int = 0
    rag_max_score: float | None = None
    failure_stderr: str = ""
    failure_stdout: str = ""
    test_failures: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    root_cause: str = ""
    suggested_fix: str = ""

    def add_evidence(self, evidence_type: ConfidenceEvidence) -> None:
        if evidence_type not in self.evidence_types:
            self.evidence_types.append(evidence_type)
        self.evidence_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_types": [e.value for e in self.evidence_types],
            "evidence_count": self.evidence_count,
            "rag_retrieval_count": self.rag_retrieval_count,
            "rag_max_score": self.rag_max_score,
            "failure_stderr": self.failure_stderr[:500],
            "failure_stdout": self.failure_stdout[:500],
            "test_failures": self.test_failures[:20],
            "affected_files": self.affected_files,
            "root_cause": self.root_cause,
            "suggested_fix": self.suggested_fix,
        }


@dataclass
class DiagnosisConfidence:
    """Confidence annotation. calibrated=False = not statistically calibrated."""

    score: float
    level: ConfidenceLevel
    evidence: DiagnosisEvidence
    calibrated: bool = False

