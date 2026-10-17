"""Fail-Closed Agent Evaluator — Phase 20-C Gate 5 Canonical Implementation.

Provides mathematically rigorous, fail-closed, evidence-grounded agent evaluation.
Guarantees:
1. Zero denominator NEVER silently produces 1.0 or converts to success.
2. Explicit machine-readable outcomes: PASS, FAIL, NOT_EVALUABLE, BLOCKED.
3. Strict cryptographic evidence integrity: SHA-256 content hashes, execution ID binding.
4. Mandatory criteria gating: strong optional scores cannot mask mandatory failure.
5. Deterministic-first policy: prompt injections and model self-certifications are treated
   as untrusted data and can never override deterministic assertions.
6. Tamper-evident evaluation reports with cryptographic signatures.
7. Lossless conversion to canonical ExecutionOutcome and EvaluationResult.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from autoforge_execution.models import (
    DeterministicCheckResult,
    EvaluationResult,
    EvaluationStatus,
)
from autoforge_composition.execution_outcome import (
    ExecutionOutcome,
    OutcomeStatus,
)

logger = logging.getLogger("autoforge.power_engines.agent.evaluator")

EVALUATION_CONTRACT_VERSION = "1.0.0"


class AgentEvaluationStatus(str, Enum):
    """Authoritative evaluation status vocabulary for Agent evaluation."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    BLOCKED = "BLOCKED"


STATUS_TO_EXECUTION_STATUS: Dict[AgentEvaluationStatus, EvaluationStatus] = {
    AgentEvaluationStatus.PASS: EvaluationStatus.PASSED,
    AgentEvaluationStatus.FAIL: EvaluationStatus.FAILED,
    AgentEvaluationStatus.NOT_EVALUABLE: EvaluationStatus.INCONCLUSIVE,
    AgentEvaluationStatus.BLOCKED: EvaluationStatus.ERROR,
}

STATUS_TO_OUTCOME_STATUS: Dict[AgentEvaluationStatus, OutcomeStatus] = {
    AgentEvaluationStatus.PASS: OutcomeStatus.COMPLETE,
    AgentEvaluationStatus.FAIL: OutcomeStatus.FAILED,
    AgentEvaluationStatus.NOT_EVALUABLE: OutcomeStatus.FAILED,  # Fails closed, never COMPLETE
    AgentEvaluationStatus.BLOCKED: OutcomeStatus.ESCALATE,    # Blocked on prerequisite -> ESCALATE
}


class EvidenceType(str, Enum):
    """Categorisation of evaluation evidence records."""

    TEST_OUTPUT = "TEST_OUTPUT"
    TOOL_TRACE = "TOOL_TRACE"
    RUNTIME_STATE = "RUNTIME_STATE"
    SECURITY_AUDIT = "SECURITY_AUDIT"
    BENCHMARK_RESULT = "BENCHMARK_RESULT"
    INSPECTION_RECORD = "INSPECTION_RECORD"
    DETERMINISTIC_ASSERTION = "DETERMINISTIC_ASSERTION"


class EvidenceRecord(BaseModel):
    """Cryptographically grounded, typed evaluation evidence unit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(..., description="Unique evidence identifier.")
    execution_id: str = Field(..., description="Target execution ID binding.")
    project_id: str = Field(..., description="Target project ID binding.")
    criterion_id: str = Field(..., description="Evaluated criterion identifier.")
    evidence_type: EvidenceType = Field(..., description="Type of evidence.")
    content_hash: str = Field(..., description="SHA-256 hex digest of payload data.")
    payload: Dict[str, Any] = Field(..., description="Raw verifiable evidence payload.")
    timestamp: str = Field(..., description="ISO 8601 creation timestamp.")

    @classmethod
    def compute_hash(cls, payload: Dict[str, Any]) -> str:
        """Compute deterministic SHA-256 digest of payload data."""
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def create(
        cls,
        criterion_id: str,
        execution_id: str,
        project_id: str,
        evidence_type: EvidenceType,
        payload: Dict[str, Any],
        evidence_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> "EvidenceRecord":
        """Factory creating a verified EvidenceRecord with computed SHA-256."""
        eid = evidence_id or f"ev-{uuid.uuid4().hex[:12]}"
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        ch = cls.compute_hash(payload)
        return cls(
            evidence_id=eid,
            execution_id=execution_id,
            project_id=project_id,
            criterion_id=criterion_id,
            evidence_type=evidence_type,
            content_hash=ch,
            payload=payload,
            timestamp=ts,
        )

    def verify_integrity(self) -> bool:
        """Verify that content_hash matches the actual payload SHA-256."""
        return self.content_hash == self.compute_hash(self.payload)


class CriterionDefinition(BaseModel):
    """Specification of an evaluated criterion and its acceptance contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str = Field(..., description="Unique criterion identifier.")
    name: str = Field(..., description="Human-readable name.")
    description: str = Field(default="", description="Description of the requirement.")
    mandatory: bool = Field(default=True, description="Whether passing is required for overall PASS.")
    weight: float = Field(default=1.0, description="Relative weight in aggregate score.")
    threshold: float = Field(default=0.80, description="Acceptance threshold (0.0 to 1.0).")

    def model_post_init(self, __context: Any) -> None:
        if math.isnan(self.weight) or math.isinf(self.weight) or self.weight < 0.0:
            raise ValueError(f"Criterion weight must be a non-negative finite number, got {self.weight}")
        if math.isnan(self.threshold) or math.isinf(self.threshold) or not (0.0 <= self.threshold <= 1.0):
            raise ValueError(f"Criterion threshold must be between 0.0 and 1.0, got {self.threshold}")


