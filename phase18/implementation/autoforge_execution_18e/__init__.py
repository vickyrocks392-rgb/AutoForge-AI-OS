"""
Phase 18-E: Real Testing / Evaluation / Diagnosis / Repair

This module extends the Phase 10 execution infrastructure with:
- RAG-integrated failure diagnosis using 18-D KnowledgeRAGEngine
- Safe file edit mechanism with target verification
- Repair validation models
- Complete repair cycle integration

Reuses existing infrastructure:
- EngineeringLoop
- FailureDiagnoser
- EvaluationEngine
- KnowledgeRAGEngine
- ExecutionContext.retrieved_knowledge
- Artifact pipeline
- Worker lifecycle
"""

from __future__ import annotations

from autoforge_execution_18e.confidence_models import (
    ConfidenceLevel,
    ConfidenceEvidence,
    DiagnosisConfidence,
    DiagnosisEvidence,
)
from autoforge_execution_18e.repair_models import (
    RepairAttempt,
    RepairResult,
    RepairStatus,
    RepairFailureReason,
    SafeFileEdit,
    SafeFileEditResult,
)
from autoforge_execution_18e.safe_edit import SafeFileEditor
from autoforge_execution_18e.diagnosis_rag import RAGIntegratedDiagnoser
from autoforge_execution_18e.repair_cycle import RepairCycle, RepairCycleConfig
from autoforge_execution_18e.confidence import DiagnosisConfidenceCalculator

__all__ = [
    "ConfidenceLevel",
    "ConfidenceEvidence",
    "DiagnosisConfidence",
    "DiagnosisEvidence",
    "RepairAttempt",
    "RepairResult",
    "RepairStatus",
    "RepairFailureReason",
    "SafeFileEdit",
    "SafeFileEditResult",
    "SafeFileEditor",
    "RAGIntegratedDiagnoser",
    "RepairCycle",
    "RepairCycleConfig",
    "DiagnosisConfidenceCalculator",
]
