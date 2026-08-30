"""Phase 18 orchestration domain models.

Defines the canonical value objects for the autonomous engineering
orchestration platform:

- Definition-time models (immutable): ``StageDefinition``,
  ``WorkflowDefinition``, ``HITLGateSpec``.
- Execution-time state (mutable): ``ProjectExecutionState``,
  ``StageExecutionState`` — durable, resumable, observable.
- Structured contracts, routing decisions, evaluation verdicts, diagnosis
  outcomes, review verdicts, HITL records, deployment results, metrics.

Design rules
------------
- Definition models are frozen Pydantic models (accidental mutation is
  impossible).
- Execution state is a mutable dataclass with explicit snapshot/restore
  (``to_snapshot`` / ``from_snapshot``) so process-restart recovery is real.
- No imports from the autoforge_workflows runtime or the autoforge_runtime
  internals: this platform composes the existing subsystems at the wiring
  boundary, not here.
"""

from __future__ import annotations

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


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


# ── Enumerations ───────────────────────────────────────────────────────────


class RunMode(str, Enum):
    """Distinguishes the two canonical Phase 18 engineering pipelines."""

    GREENFIELD = "greenfield"
    LEGACY_MODERNIZATION = "legacy_modernization"


class StageKind(str, Enum):
    """Canonical pipeline stage kinds (GREENFIELD + LEGACY)."""

    # Greenfield
    IDEA = "idea"
    INTENT = "intent"
    RESEARCH = "research"
    PLANNING = "planning"
    ARCHITECTURE = "architecture"
    DESIGN = "design"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"
    EVALUATION = "evaluation"
    DIAGNOSIS = "diagnosis"
    REPAIR = "repair"
    REIMPLEMENTATION = "reimplementation"
    RETEST = "retesting"
    REVIEW = "review"
    ARTIFACT = "artifact"
    DEPLOYMENT = "deployment"

    # Legacy modernization
    LEGACY_DISCOVERY = "legacy_discovery"
    LEGACY_ARCHAEOLOGY = "legacy_archaeology"
    ARCHITECTURE_RECONSTRUCTION = "architecture_reconstruction"
    BUSINESS_RULES_EXTRACTION = "business_rules_extraction"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    MODERNIZATION_ARCHITECTURE = "modernization_architecture"
    MIGRATION_IMPLEMENTATION = "migration_implementation"
    EQUIVALENCE_VALIDATION = "equivalence_validation"
    LEGACY_VALIDATION = "legacy_validation"
    CUTOVER = "cutover"


class StageStatus(str, Enum):
    """Explicit stage lifecycle states.

    Transition table lives in ``autoforge_orchestration.states``.

        PENDING  -> READY | BLOCKED | SKIPPED | CANCELLED
        READY    -> RUNNING | BLOCKED | CANCELLED
        RUNNING  -> SUCCEEDED | FAILED | RETRYING | WAITING_FOR_HITL | CANCELLED
        RETRYING -> RUNNING | FAILED | CANCELLED
        WAITING_FOR_HITL -> RUNNING | FAILED | CANCELLED
        BLOCKED  -> READY | CANCELLED
        FAILED   -> RETRYING | CANCELLED   (caller checks bounds before re-entry)
        SUCCEEDED / SKIPPED / CANCELLED (terminal)
    """

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    WAITING_FOR_HITL = "waiting_for_hitl"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class WorkflowStatus(str, Enum):
    """Project-execution level lifecycle status."""

    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_HITL = "waiting_for_hitl"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"

# ── Definition-time models ──────────────────────────────────────────────────


class HITLGateSpec(BaseModel):
    """Specification of a mandatory human-approval gate on a stage."""

    model_config = ConfigDict(frozen=True)

    gate_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    risk_level: str = "medium"  # low | medium | high | critical
    description: str = ""
    decision_hint: str = ""


