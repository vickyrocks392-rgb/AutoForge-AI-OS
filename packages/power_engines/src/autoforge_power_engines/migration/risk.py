"""Deterministic Migration Risk Classification Engine (18-COMMERCIAL-D).

Classifies risk across migration units into LOW, MEDIUM, HIGH, and CRITICAL.
Enforces deterministic risk thresholds based on language constructs, financial logic,
dynamic behavior, concurrency, database mutations, and missing tests.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.migration.inventory import FileInventoryRecord
from autoforge_power_engines.migration.analysis import SourceAnalysisReport, CodeEntity


class MigrationRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MigrationRiskAssessment(BaseModel):
    """Detailed risk assessment for a migration unit or overall codebase."""
    risk_level: MigrationRiskLevel
    score: float  # 0.0 to 10.0
    risk_factors: List[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    remediation_recommendations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MigrationRiskClassifier:
    """
    Deterministic risk classifier for code migration units.
    """

    # High-risk patterns
    CRITICAL_PATTERNS = [
        re.compile(r"\b(inline-assembly|asm\b|__asm__)", re.IGNORECASE),
        re.compile(r"\bpointer\s*arithmetic\b", re.IGNORECASE),
        re.compile(r"\bunsafe\s*\{", re.IGNORECASE),
    ]

    HIGH_RISK_PATTERNS = [
        re.compile(r"\b(eval|exec|compile)\s*\(", re.IGNORECASE),
        re.compile(r"\b(reflection|Method\.invoke|Class\.forName)\b", re.IGNORECASE),
        re.compile(r"\b(COMP-3|PACKED-DECIMAL|BigDecimal)\b", re.IGNORECASE),
        re.compile(r"\b(Thread|Runnable|synchronized|asyncio\.create_task)\b", re.IGNORECASE),
        re.compile(r"\b(crypto|cipher|private_key|authenticate|password)\b", re.IGNORECASE),
    ]

    MEDIUM_RISK_PATTERNS = [
        re.compile(r"\b(EXEC\s+SQL|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b", re.IGNORECASE),
        re.compile(r"\b(socket|urllib|requests|http\.client)\b", re.IGNORECASE),
        re.compile(r"\b(subprocess|Popen|system\s*\()\b", re.IGNORECASE),
    ]

    @classmethod
    def evaluate_unit(
        cls,
        file_rec: FileInventoryRecord,
        content: str,
        entity: Optional[CodeEntity] = None,
        has_tests: bool = True,
    ) -> MigrationRiskAssessment:
        score = 1.0  # Base low risk
        factors: List[str] = []
        remediations: List[str] = []

        # 1. Check CRITICAL patterns
        for p in cls.CRITICAL_PATTERNS:
            if p.search(content):
                score += 5.0
                factors.append(f"Critical construct detected: {p.pattern}")
                remediations.append("Manual architectural review required for system-level constructs.")

        # 2. Check HIGH risk patterns
        for p in cls.HIGH_RISK_PATTERNS:
            if p.search(content):
                score += 3.0
                factors.append(f"High risk construct: {p.pattern}")
                remediations.append("Ensure comprehensive invariant unit testing and behavior comparison.")

        # 3. Check MEDIUM risk patterns
        for p in cls.MEDIUM_RISK_PATTERNS:
            if p.search(content):
                score += 1.5
                factors.append(f"Stateful or external operation: {p.pattern}")
                remediations.append("Verify database query semantics and transactional boundaries.")

        # 4. Binary or generated code
        if file_rec.is_binary:
            score += 4.0
            factors.append("Binary artifact cannot be directly transpiled")
        if file_rec.is_generated:
            score += 1.0
            factors.append("Generated file may need re-generation rather than direct migration")

        # 5. Missing tests penalty
        if not has_tests and file_rec.classification == "source":
            score += 2.0
            factors.append("Missing source tests: increases behavioral regression risk")
            remediations.append("Synthesize golden test cases before applying transformations.")

        # Determine level
        if score >= 7.0 or any("Critical" in f for f in factors):
            level = MigrationRiskLevel.CRITICAL
            approval_req = True
        elif score >= 4.5:
            level = MigrationRiskLevel.HIGH
            approval_req = True
        elif score >= 2.5:
            level = MigrationRiskLevel.MEDIUM
            approval_req = False
        else:
            level = MigrationRiskLevel.LOW
            approval_req = False

        return MigrationRiskAssessment(
            risk_level=level,
            score=min(score, 10.0),
            risk_factors=factors,
            requires_human_approval=approval_req,
            remediation_recommendations=remediations,
            metadata={"file": file_rec.relative_path, "language": file_rec.language},
        )

    @classmethod
    def evaluate_overall(
        cls,
        analysis_report: SourceAnalysisReport,
        total_files: int,
        has_tests: bool,
    ) -> MigrationRiskAssessment:
        overall_score = 1.0
        factors = list(analysis_report.identified_risks)
        remediations = []

        if not has_tests:
            overall_score += 2.5
            factors.append("Codebase lacks automated test suites")
            remediations.append("Generate characterization tests to capture existing behavior.")

        if analysis_report.database_interactions:
            overall_score += 1.5
            factors.append(f"Extracted {len(analysis_report.database_interactions)} database interactions")
            remediations.append("Formulate relational schema mapping and data migration strategy.")

        if len(analysis_report.entities) > 50:
            overall_score += 1.0
            factors.append("High project complexity: substantial entity count")

        if overall_score >= 6.0:
            level = MigrationRiskLevel.HIGH
            approval_req = True
        elif overall_score >= 3.0:
            level = MigrationRiskLevel.MEDIUM
            approval_req = False
        else:
            level = MigrationRiskLevel.LOW
            approval_req = False

        return MigrationRiskAssessment(
            risk_level=level,
            score=min(overall_score, 10.0),
            risk_factors=factors,
            requires_human_approval=approval_req,
            remediation_recommendations=remediations,
            metadata={"total_entities": len(analysis_report.entities), "total_files": total_files},
        )
