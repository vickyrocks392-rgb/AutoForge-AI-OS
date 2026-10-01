"""
Execution Platform domain models — Phase 10.

Defines all value objects, states, configs, and outcome structures used
by the Execution Platform, Worker Lifecycle, Engineering Loop, Evaluation
Engine, and Artifact Pipeline.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Worker Enumerations ───────────────────────────────────────────────────


class WorkerStatus(str, Enum):
    """
    Lifecycle status of an engineering worker.

    Deterministic transitions:
        CREATED   → READY | CANCELLED
        READY     → RUNNING | CANCELLED
        RUNNING   → COMPLETED | FAILED | CANCELLED | BLOCKED | WAITING_APPROVAL
        BLOCKED   → RUNNING | CANCELLED | FAILED
        WAITING_APPROVAL → RUNNING | CANCELLED | FAILED
        COMPLETED (terminal)
        FAILED    (terminal)
        CANCELLED (terminal)
    """

    CREATED = "created"
    """Worker instantiated; not yet started."""

    READY = "ready"
    """Worker initialised and ready to accept execution assignment."""

    RUNNING = "running"
    """Worker is actively executing its engineering loop."""

    COMPLETED = "completed"
    """Worker completed its task successfully (terminal)."""

    FAILED = "failed"
    """Worker failed its task (terminal)."""

    CANCELLED = "cancelled"
    """Worker execution was cancelled (terminal)."""

    BLOCKED = "blocked"
    """Worker is temporarily blocked waiting for external resource."""

    WAITING_APPROVAL = "waiting_approval"
    """Worker is paused at an HITL governance approval gate."""


class WorkerType(str, Enum):
    """Specialisation role of an engineering worker."""

    GENERAL = "general"
    CODING = "coding"
    TESTING = "testing"
    REPAIR = "repair"
    RESEARCH = "research"
    REVIEW = "review"


# ── Command & Environment Models ──────────────────────────────────────────


class CommandSpec(BaseModel):
    """Specification of an OS command to execute in a workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    argv: list[str] = Field(
        ...,
        min_length=1,
        description="Command and arguments list (no shell injection).",
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory relative to workspace root (None = workspace root).",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Custom environment variables.",
    )
    timeout_seconds: float = Field(
        default=60.0,
        gt=0.0,
        le=3600.0,
        description="Maximum execution time budget in seconds.",
    )
    capture_output: bool = Field(
        default=True,
        description="Whether to capture stdout and stderr.",
    )


class CommandResult(BaseModel):
    """Result of a command execution in the workspace environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: list[str] = Field(..., description="Executed command argv.")
    exit_code: int = Field(..., description="Process exit code.")
    stdout: str = Field(default="", description="Captured stdout string.")
    stderr: str = Field(default="", description="Captured stderr string.")
    duration_seconds: float = Field(..., ge=0.0, description="Duration in seconds.")
    timed_out: bool = Field(default=False, description="True if command was terminated by timeout.")
    executed_at: datetime = Field(default_factory=_utc_now, description="Execution timestamp.")

    @property
    def passed(self) -> bool:
        """True if process exited with code 0 and did not time out."""
        return self.exit_code == 0 and not self.timed_out


# ── Evaluation Models ──────────────────────────────────────────────────────


class EvaluationStatus(str, Enum):
    """Overall outcome status of an evaluation."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    INCONCLUSIVE = "inconclusive"


