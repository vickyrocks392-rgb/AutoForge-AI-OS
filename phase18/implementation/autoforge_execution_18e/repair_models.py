"""Phase 18-E — Repair Models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RepairStatus(str, Enum):
    """Outcome status of a repair attempt."""
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class RepairFailureReason(str, Enum):
    """Reason why a repair was rejected or failed."""
    NONE = "none"
    TARGET_MISMATCH = "target_mismatch"
    EMPTY_REPAIR = "empty_repair"
    INVALID_REPAIR = "invalid_repair"
    RAG_UNAVAILABLE = "rag_unavailable"
    DIAGNOSIS_FAILURE = "diagnosis_failure"
    INVALID_EDIT = "invalid_edit"
    REEXECUTION_FAILED = "reexecution_failed"
    TESTS_STILL_FAILING = "tests_still_failing"
    RETRY_EXHAUSTED = "retry_exhausted"


@dataclass
class SafeFileEdit:
    """A file edit with pre-conditions for safe application."""
    target_path: str
    new_content: str
    expected_content: str | None = None
    expected_content_hash: str | None = None
    edit_description: str = ""


@dataclass
class SafeFileEditResult:
    """Result of attempting a safe file edit."""
    edit: SafeFileEdit
    success: bool
    actual_content_matches: bool
    content_hash_matches: bool
    old_content: str | None = None
    new_content: str | None = None
    error: str | None = None

    @property
    def status(self) -> RepairFailureReason:
        if self.success:
            return RepairFailureReason.NONE
        if not self.actual_content_matches and not self.content_hash_matches:
            return RepairFailureReason.TARGET_MISMATCH
        return RepairFailureReason.INVALID_EDIT


@dataclass
class RepairAttempt:
    """A single repair attempt record."""
    attempt_number: int
    diagnosis: Any = None
    retrieved_knowledge: list = field(default_factory=list)
    file_edits: list = field(default_factory=list)
    edit_results: list = field(default_factory=list)
    reexecution_results: list = field(default_factory=list)
    reevaluation: Any = None
    status: RepairStatus = RepairStatus.SKIPPED
    failure_reason: RepairFailureReason = RepairFailureReason.NONE
    confidence: Any = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = field(default=None)

    def to_dict(self):
        return {
            "attempt_number": self.attempt_number,
            "status": self.status.value,
            "failure_reason": self.failure_reason.value,
            "diagnosis": self.diagnosis.model_dump() if hasattr(self.diagnosis, "model_dump") else None,
            "retrieved_knowledge_count": len(self.retrieved_knowledge),
            "file_edits_count": len(self.file_edits),
            "edit_results": [
                {"target_path": er.edit.target_path, "success": er.success,
                 "actual_content_matches": er.actual_content_matches,
                 "content_hash_matches": er.content_hash_matches, "error": er.error}
                for er in self.edit_results
            ],
            "reevaluation_status": self.reevaluation.status.value if self.reevaluation else None,
            "reevaluation_passed": self.reevaluation.passed if self.reevaluation else None,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


@dataclass
class RepairResult:
    """Final result of the complete bounded repair cycle."""
    cycle_complete: bool
    final_status: RepairStatus
    final_evaluation: Any = None
    attempts: list = field(default_factory=list)
    total_attempts: int = 0
    retry_exhausted: bool = False
    failure_reason: RepairFailureReason = RepairFailureReason.NONE
    final_confidence: Any = None

    @property
    def passed(self) -> bool:
        return self.final_status == RepairStatus.SUCCESS