class StageDefinition(BaseModel):
    """Immutable definition of a workflow stage."""

    model_config = ConfigDict(frozen=True)

    stage_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    kind: StageKind = Field(...)
    description: str = ""
    worker_type: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    model_requirements: dict[str, Any] = Field(default_factory=dict)
    hitl_gate: HITLGateSpec | None = None
    verification_commands: list[list[str]] = Field(default_factory=list)
    required_files: list[str] = Field(default_factory=list)
    review_required: bool = False
    artifact_types: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=2, ge=1)
    max_rectifications: int = Field(default=2, ge=0)
    execution_timeout_seconds: float = Field(default=120.0, gt=0.0)
    deployment_target: str | None = None
    deployment_strategy: str = "copy"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class WorkflowDefinition(BaseModel):
    """Immutable definition of a complete project workflow (stage DAG)."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    mode: RunMode = Field(...)
    stages: list[StageDefinition] = Field(min_length=1)
    version: str = "1.0.0"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def stage_map(self) -> dict[str, StageDefinition]:
        return {s.stage_id: s for s in self.stages}

    def roots(self) -> list[str]:
        ids = {s.stage_id for s in self.stages}
        deps = {d for s in self.stages for d in s.dependencies}
        return [s.stage_id for s in self.stages if s.stage_id not in deps]

    def stage_order(self) -> list[str]:
        """Deterministic topological order (Kahn; stable tie-breaking)."""
        remaining = {s.stage_id: set(s.dependencies) for s in self.stages}
        ordered: list[str] = []
        available = sorted(self.roots())
        processed: set[str] = set()
        while available:
            sid = available.pop(0)
            if sid in processed:
                continue
            processed.add(sid)
            ordered.append(sid)
            for s in self.stages:
                if sid in remaining[s.stage_id]:
                    remaining[s.stage_id].discard(sid)
            for s in sorted(self.stages, key=lambda x: x.stage_id):
                if (
                    s.stage_id not in processed
                    and s.stage_id not in available
                    and not remaining[s.stage_id]
                ):
                    available.append(s.stage_id)
            available.sort()
        if len(ordered) != len(self.stages):
            # Cycle — fall back to definition order (deterministic, explicit).
            seen = set(ordered)
            for s in self.stages:
                if s.stage_id not in seen:
                    ordered.append(s.stage_id)
        return ordered

class Verdict(str, Enum):
    """Stage evaluation verdict — structured, never overloaded."""

    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class ReviewVerdict(str, Enum):
    """Stage review gate verdict."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"