class DeterministicCheckResult(BaseModel):
    """One deterministic rule evaluation (e.g. exit code, file existence)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_name: str = Field(..., min_length=1)
    passed: bool = Field(...)
    message: str = Field(default="")
    details: dict[str, Any] = Field(default_factory=dict)


class TestResultSummary(BaseModel):
    """Structured test outcomes parsed from test command outputs."""

    __test__ = False
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_tests: int = Field(default=0, ge=0)
    passed_tests: int = Field(default=0, ge=0)
    failed_tests: int = Field(default=0, ge=0)
    error_tests: int = Field(default=0, ge=0)
    xfailed_tests: int = Field(default=0, ge=0)
    skipped_tests: int = Field(default=0, ge=0)
    failure_details: list[str] = Field(default_factory=list)
    raw_summary_line: str = Field(default="")

    @property
    def all_passed(self) -> bool:
        return self.total_tests > 0 and self.failed_tests == 0 and self.error_tests == 0


class EvaluationResult(BaseModel):
    """
    Structured evaluation result produced at the end of an engineering loop iteration.

    Combines deterministic checks, test results, command executions, and AI findings.
    Deterministic checks ALWAYS take precedence over model confidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: EvaluationStatus = Field(..., description="Overall evaluation status.")
    deterministic_checks: list[DeterministicCheckResult] = Field(
        default_factory=list,
        description="Deterministic verification results.",
    )
    test_results: TestResultSummary | None = Field(
        default=None,
        description="Parsed test runner summary, if available.",
    )
    execution_results: list[CommandResult] = Field(
        default_factory=list,
        description="Command execution results evaluated.",
    )
    qualitative_findings: str = Field(
        default="",
        description="Optional qualitative analysis from AI model.",
    )
    failures: list[str] = Field(
        default_factory=list,
        description="Explicit list of failure reasons.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Recommendations for diagnosis / repair.",
    )
    evaluated_at: datetime = Field(default_factory=_utc_now)

    @property
    def passed(self) -> bool:
        """Convenience property: True if status is PASSED."""
        return self.status == EvaluationStatus.PASSED


# ── Diagnosis & Repair Models ─────────────────────────────────────────────


class DiagnosisReport(BaseModel):
    """Diagnosis of why an engineering attempt failed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root_cause: str = Field(..., min_length=1, description="Identified root cause.")
    failure_mechanism: str = Field(default="", description="How the failure occurred.")
    affected_files: list[str] = Field(default_factory=list, description="Files relevant to the bug.")
    suggested_fix: str = Field(default="", description="Proposed fix or repair strategy.")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Model confidence 0..1.")
    diagnosed_at: datetime = Field(default_factory=_utc_now)


class RepairStrategy(BaseModel):
    """A strategy for reimplementing or repairing a failed attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str = Field(..., min_length=1)
    planned_file_edits: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = Field(default="")


# ── Artifact Pipeline Models ──────────────────────────────────────────────


class ArtifactType(str, Enum):
    """Classification of artifacts produced during execution."""

    SOURCE_CODE = "source_code"
    DIFF = "diff"
    TEST_REPORT = "test_report"
    EXECUTION_LOG = "execution_log"
    EVALUATION_REPORT = "evaluation_report"
    DIAGNOSIS_REPORT = "diagnosis_report"
    REPAIR_PLAN = "repair_plan"
    SUMMARY = "summary"
    METRIC = "metric"


class ArtifactProvenance(BaseModel):
    """Provenance tracking for artifacts produced by workers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(...)
    worker_id: str = Field(...)
    workflow_id: uuid.UUID | None = Field(default=None)
    correlation_id: uuid.UUID | None = Field(default=None)
    attempt_number: int = Field(default=1, ge=1)
    iteration: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(BaseModel):
    """A persistent engineering artifact captured by the Artifact Pipeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: uuid.UUID = Field(default_factory=_new_uuid)
    name: str = Field(..., min_length=1)
    artifact_type: ArtifactType = Field(...)
    content: str = Field(default="", description="Textual or serialized content.")
    path: str | None = Field(default=None, description="Workspace path if file-based.")
    size_bytes: int = Field(default=0, ge=0)
    checksum: str = Field(default="", description="SHA-256 content checksum.")
    provenance: ArtifactProvenance = Field(...)

    @classmethod
    def create(
        cls,
        name: str,
        artifact_type: ArtifactType,
        content: str,
        provenance: ArtifactProvenance,
        path: str | None = None,
    ) -> ArtifactRecord:
        content_bytes = content.encode("utf-8")
        checksum = hashlib.sha256(content_bytes).hexdigest()
        return cls(
            name=name,
            artifact_type=artifact_type,
            content=content,
            path=path,
            size_bytes=len(content_bytes),
            checksum=checksum,
            provenance=provenance,
        )


# ── Engineering Loop Models ───────────────────────────────────────────────


class LoopStatus(str, Enum):
    """Lifecycle status of an engineering execution loop."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    EVALUATING = "evaluating"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class LoopConfig(BaseModel):
    """Configuration governing the bounds and behaviour of an engineering loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_iterations: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum repair loop iterations before terminating as failed.",
    )
    timeout_seconds: float = Field(
        default=300.0,
        ge=1.0,
        le=3600.0,
        description="Total wall-clock time limit for the entire loop.",
    )
    max_consecutive_failures: int = Field(
        default=3,
        ge=1,
        description="Maximum consecutive identical failures before escalating.",
    )
    stop_on_first_pass: bool = Field(
        default=True,
        description="Terminate loop immediately upon achieving PASSED evaluation.",
    )