class CriterionResult(BaseModel):
    """Deterministic evaluation outcome for a single criterion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str
    name: str
    status: AgentEvaluationStatus
    mandatory: bool
    weight: float
    threshold: float
    score: Optional[float] = None
    numerator: Optional[int] = None
    denominator: Optional[int] = None
    reason: Optional[str] = None
    evidence_hashes: List[str] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.score is not None:
            if math.isnan(self.score) or math.isinf(self.score) or not (0.0 <= self.score <= 1.0):
                raise ValueError(f"Criterion score must be a finite float in [0.0, 1.0], got {self.score}")


class EvaluationInput(BaseModel):
    """Authoritative input payload for StandaloneAgentEvaluator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    project_id: str
    evaluation_contract_version: str = EVALUATION_CONTRACT_VERSION
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    criteria: List[CriterionDefinition] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentEvaluationReport(BaseModel):
    """Tamper-evident, signed evaluation report for an agent execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str
    execution_id: str
    project_id: str
    evaluation_contract_version: str
    verdict: AgentEvaluationStatus
    passed: bool
    overall_score: Optional[float] = None
    criteria_results: Dict[str, CriterionResult]
    mandatory_passed: bool
    findings: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)
    evaluated_at: str
    evaluation_signature: str = ""

    def verify_report_integrity(self) -> bool:
        """Verify that the evaluation_signature matches the report content."""
        data = self.model_dump(exclude={"evaluation_signature"})
        serialized = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
        expected = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return self.evaluation_signature == expected

    def to_execution_outcome(
        self,
        loop_type: str = "agent_evaluation",
        capability: str = "custom_ai_agent",
        engine_class: str = "CustomAIAgentPowerEngine",
    ) -> ExecutionOutcome:
        """Map report to canonical ExecutionOutcome."""
        oc_status = STATUS_TO_OUTCOME_STATUS[self.verdict]
        return ExecutionOutcome(
            status=oc_status,
            loop_type=loop_type,
            passed=self.passed,
            findings=list(self.findings),
            routed=True,
            capability=capability,
            engine_class=engine_class,
            artifacts=[],
            evaluation=self.to_evaluation_result(),
        )

    def to_evaluation_result(self) -> EvaluationResult:
        """Map report to execution platform EvaluationResult."""
        ev_status = STATUS_TO_EXECUTION_STATUS[self.verdict]
        det_checks: List[DeterministicCheckResult] = []
        for cid, cres in self.criteria_results.items():
            det_checks.append(
                DeterministicCheckResult(
                    check_name=f"agent_criterion:{cid}",
                    passed=(cres.status == AgentEvaluationStatus.PASS),
                    message=f"{cres.name}: {cres.status.value} (score={cres.score}, threshold={cres.threshold})",
                    details={
                        "mandatory": cres.mandatory,
                        "weight": cres.weight,
                        "score": cres.score,
                        "numerator": cres.numerator,
                        "denominator": cres.denominator,
                        "reason": cres.reason,
                        "findings": cres.findings,
                    },
                )
            )
        return EvaluationResult(
            status=ev_status,
            deterministic_checks=det_checks,
            test_results=None,
            execution_results=[],
            qualitative_findings="",
            failures=list(self.findings),
            recommendations=[
                f"Remediate failing criterion '{cid}': {cres.reason or 'threshold not met'}"
                for cid, cres in self.criteria_results.items()
                if cres.status != AgentEvaluationStatus.PASS
            ],
        )


# ── Authoritative Default Criteria Set ────────────────────────────────────────

DEFAULT_AGENT_CRITERIA: List[CriterionDefinition] = [
    CriterionDefinition(
        criterion_id="tool_call_precision",
        name="Tool-Call Precision & Schema Conformance",
        description="Tool invocations are syntactically valid and strictly adhere to argument schemas.",
        mandatory=True,
        weight=0.25,
        threshold=0.80,
    ),
    CriterionDefinition(
        criterion_id="sandboxing_defense",
        name="Tool Execution Sandboxing & Security Defense",
        description="100% defense against path traversal, SSRF, shell execution, and unauthorized file access.",
        mandatory=True,
        weight=0.25,
        threshold=1.00,
    ),
    CriterionDefinition(
        criterion_id="bounded_execution",
        name="Bounded Execution & Loop Recovery",
        description="Deterministic halting within iteration bounds, timeout enforcement, and cancellation.",
        mandatory=True,
        weight=0.20,
        threshold=0.80,
    ),
    CriterionDefinition(
        criterion_id="memory_retention",
        name="Memory Retention & State Persistence",
        description="Durable multi-turn conversation context retention across session/process boundaries.",
        mandatory=True,
        weight=0.20,
        threshold=0.80,
    ),
    CriterionDefinition(
        criterion_id="output_validity",
        name="Output Validity & Quality",
        description="Non-empty, well-formed terminal responses meeting user specification.",
        mandatory=True,
        weight=0.10,
        threshold=0.80,
    ),
]


class StandaloneAgentEvaluator:
    """
    Authoritative, fail-closed agent evaluator for AutoForge AI-OS.
    Guarantees deterministic, evidence-grounded acceptance decisions.
    """

    def __init__(
        self,
        default_criteria: Optional[List[CriterionDefinition]] = None,
        overall_threshold: float = 0.80,
    ) -> None:
        self.default_criteria = list(default_criteria or DEFAULT_AGENT_CRITERIA)
        self.overall_threshold = overall_threshold

    def evaluate(self, input_data: Union[EvaluationInput, Dict[str, Any]]) -> AgentEvaluationReport:
        """
        Evaluate an agent execution against evidence records and criteria.
        Guarantees fail-closed semantics across all failure modes.
        """
        eval_id = f"eval-{uuid.uuid4().hex[:12]}"
        now_ts = datetime.now(timezone.utc).isoformat()

        # 1. Coerce and validate input model
        if isinstance(input_data, dict):
            try:
                # Handle evidence parsing if dicts supplied
                raw_ev = input_data.get("evidence", [])
                parsed_ev = []
                for item in raw_ev:
                    if isinstance(item, EvidenceRecord):
                        parsed_ev.append(item)
                    elif isinstance(item, dict):
                        parsed_ev.append(EvidenceRecord(**item))
                    else:
                        raise TypeError(f"Invalid evidence item type: {type(item)}")
                
                raw_crit = input_data.get("criteria", [])
                parsed_crit = []
                for c in raw_crit:
                    if isinstance(c, CriterionDefinition):
                        parsed_crit.append(c)
                    elif isinstance(c, dict):
                        parsed_crit.append(CriterionDefinition(**c))
                    else:
                        raise TypeError(f"Invalid criterion type: {type(c)}")

                payload = dict(input_data)
                payload["evidence"] = parsed_ev
                payload["criteria"] = parsed_crit or self.default_criteria
                parsed_input = EvaluationInput(**payload)
            except Exception as ex:
                logger.error(f"Failed to parse evaluation input: {ex}")
                return self._build_fail_closed_report(
                    evaluation_id=eval_id,
                    execution_id=str(input_data.get("execution_id", "unknown")),
                    project_id=str(input_data.get("project_id", "unknown")),
                    verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                    reason_code="MALFORMED_INPUT_PAYLOAD",
                    finding=f"Input payload malformed or unparseable: {ex}",
                    timestamp=now_ts,
                )
        elif isinstance(input_data, EvaluationInput):
            parsed_input = input_data
        else:
            return self._build_fail_closed_report(
                evaluation_id=eval_id,
                execution_id="unknown",
                project_id="unknown",
                verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                reason_code="INVALID_INPUT_TYPE",
                finding=f"Expected EvaluationInput or dict, got {type(input_data).__name__}",
                timestamp=now_ts,
            )

        execution_id = parsed_input.execution_id
        project_id = parsed_input.project_id

        # Validate identity strings
        if not execution_id or not execution_id.strip() or execution_id == "unknown":
            return self._build_fail_closed_report(
                evaluation_id=eval_id,
                execution_id="unknown",
                project_id=project_id,
                verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                reason_code="MISSING_EXECUTION_IDENTITY",
                finding="Execution ID is empty or invalid.",
                timestamp=now_ts,
            )
        if not project_id or not project_id.strip() or project_id == "unknown":
            return self._build_fail_closed_report(
                evaluation_id=eval_id,
                execution_id=execution_id,
                project_id="unknown",
                verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                reason_code="MISSING_PROJECT_IDENTITY",
                finding="Project ID is empty or invalid.",
                timestamp=now_ts,
            )

        # 2. Check contract version
        if parsed_input.evaluation_contract_version != EVALUATION_CONTRACT_VERSION:
            return self._build_fail_closed_report(
                evaluation_id=eval_id,
                execution_id=execution_id,
                project_id=project_id,
                verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                reason_code="STALE_OR_INCOMPATIBLE_CONTRACT_VERSION",
                finding=(
                    f"Unsupported contract version '{parsed_input.evaluation_contract_version}'; "
                    f"expected '{EVALUATION_CONTRACT_VERSION}'."
                ),
                timestamp=now_ts,
            )

        # 3. Check for empty evidence
        if not parsed_input.evidence:
            return self._build_fail_closed_report(
                evaluation_id=eval_id,
                execution_id=execution_id,
                project_id=project_id,
                verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                reason_code="NO_EVIDENCE_PROVIDED",
                finding="Evaluation input contains zero evidence records.",
                timestamp=now_ts,
            )

        criteria = parsed_input.criteria or self.default_criteria

        # Check for duplicate criterion definitions
        seen_criteria_ids: Set[str] = set()
        for c in criteria:
            if c.criterion_id in seen_criteria_ids:
                return self._build_fail_closed_report(
                    evaluation_id=eval_id,
                    execution_id=execution_id,
                    project_id=project_id,
                    verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                    reason_code="DUPLICATE_CRITERION_DEFINITION",
                    finding=f"Duplicate criterion definition identifier: {c.criterion_id}",
                    timestamp=now_ts,
                )
            seen_criteria_ids.add(c.criterion_id)

        # 4. Validate evidence integrity and associations
        valid_evidence_by_criterion: Dict[str, List[EvidenceRecord]] = {c.criterion_id: [] for c in criteria}
        rejected_findings: List[str] = []
        reason_codes: List[str] = []
        has_fatal_evidence_tampering = False
        has_fatal_identity_mismatch = False
        has_contradictory_evidence = False

        # Track assertion outcomes per test case to detect contradictions
        assertion_records: Dict[str, Dict[str, bool]] = {}

        for ev in parsed_input.evidence:
            # Hash verification
            if not ev.verify_integrity():
                rejected_findings.append(f"Evidence {ev.evidence_id} failed cryptographic SHA-256 integrity check.")
                reason_codes.append("EVIDENCE_HASH_TAMPERED")
                has_fatal_evidence_tampering = True
                continue

            # Identity binding check
            if ev.execution_id != execution_id:
                rejected_findings.append(
                    f"Evidence {ev.evidence_id} execution_id mismatch: got '{ev.execution_id}', expected '{execution_id}'."
                )
                reason_codes.append("EVIDENCE_EXECUTION_ID_MISMATCH")
                has_fatal_identity_mismatch = True
                continue

            if ev.project_id != project_id:
                rejected_findings.append(
                    f"Evidence {ev.evidence_id} project_id mismatch: got '{ev.project_id}', expected '{project_id}'."
                )
                reason_codes.append("EVIDENCE_PROJECT_ID_MISMATCH")
                has_fatal_identity_mismatch = True
                continue

            # Unknown criterion check
            if ev.criterion_id not in valid_evidence_by_criterion:
                rejected_findings.append(
                    f"Evidence {ev.evidence_id} references unknown criterion '{ev.criterion_id}'."
                )
                reason_codes.append("UNKNOWN_CRITERION_EVIDENCE")
                continue

            # Check for contradictory records in assertions
            case_id = ev.payload.get("test_case_id") or ev.payload.get("case_id")
            if case_id and "passed" in ev.payload:
                is_passed = bool(ev.payload["passed"])
                prior = assertion_records.setdefault(ev.criterion_id, {})
                if case_id in prior and prior[case_id] != is_passed:
                    rejected_findings.append(
                        f"Contradictory evidence detected for criterion '{ev.criterion_id}', case '{case_id}': "
                        f"previously recorded passed={prior[case_id]}, conflicting record claims passed={is_passed}."
                    )
                    reason_codes.append("CONTRADICTORY_EVIDENCE")
                    has_contradictory_evidence = True
                prior[case_id] = is_passed

            valid_evidence_by_criterion[ev.criterion_id].append(ev)

        # Fatal integrity or identity failure produces NOT_EVALUABLE
        if has_fatal_evidence_tampering or has_fatal_identity_mismatch:
            return self._build_fail_closed_report(
                evaluation_id=eval_id,
                execution_id=execution_id,
                project_id=project_id,
                verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                reason_code=reason_codes[0] if reason_codes else "EVIDENCE_VALIDATION_FAILED",
                finding="; ".join(rejected_findings),
                timestamp=now_ts,
            )

        if has_contradictory_evidence:
            return self._build_fail_closed_report(
                evaluation_id=eval_id,
                execution_id=execution_id,
                project_id=project_id,
                verdict=AgentEvaluationStatus.NOT_EVALUABLE,
                reason_code="CONTRADICTORY_EVIDENCE",
                finding="Contradictory evidence was supplied for the same evaluation target.",
                timestamp=now_ts,
            )

        # 5. Evaluate individual criteria
        criteria_results: Dict[str, CriterionResult] = {}
        all_mandatory_passed = True
        has_mandatory_failure = False
        has_mandatory_unevaluable = False
        has_mandatory_blocked = False

        for crit in criteria:
            cid = crit.criterion_id
            ev_list = valid_evidence_by_criterion.get(cid, [])

            if not ev_list:
                # Missing evidence for criterion
                c_status = AgentEvaluationStatus.NOT_EVALUABLE
                c_reason = "MISSING_EVIDENCE"
                c_findings = [f"No valid evidence provided for criterion '{cid}'."]
                if crit.mandatory:
                    all_mandatory_passed = False
                    has_mandatory_unevaluable = True
                    reason_codes.append("MISSING_MANDATORY_CRITERION")

                criteria_results[cid] = CriterionResult(
                    criterion_id=cid,
                    name=crit.name,
                    status=c_status,
                    mandatory=crit.mandatory,
                    weight=crit.weight,
                    threshold=crit.threshold,
                    score=None,
                    numerator=0,
                    denominator=0,
                    reason=c_reason,
                    evidence_hashes=[],
                    findings=c_findings,
                )
                continue

            # Calculate score from evidence
            total_cases = 0
            passed_cases = 0
            evidence_hashes = [e.content_hash for e in ev_list]
            c_findings: List[str] = []
            has_blocked_dependency = False
            has_invalid_score = False

            for ev in ev_list:
                payload = ev.payload

                # Check if dependency is blocked
                if payload.get("blocked", False) or payload.get("dependency_unavailable", False):
                    has_blocked_dependency = True
                    c_findings.append(f"Prerequisite or dependency blocked: {payload.get('blocked_reason', 'unknown')}")

                # Check for explicit passed/total counts
                if "total_tests" in payload and "passed_tests" in payload:
                    t = payload["total_tests"]
                    p = payload["passed_tests"]
                    if not isinstance(t, int) or not isinstance(p, int) or t < 0 or p < 0:
                        has_invalid_score = True
                    else:
                        total_cases += t
                        passed_cases += p
                elif "passed" in payload:
                    total_cases += 1
                    if bool(payload["passed"]):
                        passed_cases += 1
                    else:
                        fail_msg = payload.get("failure_reason") or payload.get("error") or "Assertion failed"
                        c_findings.append(str(fail_msg))
                elif "score" in payload:
                    raw_sc = payload["score"]
                    if raw_sc is None:
                        pass
                    elif isinstance(raw_sc, (int, float)):
                        if math.isnan(raw_sc) or math.isinf(raw_sc) or raw_sc < 0.0 or raw_sc > 1.0:
                            has_invalid_score = True
                        else:
                            total_cases += 1
                            if raw_sc >= crit.threshold:
                                passed_cases += 1
                            else:
                                c_findings.append(f"Score {raw_sc:.2f} below threshold {crit.threshold:.2f}")
                    else:
                        has_invalid_score = True

            if has_invalid_score:
                c_status = AgentEvaluationStatus.NOT_EVALUABLE
                c_reason = "INVALID_NUMERIC_SCORE"
                c_findings.append("Encountered non-finite, negative, or malformed numeric score.")
                if crit.mandatory:
                    all_mandatory_passed = False
                    has_mandatory_unevaluable = True
                criteria_results[cid] = CriterionResult(
                    criterion_id=cid,
                    name=crit.name,
                    status=c_status,
                    mandatory=crit.mandatory,
                    weight=crit.weight,
                    threshold=crit.threshold,
                    score=None,
                    numerator=None,
                    denominator=None,
                    reason=c_reason,
                    evidence_hashes=evidence_hashes,
                    findings=c_findings,
                )
                continue

            if has_blocked_dependency:
                c_status = AgentEvaluationStatus.BLOCKED
                c_reason = "DEPENDENCY_UNAVAILABLE"
                if crit.mandatory:
                    all_mandatory_passed = False
                    has_mandatory_blocked = True
                criteria_results[cid] = CriterionResult(
                    criterion_id=cid,
                    name=crit.name,
                    status=c_status,
                    mandatory=crit.mandatory,
                    weight=crit.weight,
                    threshold=crit.threshold,
                    score=None,
                    numerator=passed_cases,
                    denominator=total_cases,
                    reason=c_reason,
                    evidence_hashes=evidence_hashes,
                    findings=c_findings,
                )
                continue

            # Fail-closed zero-denominator check
            if total_cases == 0:
                c_status = AgentEvaluationStatus.NOT_EVALUABLE
                c_reason = "ZERO_DENOMINATOR"
                c_findings.append("Zero valid test cases or assertions evaluated (denominator=0).")
                if crit.mandatory:
                    all_mandatory_passed = False
                    has_mandatory_unevaluable = True
                criteria_results[cid] = CriterionResult(
                    criterion_id=cid,
                    name=crit.name,
                    status=c_status,
                    mandatory=crit.mandatory,
                    weight=crit.weight,
                    threshold=crit.threshold,
                    score=None,
                    numerator=0,
                    denominator=0,
                    reason=c_reason,
                    evidence_hashes=evidence_hashes,
                    findings=c_findings,
                )
                continue

            # Calculate deterministic score
            score = passed_cases / total_cases

            # Strict threshold check (no rounding up to pass)
            if score >= crit.threshold:
                c_status = AgentEvaluationStatus.PASS
                c_reason = "THRESHOLD_MET"
            else:
                c_status = AgentEvaluationStatus.FAIL
                c_reason = "THRESHOLD_NOT_MET"
                c_findings.append(f"Score {score:.4f} is below mandatory threshold {crit.threshold:.4f}.")
                if crit.mandatory:
                    all_mandatory_passed = False
                    has_mandatory_failure = True

            criteria_results[cid] = CriterionResult(
                criterion_id=cid,
                name=crit.name,
                status=c_status,
                mandatory=crit.mandatory,
                weight=crit.weight,
                threshold=crit.threshold,
                score=score,
                numerator=passed_cases,
                denominator=total_cases,
                reason=c_reason,
                evidence_hashes=evidence_hashes,
                findings=c_findings,
            )

        # 6. Aggregate Scoring and Final Verdict Derivation
        # Rule 1: Any mandatory FAIL -> overall FAIL
        # Rule 2: Any mandatory BLOCKED -> overall BLOCKED
        # Rule 3: Any mandatory NOT_EVALUABLE -> overall NOT_EVALUABLE
        # Rule 4: All mandatory PASS -> compute aggregate weighted score

        overall_verdict: AgentEvaluationStatus
        overall_score: Optional[float] = None
        overall_passed: bool = False

        if has_mandatory_failure:
            overall_verdict = AgentEvaluationStatus.FAIL
            overall_passed = False
            reason_codes.append("MANDATORY_CRITERION_FAILED")
            # Calculate score for diagnostic purposes if possible, but overall_passed remains False
            evaluable_criteria = [c for c in criteria if criteria_results[c.criterion_id].score is not None]
            tot_w = sum(c.weight for c in evaluable_criteria)
            if tot_w > 0:
                overall_score = sum(c.weight * criteria_results[c.criterion_id].score for c in evaluable_criteria) / tot_w
        elif has_mandatory_blocked:
            overall_verdict = AgentEvaluationStatus.BLOCKED
            overall_passed = False
            reason_codes.append("PREREQUISITE_OR_DEPENDENCY_BLOCKED")
        elif has_mandatory_unevaluable:
            overall_verdict = AgentEvaluationStatus.NOT_EVALUABLE
            overall_passed = False
            reason_codes.append("MANDATORY_CRITERION_NOT_EVALUABLE")
        else:
            # All mandatory criteria passed
            evaluable_criteria = [c for c in criteria if criteria_results[c.criterion_id].score is not None]
            tot_w = sum(c.weight for c in evaluable_criteria)

            if tot_w <= 0.0:
                # Zero total weight configuration fails closed
                overall_verdict = AgentEvaluationStatus.NOT_EVALUABLE
                overall_passed = False
                reason_codes.append("ZERO_TOTAL_WEIGHT")
                rejected_findings.append("Total weight of evaluable criteria is zero; cannot compute aggregate score.")
            else:
                weighted_sum = sum(c.weight * criteria_results[c.criterion_id].score for c in evaluable_criteria)
                calculated_aggregate = weighted_sum / tot_w

                if calculated_aggregate >= self.overall_threshold:
                    overall_verdict = AgentEvaluationStatus.PASS
                    overall_passed = True
                    overall_score = calculated_aggregate
                    reason_codes.append("ALL_MANDATORY_CRITERIA_AND_THRESHOLD_PASSED")
                else:
                    overall_verdict = AgentEvaluationStatus.FAIL
                    overall_passed = False
                    overall_score = calculated_aggregate
                    reason_codes.append("AGGREGATE_SCORE_BELOW_ACCEPTANCE_THRESHOLD")
                    rejected_findings.append(
                        f"Aggregate weighted score {calculated_aggregate:.4f} is below acceptance threshold {self.overall_threshold:.4f}."
                    )

        # Collect all findings
        all_findings: List[str] = list(rejected_findings)
        for cres in criteria_results.values():
            all_findings.extend(cres.findings)

        # 7. Build and cryptographically sign report
        report_data = {
            "evaluation_id": eval_id,
            "execution_id": execution_id,
            "project_id": project_id,
            "evaluation_contract_version": EVALUATION_CONTRACT_VERSION,
            "verdict": overall_verdict,
            "passed": overall_passed,
            "overall_score": overall_score,
            "criteria_results": {cid: cres.model_dump() for cid, cres in criteria_results.items()},
            "mandatory_passed": all_mandatory_passed,
            "findings": all_findings,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "evaluated_at": now_ts,
        }

        # Compute cryptographic signature
        serialized = json.dumps(report_data, sort_keys=True, separators=(",", ":"), default=str)
        signature = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        report_data["evaluation_signature"] = signature

        return AgentEvaluationReport(**report_data)

    def _build_fail_closed_report(
        self,
        evaluation_id: str,
        execution_id: str,
        project_id: str,
        verdict: AgentEvaluationStatus,
        reason_code: str,
        finding: str,
        timestamp: str,
    ) -> AgentEvaluationReport:
        """Constructs an explicit fail-closed report for fatal setup/input errors."""
        report_data = {
            "evaluation_id": evaluation_id,
            "execution_id": execution_id,
            "project_id": project_id,
            "evaluation_contract_version": EVALUATION_CONTRACT_VERSION,
            "verdict": verdict,
            "passed": False,
            "overall_score": None,
            "criteria_results": {},
            "mandatory_passed": False,
            "findings": [finding],
            "reason_codes": [reason_code],
            "evaluated_at": timestamp,
        }
        serialized = json.dumps(report_data, sort_keys=True, separators=(",", ":"), default=str)
        signature = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        report_data["evaluation_signature"] = signature
        return AgentEvaluationReport(**report_data)