class FailureType(str, Enum):
    """Explicit failure classification for structured failure context."""

    INFRASTRUCTURE = "infrastructure"
    MODEL = "model"
    PROVIDER = "provider"
    NODE = "node"
    TOOL = "tool"
    TEST = "test"
    BUILD = "build"
    ARTIFACT = "artifact"
    RUNTIME = "runtime"
    REVIEW = "review"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class HITLStatus(str, Enum):
    """Lifecycle status of an HITL approval gate record."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class DeploymentStatus(str, Enum):
    """Truthful deployment outcome."""

    DEPLOYED = "deployed"
    UNAVAILABLE = "unavailable"
# ── Structured value objects (contracts, routing, gates) ───────────────────


@dataclass
class WorkerAssignment:
    """Capability-driven worker assignment provenance."""

    worker_id: str
    worker_type: str
    required_capabilities: list[str] = field(default_factory=list)
    assigned_at: str = field(default_factory=lambda: _iso(_utc_now()) or "")
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "required_capabilities": list(self.required_capabilities),
            "assigned_at": self.assigned_at,
            "evidence": self.evidence,
        }


@dataclass
class ModelDecision:
    """Retained model/node routing decision (provenance)."""

    model_id: str
    provider_id: str
    node_id: str
    policy_name: str = ""
    decision_id: str = ""
    rationale: str = ""
    resolved_capabilities: list[str] = field(default_factory=list)
    decided_at: str = field(default_factory=lambda: _iso(_utc_now()) or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "node_id": self.node_id,
            "policy_name": self.policy_name,
            "decision_id": self.decision_id,
            "rationale": self.rationale,
            "resolved_capabilities": list(self.resolved_capabilities),
            "decided_at": self.decided_at,
        }


@dataclass
class WorkerContractInput:
    """Structured worker invocation input."""

    task: str
    task_id: str
    stage_id: str
    project_context: dict[str, Any] = field(default_factory=dict)
    prior_artifacts: list[dict[str, Any]] = field(default_factory=list)
    relevant_evidence: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
    model_requirements: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "task_id": self.task_id,
            "stage_id": self.stage_id,
            "project_context": self.project_context,
            "prior_artifacts": self.prior_artifacts,
            "relevant_evidence": self.relevant_evidence,
            "constraints": self.constraints,
            "requirements": self.requirements,
            "available_tools": self.available_tools,
            "model_requirements": self.model_requirements,
        }


@dataclass
class WorkerContractOutput:
    """Structured worker invocation output."""

    result: Any = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    recommendations: list[str] = field(default_factory=list)
    failure: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "artifacts": list(self.artifacts),
            "evidence": list(self.evidence),
            "provenance": dict(self.provenance),
            "confidence": self.confidence,
            "recommendations": list(self.recommendations),
            "failure": self.failure,
        }


@dataclass
class StageEvaluationVerdict:
    """Structured evaluation gate outcome."""

    verdict: Verdict
    checks: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    test_summary: dict[str, Any] | None = None
    evaluated_at: str = field(default_factory=lambda: _iso(_utc_now()) or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "checks": list(self.checks),
            "failures": list(self.failures),
            "test_summary": self.test_summary,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class StructuredFailureContext:
    """Explicit structured failure capture (section 13)."""

    failure_type: FailureType
    stage_id: str
    worker_id: str = ""
    execution_ref: str = ""
    error: str = ""
    stderr: str = ""
    stdout: str = ""
    test_failures: list[str] = field(default_factory=list)
    artifact_state: dict[str, Any] = field(default_factory=dict)
    model_id: str = ""
    node_id: str = ""
    attempt: int = 0
    timestamp: str = field(default_factory=lambda: _iso(_utc_now()) or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_type": self.failure_type.value,
            "stage_id": self.stage_id,
            "worker_id": self.worker_id,
            "execution_ref": self.execution_ref,
            "error": self.error,
            "stderr": self.stderr,
            "stdout": self.stdout,
            "test_failures": list(self.test_failures),
            "artifact_state": dict(self.artifact_state),
            "model_id": self.model_id,
            "node_id": self.node_id,
            "attempt": self.attempt,
            "timestamp": self.timestamp,
        }


@dataclass
class DiagnosisOutcome:
    """Diagnosis result with explicit epistemic honesty."""

    root_cause: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    recommended_action: str = ""
    diagnosed_at: str = field(default_factory=lambda: _iso(_utc_now()) or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "diagnosed_at": self.diagnosed_at,
        }


@dataclass
class ReviewGateResult:
    """Stage review gate outcome."""

    verdict: ReviewVerdict
    review_id: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)
    reviewed_at: str = field(default_factory=lambda: _iso(_utc_now()) or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "review_id": self.review_id,
            "findings": list(self.findings),
            "reviewed_at": self.reviewed_at,
        }


@dataclass
class ProjectExecutionMetrics:
    """Real, persisted project execution metrics (section 23)."""

    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    attempt_count: int = 0
    failure_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    rectification_count: int = 0
    worker_count: int = 0
    inference_count: int = 0
    test_count: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    artifact_count: int = 0

    def record_attempt(self) -> None:
        self.attempt_count += 1

    def record_failure(self) -> None:
        self.failure_count += 1

    def record_error(self) -> None:
        self.error_count += 1

    def record_retry(self) -> None:
        self.retry_count += 1

    def record_rectification(self) -> None:
        self.rectification_count += 1

    def record_worker(self) -> None:
        self.worker_count += 1

    def record_inference(self) -> None:
        self.inference_count += 1

    def record_tests(self, passed: int, failed: int) -> None:
        self.test_count += passed + failed
        self.passed_tests += passed
        self.failed_tests += failed

    @property
    def total_failures(self) -> int:
        """Alias for failure_count (test compatibility)."""
        return self.failure_count

    def finalize(self, now: datetime | None = None) -> None:
        """Mark metrics collection complete and compute duration truthfully."""
        end = now or _utc_now()
        self.completed_at = _iso(end)
        if self.started_at:
            start = parse_iso(self.started_at)
            if start:
                self.duration_seconds = max(0.0, (end - start).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "attempt_count": self.attempt_count,
            "failure_count": self.failure_count,
            "error_count": self.error_count,
            "retry_count": self.retry_count,
            "rectification_count": self.rectification_count,
            "worker_count": self.worker_count,
            "inference_count": self.inference_count,
            "test_count": self.test_count,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "artifact_count": self.artifact_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectExecutionMetrics":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

@dataclass
class StageExecutionState:
    """Mutable, durable execution state for a single stage."""

    stage_id: str
    definition: StageDefinition
    status: StageStatus = StageStatus.PENDING
    attempt_number: int = 0
    rectification_count: int = 0
    worker_assignment: WorkerAssignment | None = None
    model_decision: ModelDecision | None = None
    contract_in: dict[str, Any] = field(default_factory=dict)
    contract_out: dict[str, Any] = field(default_factory=dict)
    failure: StructuredFailureContext | None = None
    diagnosis: DiagnosisOutcome | None = None
    evaluation: StageEvaluationVerdict | None = None
    review: ReviewGateResult | None = None
    hitl: HITLGateRecord | None = None
    deployment: DeploymentResult | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    loop_summary: dict[str, Any] | None = None
    result: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None

    def touch(self) -> None:
        self.updated_at = _iso(_utc_now())

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "definition": self.definition.to_dict(),
            "status": self.status.value,
            "attempt_number": self.attempt_number,
            "rectification_count": self.rectification_count,
            "worker_assignment": self.worker_assignment.to_dict() if self.worker_assignment else None,
            "model_decision": self.model_decision.to_dict() if self.model_decision else None,
            "contract_in": dict(self.contract_in),
            "contract_out": dict(self.contract_out),
            "failure": self.failure.to_dict() if self.failure else None,
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "review": self.review.to_dict() if self.review else None,
            "hitl": self.hitl.to_dict() if self.hitl else None,
            "deployment": self.deployment.to_dict() if self.deployment else None,
            "artifacts": list(self.artifacts),
            "loop_summary": self.loop_summary,
            "result": dict(self.result),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "StageExecutionState":
        definition = StageDefinition.model_validate(snapshot["definition"])
        state = cls(
            stage_id=snapshot["stage_id"],
            definition=definition,
            status=StageStatus(snapshot["status"]),
            attempt_number=snapshot.get("attempt_number", 0),
            rectification_count=snapshot.get("rectification_count", 0),
            contract_in=dict(snapshot.get("contract_in") or {}),
            contract_out=dict(snapshot.get("contract_out") or {}),
            artifacts=list(snapshot.get("artifacts") or []),
            loop_summary=snapshot.get("loop_summary"),
            result=dict(snapshot.get("result") or {}),
            started_at=snapshot.get("started_at"),
            finished_at=snapshot.get("finished_at"),
            updated_at=snapshot.get("updated_at"),
        )
        wa = snapshot.get("worker_assignment")
        if wa:
            state.worker_assignment = WorkerAssignment(**wa)
        md = snapshot.get("model_decision")
        if md:
            state.model_decision = ModelDecision(**md)
        f = snapshot.get("failure")
        if f:
            state.failure = StructuredFailureContext(
                failure_type=FailureType(f["failure_type"]),
                stage_id=f["stage_id"],
                worker_id=f.get("worker_id", ""),
                execution_ref=f.get("execution_ref", ""),
                error=f.get("error", ""),
                stderr=f.get("stderr", ""),
                stdout=f.get("stdout", ""),
                test_failures=list(f.get("test_failures") or []),
                artifact_state=dict(f.get("artifact_state") or {}),
                model_id=f.get("model_id", ""),
                node_id=f.get("node_id", ""),
                attempt=f.get("attempt", 0),
                timestamp=f.get("timestamp", ""),
            )
        d = snapshot.get("diagnosis")
        if d:
            state.diagnosis = DiagnosisOutcome(**d)
        ev = snapshot.get("evaluation")
        if ev:
            state.evaluation = StageEvaluationVerdict(
                verdict=Verdict(ev["verdict"]),
                checks=list(ev.get("checks") or []),
                failures=list(ev.get("failures") or []),
                test_summary=ev.get("test_summary"),
                evaluated_at=ev.get("evaluated_at", ""),
            )
        rv = snapshot.get("review")
        if rv:
            state.review = ReviewGateResult(
                verdict=ReviewVerdict(rv["verdict"]),
                review_id=rv.get("review_id", ""),
                findings=list(rv.get("findings") or []),
                reviewed_at=rv.get("reviewed_at", ""),
            )
        h = snapshot.get("hitl")
        if h:
            state.hitl = HITLGateRecord(**h)
        dep = snapshot.get("deployment")
        if dep:
            state.deployment = DeploymentResult(
                status=DeploymentStatus(dep["status"]),
                target=dep.get("target", ""),
                detail=dep.get("detail", ""),
                deployed_at=dep.get("deployed_at", ""),
            )
        return state

@dataclass
class HITLGateRecord:
    """Persisted human-approval gate record (actor/timestamp/decision/reason)."""

    gate_id: str
    stage_id: str
    workflow_id: str
    project_id: str
    reason: str
    risk_level: str = "medium"
    requested_at: str = field(default_factory=lambda: _iso(_utc_now()) or "")
    status: str = "pending"  # pending | approved | rejected | cancelled
    actor: str = ""
    decided_at: str | None = None
    decision: str = ""  # approve | reject
    reason_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "stage_id": self.stage_id,
            "workflow_id": self.workflow_id,
            "project_id": self.project_id,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "requested_at": self.requested_at,
            "status": self.status,
            "actor": self.actor,
            "decided_at": self.decided_at,
            "decision": self.decision,
            "reason_text": self.reason_text,
        }


@dataclass
class DeploymentResult:
    """Truthful deployment stage outcome."""

    status: DeploymentStatus
    target: str = ""
    detail: str = ""
    deployed_at: str = field(default_factory=lambda: _iso(_utc_now()) or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "target": self.target,
            "detail": self.detail,
            "deployed_at": self.deployed_at,
        }


@dataclass
class WorkerContract:
    """The complete structured contract for a worker invocation."""

    input: WorkerContractInput
    output: WorkerContractOutput | None = None
    routed_model: ModelDecision | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input.to_dict(),
            "output": self.output.to_dict() if self.output else None,
            "routed_model": self.routed_model.to_dict() if self.routed_model else None,
        }


@dataclass
class ProjectExecutionState:
    """Durable project execution state (section 4).

    Survives process restart via ``to_snapshot`` / ``from_snapshot``.
    """

    project_id: str
    workflow_id: str
    workflow_name: str
    mode: RunMode
    execution_id: str
    status: WorkflowStatus = WorkflowStatus.CREATED
    objective: str = ""
    stages: dict[str, StageExecutionState] = field(default_factory=dict)
    stage_order: list[str] = field(default_factory=list)
    metrics: ProjectExecutionMetrics = field(default_factory=ProjectExecutionMetrics)
    hitl_gates: dict[str, HITLGateRecord] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    telemetry_refs: list[dict[str, Any]] = field(default_factory=list)
    cancellation: dict[str, Any] | None = None
    workspace_root: str = ""
    created_at: str = field(default_factory=lambda: _iso(_utc_now()) or "")
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = _iso(_utc_now())

    def record_telemetry(self, ref: dict[str, Any]) -> None:
        self.telemetry_refs.append(ref)

    def register_artifact(self, artifact: dict[str, Any]) -> None:
        # Idempotency: never register the same artifact twice.
        key = artifact.get("artifact_id") or artifact.get("path")
        for existing in self.artifacts:
            if key and (existing.get("artifact_id") == key or existing.get("path") == key):
                return
        self.artifacts.append(artifact)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "mode": self.mode.value,
            "execution_id": self.execution_id,
            "status": self.status.value,
            "objective": self.objective,
            "stages": {sid: s.to_snapshot() for sid, s in self.stages.items()},
            "stage_order": list(self.stage_order),
            "metrics": self.metrics.to_dict(),
            "hitl_gates": {gid: g.to_dict() for gid, g in self.hitl_gates.items()},
            "artifacts": list(self.artifacts),
            "telemetry_refs": list(self.telemetry_refs),
            "cancellation": dict(self.cancellation) if self.cancellation else None,
            "workspace_root": self.workspace_root,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "ProjectExecutionState":
        state = cls(
            project_id=snapshot["project_id"],
            workflow_id=snapshot["workflow_id"],
            workflow_name=snapshot["workflow_name"],
            mode=RunMode(snapshot["mode"]),
            execution_id=snapshot["execution_id"],
            status=WorkflowStatus(snapshot["status"]),
            objective=snapshot.get("objective", ""),
            stage_order=list(snapshot.get("stage_order") or []),
            metrics=ProjectExecutionMetrics.from_dict(snapshot.get("metrics") or {}),
            artifacts=list(snapshot.get("artifacts") or []),
            telemetry_refs=list(snapshot.get("telemetry_refs") or []),
            cancellation=dict(snapshot["cancellation"]) if snapshot.get("cancellation") else None,
            workspace_root=snapshot.get("workspace_root", ""),
            created_at=snapshot.get("created_at", ""),
            started_at=snapshot.get("started_at"),
            updated_at=snapshot.get("updated_at"),
            completed_at=snapshot.get("completed_at"),
            meta=dict(snapshot.get("meta") or {}),
        )
        for sid, stage_snap in (snapshot.get("stages") or {}).items():
            state.stages[sid] = StageExecutionState.from_snapshot(stage_snap)
        for gid, gate_snap in (snapshot.get("hitl_gates") or {}).items():
            state.hitl_gates[gid] = HITLGateRecord(**gate_snap)
        return state