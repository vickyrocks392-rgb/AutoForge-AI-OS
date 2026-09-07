"""Transformation execution orchestrator (Phase 18 post-G.3)."""
from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, Field

from autoforge_modernization.capacity_scheduler import (
    CapacityScheduler,
    ScheduledTask,
)
from autoforge_modernization.llm_transformation import (
    LLMInferenceFrontend,
    LLMTransformationContract,
    LLMTransformationEngine,
    LLMTransformationStatus,
    build_ollama_inference_stack,
)
from autoforge_modernization.modernization_estimator import (
    ModernizationEstimator,
)
from autoforge_modernization.repair_cycle import (
    BoundedRepairCycle,
    RepairOutcome,
    RepairStatus,
)
from autoforge_modernization.target_technology import (
    TargetTechnologyRegistry,
)
from autoforge_modernization.telemetry import (
    TelemetryEventType,
    TelemetryRecorder,
)
from autoforge_modernization.throughput_accounting import (
    ThroughputAccounting,
    UnitKind,
)
from autoforge_modernization.transformation_context import (
    SemanticModelSnapshot,
    TransformationContextAssembler,
    TransformationInputs,
    TransformationPrompt,
)
from autoforge_modernization.verification import GeneratedCodeVerifier

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

class TransformationUnit(BaseModel):
    unit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_technology: str = ""
    source_artifacts: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    source_text: str = ""
    source_technology: str = ""
    source_sha256: str = Field(
        default_factory=lambda: hashlib.sha256(b"placeholder").hexdigest()
    )
    # Semantic snapshot produced by LegacyAnalysisEngine via AnalyzerDispatcher.
    # Populated by BenchmarkRunner.arun() before the unit is submitted for transformation.
    # May be None for units where analysis was unavailable or skipped.
    semantic_snapshot: "SemanticModelSnapshot | None" = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    session_id: str = ""
    total_units: int = 0
    completed_units: int = 0
    failed_units: int = 0
    skipped_units: int = 0
    unavailable_units: int = 0
    repaired_units: int = 0
    total_latency_ms: float = 0.0
    ledger: list[Any] = Field(default_factory=list)
    repair_outcomes: list[Any] = Field(default_factory=list)
    telemetry_summary: dict[str, int] = Field(default_factory=dict)