class LoopIterationRecord(BaseModel):
    """Historical record of one iteration within the engineering loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    iteration: int = Field(..., ge=1)
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = Field(default=None)
    action_plan: str = Field(default="", description="Plan generated for this iteration.")
    changed_files: list[str] = Field(default_factory=list)
    commands_executed: list[CommandResult] = Field(default_factory=list)
    evaluation: EvaluationResult | None = Field(default=None)
    diagnosis: DiagnosisReport | None = Field(default=None)
    passed: bool = Field(default=False)


# ── Governance Models ─────────────────────────────────────────────────────


class ConsequentialActionType(str, Enum):
    """Actions requiring explicit HITL approval if configured."""

    TECH_STACK_FINALIZATION = "tech_stack_finalization"
    ARCHITECTURE_FINALIZATION = "architecture_finalization"
    GIT_COMMIT = "git_commit"
    GIT_PUSH = "git_push"
    DEPLOYMENT = "deployment"
    PUBLISH = "publish"
    DESTRUCTIVE_CLEANUP = "destructive_cleanup"


class GovernancePolicy(BaseModel):
    """Policy configuring which consequential actions require human approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    consequential_actions_requiring_approval: frozenset[ConsequentialActionType] = Field(
        default_factory=lambda: frozenset({
            ConsequentialActionType.TECH_STACK_FINALIZATION,
            ConsequentialActionType.GIT_PUSH,
            ConsequentialActionType.DEPLOYMENT,
            ConsequentialActionType.PUBLISH,
        }),
        description="Set of actions that pause for human approval.",
    )
    auto_approve_safe_actions: bool = Field(
        default=True,
        description="Allow normal file edits and tests to proceed autonomously without pausing.",
    )


# ── Worker Mutable Execution State ────────────────────────────────────────


@dataclass
class WorkerState:
    """
    Mutable execution state for an active engineering worker instance.
    """

    worker_id: str
    worker_type: WorkerType
    task_id: str
    workflow_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None
    attempt_number: int = 1

    status: WorkerStatus = WorkerStatus.CREATED
    started_at: datetime | None = None
    finished_at: datetime | None = None

    current_iteration: int = 0
    iteration_history: list[LoopIterationRecord] = field(default_factory=list)
    produced_artifacts: list[ArtifactRecord] = field(default_factory=list)

    last_error_code: str | None = None
    last_error_message: str | None = None
    last_evaluation: EvaluationResult | None = None
    last_diagnosis: DiagnosisReport | None = None

    cancellation_requested: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            WorkerStatus.COMPLETED,
            WorkerStatus.FAILED,
            WorkerStatus.CANCELLED,
        }

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize for runtime checkpointing."""
        return {
            "worker_id": self.worker_id,
            "worker_type": self.worker_type.value,
            "task_id": self.task_id,
            "workflow_id": str(self.workflow_id) if self.workflow_id else None,
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "attempt_number": self.attempt_number,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "current_iteration": self.current_iteration,
            "iteration_count": len(self.iteration_history),
            "artifact_count": len(self.produced_artifacts),
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "cancellation_requested": self.cancellation_requested,
            "metadata": self.metadata,
        }


# ── Phase 18-E: RAG Retrieval Engine Protocol ─────────────────────────────────

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RAGRetrievalEngine(Protocol):
    """
    Protocol for a RAG-enabled knowledge retrieval engine.

    Matches the interface of
    ``autoforge_knowledge_platform.rag18.facade.KnowledgeRAGEngine``.
    The execution layer depends only on this protocol — no runtime import of
    ``autoforge_knowledge_platform`` is required.

    Implementations must provide:

        await engine.retrieve_for_context(
            query: str,
            *,
            project_id: str | None = None,
            workflow_id: str | None = None,
            execution_id: str | None = None,
            workspace_root: str | None = None,
            top_k: int | None = None,
            score_threshold: float | None = None,
        ) -> Any

    The returned value is duck-typed: it must have ``.hits`` or ``.results``
    (a list of retrieval hits).
    """

    async def retrieve_for_context(
        self,
        query: str,
        *,
        project_id: str | None = None,
        workflow_id: str | None = None,
        execution_id: str | None = None,
        workspace_root: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> Any: ...
