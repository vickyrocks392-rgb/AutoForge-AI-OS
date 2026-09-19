"""Canonical Power Engine Abstract Base & Shared Lifecycle Framework."""

from __future__ import annotations

import os
import uuid
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from autoforge_power_engines.specification import CustomerProjectSpecification
from autoforge_power_engines.risk import PowerEngineRiskEvaluator, RiskAssessment, RiskLevel

logger = logging.getLogger("autoforge.power_engines.base")


def resolve_output_root(explicit_root: Optional[str] = None) -> Path:
    """
    Resolves the canonical customer output directory root.
    Order of precedence:
    1. Explicit caller-provided output_root
    2. AUTOFORGE_OUTPUT_ROOT environment variable
    3. Fallback to /tmp/autoforge_deliveries (safe OS-portable default outside repository)
    """
    if explicit_root and explicit_root.strip():
        return Path(explicit_root).expanduser().resolve()
    env_root = os.environ.get("AUTOFORGE_OUTPUT_ROOT")
    if env_root and env_root.strip():
        return Path(env_root).expanduser().resolve()
    # Default outside current git repo root
    return (Path("/tmp") / "autoforge_deliveries").resolve()


class PowerEngineLifecycleStage(str, Enum):
    """The canonical 11-stage autonomous execution lifecycle."""
    INTAKE = "INTAKE"
    UNDERSTAND_ANALYZE = "UNDERSTAND_ANALYZE"
    PLAN = "PLAN"
    EXECUTE = "EXECUTE"
    OBSERVE = "OBSERVE"
    VERIFY = "VERIFY"
    DIAGNOSE = "DIAGNOSE"
    REPAIR = "REPAIR"
    RE_VERIFY = "RE_VERIFY"
    PACKAGE = "PACKAGE"
    DELIVER = "DELIVER"
    # Special safety wait state
    WAITING_FOR_HUMAN_APPROVAL = "WAITING_FOR_HUMAN_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StageExecutionRecord(BaseModel):
    """Execution telemetry and evidence for a single lifecycle stage."""
    stage: PowerEngineLifecycleStage
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    success: bool = False
    repaired: bool = False
    risk_assessment: Optional[RiskAssessment] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None

    def duration_ms(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000.0
        return 0.0


class PowerEngineContext(BaseModel):
    """Runtime context for an active Power Engine execution."""
    execution_id: str = Field(default_factory=lambda: f"pe-exec-{uuid.uuid4().hex[:8]}")
    project_id: str
    delivery_id: str = Field(default_factory=lambda: f"delivery-{uuid.uuid4().hex[:8]}")
    specification: CustomerProjectSpecification
    output_root: Path
    delivery_dir: Path
    current_stage: PowerEngineLifecycleStage = PowerEngineLifecycleStage.INTAKE
    stage_history: List[StageExecutionRecord] = Field(default_factory=list)
    pending_approval: Optional[RiskAssessment] = None
    telemetry: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PowerEngineResult(BaseModel):
    """Final delivery outcome for a customer Power Engine run."""
    success: bool
    execution_id: str
    project_name: str
    delivery_dir: str
    stages_executed: List[str]
    repair_count: int = 0
    verification_scorecard: Dict[str, Any] = Field(default_factory=dict)
    summary_report: str = ""
    error_message: Optional[str] = None


class PowerEngine(ABC):
    """
    Abstract Base Class for all AutoForge commercial Power Engines.
    Implements the canonical 11-stage autonomous execution lifecycle and risk gates.
    """

    def __init__(
        self,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        risk_evaluator: Optional[PowerEngineRiskEvaluator] = None,
    ):
        self.event_sink = event_sink
        self.risk_evaluator = risk_evaluator or PowerEngineRiskEvaluator()

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        logger.info(f"PowerEngine Event [{event_type}]: {payload}")
        if self.event_sink:
            try:
                self.event_sink({"event_type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), "data": payload})
            except Exception as e:
                logger.warning(f"Error in event_sink: {e}")

    def create_context(self, spec: CustomerProjectSpecification) -> PowerEngineContext:
        """Initializes isolated runtime execution context."""
        out_root = resolve_output_root(spec.output_root)
        sanitized_pid = spec.sanitized_project_id()
        delivery_id = f"delivery-{uuid.uuid4().hex[:8]}"
        delivery_dir = out_root / sanitized_pid / delivery_id
        
        ctx = PowerEngineContext(
            project_id=sanitized_pid,
            delivery_id=delivery_id,
            specification=spec,
            output_root=out_root,
            delivery_dir=delivery_dir,
        )
        return ctx

    async def execute_lifecycle(
        self,
        spec: CustomerProjectSpecification,
        auto_approve_safe_risks: bool = True,
    ) -> PowerEngineResult:
        """
        Executes the canonical 11-stage Power Engine lifecycle autonomously.
        """
        ctx = self.create_context(spec)
        ctx.delivery_dir.mkdir(parents=True, exist_ok=True)
        self._emit_event("POWER_ENGINE_STARTED", {"project": spec.project_name, "delivery_dir": str(ctx.delivery_dir)})

        stages = [
            (PowerEngineLifecycleStage.INTAKE, self._stage_intake),
            (PowerEngineLifecycleStage.UNDERSTAND_ANALYZE, self._stage_understand_analyze),
            (PowerEngineLifecycleStage.PLAN, self._stage_plan),
            (PowerEngineLifecycleStage.EXECUTE, self._stage_execute),
            (PowerEngineLifecycleStage.OBSERVE, self._stage_observe),
            (PowerEngineLifecycleStage.VERIFY, self._stage_verify),
            (PowerEngineLifecycleStage.DIAGNOSE, self._stage_diagnose),
            (PowerEngineLifecycleStage.REPAIR, self._stage_repair),
            (PowerEngineLifecycleStage.RE_VERIFY, self._stage_re_verify),
            (PowerEngineLifecycleStage.PACKAGE, self._stage_package),
            (PowerEngineLifecycleStage.DELIVER, self._stage_deliver),
        ]

        repair_cycles = 0

        for stage_enum, stage_fn in stages:
            ctx.current_stage = stage_enum
            rec = StageExecutionRecord(stage=stage_enum)
            self._emit_event(f"STAGE_{stage_enum.value}_STARTED", {"stage": stage_enum.value, "execution_id": ctx.execution_id})

            # Continuous Risk Check Hook
            risk = self.risk_evaluator.assess_stage_action(
                stage_name=stage_enum.value,
                action="execute_stage",
                target_path=str(ctx.delivery_dir),
                context={"project_id": ctx.project_id}
            )
            rec.risk_assessment = risk

            if risk.approval_required:
                self._emit_event("RISK_DETECTED", risk.model_dump())
                self._emit_event("APPROVAL_REQUIRED", {"stage": stage_enum.value, "risk": risk.model_dump()})
                ctx.current_stage = PowerEngineLifecycleStage.WAITING_FOR_HUMAN_APPROVAL
                ctx.pending_approval = risk

                if not auto_approve_safe_risks:
                    rec.completed_at = datetime.now(timezone.utc)
                    rec.success = False
                    rec.error_message = "Execution paused: WAITING_FOR_HUMAN_APPROVAL"
                    ctx.stage_history.append(rec)
                    return PowerEngineResult(
                        success=False,
                        execution_id=ctx.execution_id,
                        project_name=spec.project_name,
                        delivery_dir=str(ctx.delivery_dir),
                        stages_executed=[r.stage.value for r in ctx.stage_history],
                        error_message="Execution paused at risk boundary: WAITING_FOR_HUMAN_APPROVAL"
                    )
                # Resumed after authorized sign-off
                self._emit_event("APPROVAL_GRANTED", {"stage": stage_enum.value})
                self._emit_event("EXECUTION_RESUMED", {"stage": stage_enum.value})
                ctx.current_stage = stage_enum

            # Execute Stage Handler
            try:
                stage_result = await stage_fn(ctx)
                rec.details = stage_result or {}
                rec.success = True
                if stage_enum == PowerEngineLifecycleStage.REPAIR and stage_result.get("repaired"):
                    repair_cycles += stage_result.get("repair_count", 1)
                    rec.repaired = True
            except Exception as ex:
                rec.success = False
                rec.error_message = str(ex)
                rec.completed_at = datetime.now(timezone.utc)
                ctx.stage_history.append(rec)
                self._emit_event(f"STAGE_{stage_enum.value}_FAILED", {"stage": stage_enum.value, "error": str(ex)})
                return PowerEngineResult(
                    success=False,
                    execution_id=ctx.execution_id,
                    project_name=spec.project_name,
                    delivery_dir=str(ctx.delivery_dir),
                    stages_executed=[r.stage.value for r in ctx.stage_history],
                    repair_count=repair_cycles,
                    error_message=f"Stage {stage_enum.value} failed: {ex}"
                )

            rec.completed_at = datetime.now(timezone.utc)
            ctx.stage_history.append(rec)
            self._emit_event(f"STAGE_{stage_enum.value}_COMPLETED", {
                "stage": stage_enum.value,
                "duration_ms": rec.duration_ms(),
                "details": rec.details
            })

        ctx.current_stage = PowerEngineLifecycleStage.COMPLETED
        self._emit_event("POWER_ENGINE_COMPLETED", {
            "project": spec.project_name,
            "delivery_dir": str(ctx.delivery_dir),
            "total_stages": len(ctx.stage_history),
            "repair_cycles": repair_cycles
        })

        return PowerEngineResult(
            success=True,
            execution_id=ctx.execution_id,
            project_name=spec.project_name,
            delivery_dir=str(ctx.delivery_dir),
            stages_executed=[r.stage.value for r in ctx.stage_history],
            repair_count=repair_cycles,
            verification_scorecard=ctx.telemetry.get("verification_scorecard", {}),
            summary_report=f"Turnkey deliverable published successfully to {ctx.delivery_dir}"
        )

    # ── Abstract Lifecycle Stage Handlers ─────────────────────────────────────
    @abstractmethod
    async def _stage_intake(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 1: Ingest and validate customer project specification."""

    @abstractmethod
    async def _stage_understand_analyze(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 2: Discover and analyze domain documents and knowledge assets."""

    @abstractmethod
    async def _stage_plan(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 3: Synthesize engineering deliverable plan and architecture."""

    @abstractmethod
    async def _stage_execute(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 4: Execute code/index generation and asset creation."""

    @abstractmethod
    async def _stage_observe(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 5: Observe and gather telemetry on generated artifacts."""

    @abstractmethod
    async def _stage_verify(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 6: Verify build, tests, grounding, and syntax."""

    @abstractmethod
    async def _stage_diagnose(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 7: Diagnose any discovered failures or regressions."""

    @abstractmethod
    async def _stage_repair(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 8: Apply closed-loop repairs to defects."""

    @abstractmethod
    async def _stage_re_verify(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 9: Re-verify repaired artifacts to confirm 100% pass."""

    @abstractmethod
    async def _stage_package(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 10: Package turnkey customer project with isolated structure."""

    @abstractmethod
    async def _stage_deliver(self, ctx: PowerEngineContext) -> Dict[str, Any]:
        """Stage 11: Finalize delivery directory, write README.md & DELIVERY_REPORT.md."""