class TransformationExecutor:
    """End-to-end orchestrator for all Phase-18 components."""

    def __init__(
        self,
        *,
        session_id: str = "",
        max_concurrent: int = 4,
        per_tech_concurrency: dict[str, int] | None = None,
        inference: Any = None,
        rag_evidence_fn: Callable[..., list[Any]] | None = None,
        run_compile_checks: bool = True,
        run_static_checks: bool = True,
        repair_max_attempts: int = 3,
        repair_timeout_seconds: float = 120.0,
        governance_max_repair_attempts: int | None = None,
    ) -> None:
        self._session_id = session_id or str(uuid.uuid4())
        self._scheduler = CapacityScheduler(
            max_concurrent=max_concurrent,
            per_tech_concurrency=per_tech_concurrency,
        )
        self._verifier = GeneratedCodeVerifier(
            run_compile_checks=run_compile_checks,
            run_static_checks=run_static_checks,
        )
        if inference is None:
            if os.environ.get("AUTOFORGE_LLM_AVAILABLE") == "0":
                inference = None
            else:
                try:
                    stack = build_ollama_inference_stack()
                    inference = LLMInferenceFrontend(stack=stack)
                except Exception:  # noqa: BLE001
                    inference = None
        self._inference = inference
        self._rag_evidence_fn = rag_evidence_fn
        self._engine = LLMTransformationEngine(frontend=inference)
        self._assembler = TransformationContextAssembler()
        self._tech_registry = TargetTechnologyRegistry()
        self._repair = BoundedRepairCycle(
            inference=inference,
            verifier=self._verifier,
            rag_evidence_fn=rag_evidence_fn,
            max_attempts=repair_max_attempts,
            timeout_seconds=repair_timeout_seconds,
            governance_max_attempts=governance_max_repair_attempts,
        )
        self._throughput = ThroughputAccounting(session_id=self._session_id)
        self._estimator = ModernizationEstimator(session_id=self._session_id)
        self._telemetry = TelemetryRecorder(session_id=self._session_id)
        self._plan: list[TransformationUnit] = []
        self._completed = 0
        self._started_at: datetime | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    def add_unit(self, unit: TransformationUnit) -> None:
        self._plan.append(unit)
        self._scheduler.add_unit(
            unit_id=unit.unit_id,
            target_technology=unit.target_technology,
            depends_on=unit.depends_on,
        )

    def _make_prompt(
        self,
        unit: TransformationUnit,
        target_technology: str,
    ) -> TransformationPrompt:
        target_knowledge = self._tech_registry.get(target_technology)
        # Wire the pre-computed semantic snapshot from the unit (populated by
        # LegacyAnalysisEngine via AnalyzerDispatcher in BenchmarkRunner) into
        # TransformationInputs.  An empty snapshot is acceptable and means
        # the source had no detectable semantic constructs.
        snapshot = unit.semantic_snapshot or SemanticModelSnapshot()
        # Prefer the first source artifact path if present; fall back to metadata.
        source_path = ""
        if unit.source_artifacts:
            source_path = unit.source_artifacts[0]
        elif unit.metadata.get("source_path"):
            source_path = str(unit.metadata["source_path"])
        inputs = TransformationInputs(
            source_artifact_id=unit.unit_id,
            source_path=source_path,
            source_sha256=unit.source_sha256,
            source_technology=unit.source_technology or "unknown",
            source_text=unit.source_text,
            source_loc=int(unit.metadata.get("loc", 0) or 0),
            unit_id=unit.unit_id,
            project_id=unit.unit_id,
            semantic_snapshot=snapshot,
        )
        rag_evidence = None
        if self._rag_evidence_fn is not None:
            try:
                rag_evidence = self._rag_evidence_fn(
                    unit_id=unit.unit_id,
                    target_technology=target_technology,
                )
            except Exception:  # noqa: BLE001
                rag_evidence = None
        return self._assembler.assemble(
            inputs, target_knowledge, rag_evidence
        )

    async def execute(self) -> ExecutionResult:
        self._started_at = _utc_now()
        self._completed = 0
        self._scheduler.on_progress(self._on_unit_done)
        await self._scheduler.run_all(self._execute_one)
        return self._build_result()

    async def _execute_one(self, task: ScheduledTask) -> dict[str, Any]:
        unit = next(
            (u for u in self._plan if u.unit_id == task.unit_id), None
        )
        if unit is None:
            return {"error": f"unit {task.unit_id} not found in plan"}
        ti = self._tech_registry.get(unit.target_technology)
        tgt = ti.name if ti else unit.target_technology
        self._estimator.start_unit(unit.unit_id)
        self._telemetry.emit(
            TelemetryEventType.UNIT_STARTED, unit_id=unit.unit_id
        )
        prompt = self._make_prompt(unit, tgt)
        try:
            result: LLMTransformationContract = await self._engine.transform(
                prompt,
                source_artifact_id=unit.unit_id,
                source_sha256=unit.source_sha256,
                target_technology=tgt,
            )
        except Exception:  # noqa: BLE001
            self._throughput.record(
                unit_id=unit.unit_id,
                kind=UnitKind.UNAVAILABLE,
                target_technology=tgt,
            )
            self._telemetry.emit(
                TelemetryEventType.UNIT_UNAVAILABLE,
                unit_id=unit.unit_id,
            )
            return {"status": "unavailable"}
        unavailable = result.status == LLMTransformationStatus.UNAVAILABLE.value
        if unavailable:
            self._throughput.record(
                unit_id=unit.unit_id,
                kind=UnitKind.UNAVAILABLE,
                target_technology=tgt,
                llm_calls=0,
                model="",
                provider="",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0.0,
            )
            self._telemetry.emit(
                TelemetryEventType.UNIT_UNAVAILABLE,
                unit_id=unit.unit_id,
            )
            return {"status": "unavailable"}
        code = result.generated_code or ""
        vr = self._verifier.verify(
            artifact_id=unit.unit_id,
            code=code,
            target_technology=tgt,
        )
        ro: RepairOutcome | None = None
        if not vr.passed:
            self._telemetry.emit(
                TelemetryEventType.REPAIR_ATTEMPTED,
                unit_id=unit.unit_id,
            )
            rag_evidence = None
            if self._rag_evidence_fn is not None:
                try:
                    rag_evidence = self._rag_evidence_fn(
                        unit_id=unit.unit_id,
                        target_technology=tgt,
                    )
                except Exception:  # noqa: BLE001
                    rag_evidence = None
            ro = await self._repair.repair(
                unit_id=unit.unit_id,
                artifact_id=unit.unit_id,
                code=code,
                target_technology=tgt,
                failure_diagnostics=[d.message for d in vr.failures()],
                prompt_factory=lambda a, d, i: self._build_repair_prompt(
                    a, d, code, tgt
                ),
                rag_evidence=rag_evidence,
            )
            if ro.is_repaired():
                code = ro.final_code
                vr = self._verifier.verify(
                    artifact_id=unit.unit_id,
                    code=code,
                    target_technology=tgt,
                )
                self._telemetry.emit(
                    TelemetryEventType.REPAIR_COMPLETED,
                    unit_id=unit.unit_id,
                    payload={"attempts": len(ro.attempts)},
                )
            else:
                self._telemetry.emit(
                    TelemetryEventType.REPAIR_EXHAUSTED,
                    unit_id=unit.unit_id,
                    payload={
                        "status": ro.final_status.value,
                        "attempts": len(ro.attempts),
                    },
                )
        ph = sum(1 for m in ("TODO", "FIXME", "PLACEHOLDER") if m in code)
        wr = ro is not None and ro.is_repaired()
        if vr.passed:
            self._throughput.record(
                unit_id=unit.unit_id,
                kind=UnitKind.REPAIR if wr else UnitKind.PRODUCE,
                target_technology=tgt,
                source_file_count=len(unit.source_artifacts),
                output_file_count=1,
                placeholder_count=ph,
                generated_code_bytes=len(code.encode()),
                verification_passed=True,
                verification_report_id=vr.report_id,
                repair_outcome_id=ro.outcome_id if ro else "",
                llm_calls=1 if result.model else 0,
                rag_context_ids=list(result.rag_evidence_ids or []),
                latency_ms=result.latency_ms,
                model=result.model or "",
                provider=result.provider or "",
                prompt_tokens=result.token_usage_in,
                completion_tokens=result.token_usage_out,
            )
            self._telemetry.emit(
                TelemetryEventType.UNIT_COMPLETED,
                unit_id=unit.unit_id,
                payload={
                    "verification_passed": True,
                    "repaired": wr,
                    "latency_ms": result.latency_ms,
                },
            )
        else:
            self._throughput.record(
                unit_id=unit.unit_id,
                kind=UnitKind.FAILED,
                target_technology=tgt,
                source_file_count=len(unit.source_artifacts),
                placeholder_count=ph,
                verification_passed=False,
                verification_report_id=vr.report_id,
                error="verification failed after repair",
                llm_calls=1 if result.model else 0,
                model=result.model or "",
                provider=result.provider or "",
                prompt_tokens=result.token_usage_in,
                completion_tokens=result.token_usage_out,
                latency_ms=result.latency_ms,
            )
            self._telemetry.emit(
                TelemetryEventType.UNIT_FAILED,
                unit_id=unit.unit_id,
            )
        return {
            "status": "ok",
            "unit_id": unit.unit_id,
            "verification_passed": vr.passed,
        }

    async def _on_unit_done(self, task: ScheduledTask) -> None:
        self._completed += 1
        self._estimator.complete_unit(
            task.unit_id,
            completed_count=self._completed,
            total_units=len(self._plan),
        )

    def _build_repair_prompt(
        self,
        attempt: int,
        diagnosis: str,
        original_code: str,
        target_technology: str,
    ) -> TransformationPrompt:
        return TransformationPrompt(
            prompt_context_id=str(uuid.uuid4()),
            system_prompt=
                f"You are a code repair assistant. "
                f"Target technology: {target_technology}",
            user_context=
                f"DIAGNOSIS: {diagnosis}\n"
                f"ATTEMPT: {attempt}\n"
                f"ORIGINAL CODE:\n{original_code}\n"
                f"Return only the corrected code.",
        )

    def _build_result(self) -> ExecutionResult:
        elapsed = (
            (time.time() - self._started_at.timestamp()) * 1000.0
            if self._started_at
            else 0.0
        )
        s = self._throughput.summary()
        return ExecutionResult(
            session_id=self._session_id,
            total_units=len(self._plan),
            completed_units=s.meaningful_throughput,
            failed_units=s.failed,
            skipped_units=s.skipped,
            unavailable_units=s.unavailable,
            repaired_units=s.repaired,
            total_latency_ms=elapsed,
            ledger=[e.model_dump(mode="json") for e in self._throughput.ledger],
            repair_outcomes=[o.model_dump(mode="json") for o in self._repair.outcomes()],
            telemetry_summary=self._telemetry.summary(),
        )


__all__ = [
    "TransformationUnit",
    "ExecutionResult",
    "TransformationExecutor",
]
