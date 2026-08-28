"""
AI Adapter for Execution Platform — bridges workers to AI Infrastructure Platform.

Preserves provider agnosticism and local-first routing by dispatching reasoning
tasks (planning, coding, failure diagnosis, repair) through AI Infrastructure's
ModelRouter / ExecutionContinuityService.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from autoforge_ai_infrastructure.execution import (
    ExecutionRequest,
    ExecutionResult,
    RoutedModelExecutor,
)
from autoforge_ai_infrastructure.metadata import (
    CapabilityIds,
    DeploymentMode,
    ModelQuery,
    RoutingRequest,
)
from autoforge_ai_infrastructure.router import ModelRouterService

from autoforge_execution.context import ExecutionContext
from autoforge_execution.models import DiagnosisReport


@runtime_checkable
class AIEngineeringProvider(Protocol):
    """Protocol for AI reasoning services used by engineering workers."""

    async def generate_plan(self, context: ExecutionContext) -> str:
        """Formulate an initial action/implementation plan."""
        ...

    async def generate_implementation(
        self,
        context: ExecutionContext,
        plan: str,
    ) -> list[dict[str, Any]]:
        """Produce concrete file edits/actions to satisfy the plan."""
        ...

    async def diagnose_failure(
        self,
        context: ExecutionContext,
        failure_evidence: dict[str, Any],
    ) -> DiagnosisReport:
        """Analyze a test or verification failure and propose a root cause + remedy."""
        ...

    async def generate_repair(
        self,
        context: ExecutionContext,
        diagnosis: DiagnosisReport,
    ) -> list[dict[str, Any]]:
        """Generate targeted fix actions based on a diagnosed failure."""
        ...


class AIInfrastructureAdapter:
    """
    Standard AI provider implementation using autoforge_ai_infrastructure.
    Dynamically maps task context and worker effective model requirements to RoutingRequest.
    """

    def __init__(
        self,
        router: ModelRouterService | None = None,
        model_executor: RoutedModelExecutor | None = None,
    ) -> None:
        self._router = router
        self._executor = model_executor

    def _build_routing_request(
        self,
        context: ExecutionContext,
        default_capability: str | None = None,
    ) -> RoutingRequest:
        reqs = context.effective_model_requirements or {}

        # 1. Required capabilities from effective requirements
        caps = set(reqs.get("required_capabilities") or reqs.get("capabilities") or [])
        if not caps and default_capability:
            caps.add(default_capability)
        elif not caps:
            caps.add(CapabilityIds.TEXT_GENERATION)

        # 2. Min context window
        min_context = reqs.get("min_context_window_tokens") or reqs.get("min_context") or 1024

        # 3. Allowed deployment modes (Privacy)
        privacy = reqs.get("privacy_policy", "local_only")
        allowed_deployments = (
            frozenset({DeploymentMode.LOCAL}) if privacy == "local_only" else None
        )

        return RoutingRequest(
            required_capabilities=frozenset(caps),
            min_context_window_tokens=min_context,
            allowed_deployment_modes=allowed_deployments,
        )

    async def generate_plan(self, context: ExecutionContext) -> str:
        if self._executor and self._router:
            req = ExecutionRequest(
                payload={
                    "task": "plan",
                    "context": context.format_reasoning_prompt(1),
                }
            )
            routing = self._build_routing_request(
                context, default_capability=CapabilityIds.REASONING
            )
            try:
                res: ExecutionResult = await self._executor.execute(req, routing)
                return str(res.output.get("plan", f"Plan for {context.task_name}"))
            except Exception:
                pass
        return f"Implementation plan for {context.task_name}: analyze requirements, inspect files, apply edits, and verify."

    async def generate_implementation(
        self,
        context: ExecutionContext,
        plan: str,
    ) -> list[dict[str, Any]]:
        if self._executor and self._router:
            req = ExecutionRequest(
                payload={
                    "task": "implementation",
                    "plan": plan,
                    "context": context.format_reasoning_prompt(1),
                }
            )
            routing = self._build_routing_request(
                context, default_capability=CapabilityIds.CODE_GENERATION
            )
            try:
                res: ExecutionResult = await self._executor.execute(req, routing)
                edits = res.output.get("file_edits", [])
                if isinstance(edits, list) and edits:
                    return edits
            except Exception:
                pass

        # Check if context input_data specifies explicit file modifications
        input_files = context.input_data.get("files") or context.input_data.get("file_edits")
        if isinstance(input_files, list):
            return input_files
        if isinstance(input_files, dict):
            return [{"path": k, "content": v} for k, v in input_files.items()]

        return []

    async def diagnose_failure(
        self,
        context: ExecutionContext,
        failure_evidence: dict[str, Any],
    ) -> DiagnosisReport:
        if self._executor and self._router:
            req = ExecutionRequest(
                payload={
                    "task": "diagnose",
                    "evidence": failure_evidence,
                    "context": context.format_reasoning_prompt(len(context.prior_iterations) + 1),
                }
            )
            routing = self._build_routing_request(
                context, default_capability=CapabilityIds.REASONING
            )
            try:
                res: ExecutionResult = await self._executor.execute(req, routing)
                out = res.output
                return DiagnosisReport(
                    root_cause=out.get("root_cause", "Execution or test check failed"),
                    failure_mechanism=out.get("failure_mechanism", str(failure_evidence)),
                    affected_files=out.get("affected_files", []),
                    suggested_fix=out.get("suggested_fix", "Apply necessary fixes to passing condition"),
                    confidence_score=float(out.get("confidence_score", 0.9)),
                )
            except Exception:
                pass

        # Fallback diagnosis from evidence
        stderr = failure_evidence.get("stderr", "")
        stdout = failure_evidence.get("stdout", "")
        failures = failure_evidence.get("failures", [])

        cause = failures[0] if failures else (stderr.strip() or stdout.strip() or "Non-zero exit code detected")
        return DiagnosisReport(
            root_cause=f"Test/command failure: {cause[:200]}",
            failure_mechanism=stderr[:400] or stdout[:400],
            affected_files=context.project_files,
            suggested_fix="Correct the logic in affected files to satisfy the tests",
            confidence_score=0.85,
        )

    async def generate_repair(
        self,
        context: ExecutionContext,
        diagnosis: DiagnosisReport,
    ) -> list[dict[str, Any]]:
        if self._executor and self._router:
            req = ExecutionRequest(
                payload={
                    "task": "repair",
                    "diagnosis": diagnosis.model_dump(),
                    "context": context.format_reasoning_prompt(len(context.prior_iterations) + 1),
                }
            )
            routing = self._build_routing_request(
                context, default_capability=CapabilityIds.CODE_GENERATION
            )
            try:
                res: ExecutionResult = await self._executor.execute(req, routing)
                edits = res.output.get("file_edits", [])
                if isinstance(edits, list) and edits:
                    return edits
            except Exception:
                pass

        # Check if task input_data has a repair strategy or repaired files specified
        repair_files = context.input_data.get("repair_files") or context.input_data.get("repair_edits")
        if isinstance(repair_files, list):
            return repair_files
        if isinstance(repair_files, dict):
            return [{"path": k, "content": v} for k, v in repair_files.items()]

        return []
