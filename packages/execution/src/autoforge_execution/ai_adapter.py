"""
AI Adapter for Execution Platform — bridges workers to AI Infrastructure Platform.

Preserves provider agnosticism and local-first routing by dispatching reasoning
tasks (planning, coding, failure diagnosis, repair) through AI Infrastructure's
ModelRouter / ExecutionContinuityService and capturing real execution telemetry.
"""

from __future__ import annotations

import json
import logging
import os
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
from autoforge_execution.evidence import assemble_evidence

logger = logging.getLogger(__name__)


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
    Dynamically maps task context and worker effective model requirements to RoutingRequest
    and enforces capacity-aware concurrency allocation.
    """

_AI_REQUIRED_TASK_TYPES = frozenset({
    "research", "architecture", "planning", "ui_design", "backend", "frontend",
    "database", "ml", "infrastructure", "devops", "qa", "security", "performance",
    "documentation", "code_archaeology", "architecture_reconstruction",
    "legacy_data", "legacy_integration", "dependency_impact_analysis",
    "modernization_architecture", "migration_planning",
    "research_engineer", "architecture_engineer", "planning_engineer",
    "ui_designer", "backend_engineer", "frontend_engineer", "database_engineer",
    "ml_engineer", "infrastructure_engineer", "devops_engineer", "qa_engineer",
    "security_engineer", "performance_engineer", "documentation_engineer",
    "legacy_code_archaeologist", "legacy_architecture_analyst", "legacy_data_engineer",
    "legacy_integration_engineer", "dependency_impact_analyst",
    "modernization_architect", "migration_engineer",
})


class AIInfrastructureAdapter(AIEngineeringProvider):
    """
    Adapter that connects Execution Engine to AI Infrastructure services.
    Enforces capacity-aware routing, concurrency tracking, model preference preservation,
    and visible failure semantics (no silent deterministic fallbacks for AI-required workers).
    """

    def __init__(
        self,
        router: ModelRouterService | None = None,
        model_executor: Any | None = None,
        capacity_router: Any | None = None,
        allow_deterministic_fallback: bool | None = None,
    ) -> None:
        self._capacity_router = capacity_router
        self._router = router or (getattr(capacity_router, "router_service", None) if capacity_router else None)
        self._executor = model_executor
        self._allow_fallback = allow_deterministic_fallback
        self._last_execution_result: ExecutionResult | None = None
        self._execution_history: list[ExecutionResult] = []

    @property
    def last_execution_result(self) -> ExecutionResult | None:
        return self._last_execution_result

    @property
    def execution_history(self) -> list[ExecutionResult]:
        return list(self._execution_history)

    @property
    def capacity_router(self) -> Any | None:
        return self._capacity_router

    def _record_result(self, result: ExecutionResult) -> None:
        self._last_execution_result = result
        self._execution_history.append(result)

    def _has_explicit_fallback_policy(self, context: ExecutionContext) -> bool:
        reqs = context.effective_model_requirements or {}
        policy = reqs.get("fallback_policy", "")
        if policy in {"deterministic", "allow_fallback", "mock"}:
            return True
        if hasattr(context, "input_data") and isinstance(context.input_data, dict):
            input_policy = context.input_data.get("fallback_policy", "")
            if input_policy in {"deterministic", "allow_fallback", "mock"}:
                return True
        return False

    def _should_allow_fallback(self, context: ExecutionContext | None = None) -> bool:
        """Enforce strict fail-visible policy for AI-required workers.
        
        AI-required workers must NEVER silently receive deterministic template outputs.
        Deterministic fallback is only permitted if explicitly configured.
        """
        # Explicit parameter override takes precedence
        if self._allow_fallback is False:
            return False
        if self._allow_fallback is True:
            return True

        # Explicit override via environment
        if os.environ.get("AUTOFORGE_ALLOW_DETERMINISTIC_FALLBACK", "").lower() in ("true", "1", "yes"):
            return True
        if self._allow_fallback is False and (not context or not self._has_explicit_fallback_policy(context)):
            return False
        if context is None:
            return bool(self._allow_fallback)

        if self._has_explicit_fallback_policy(context):
            return True

        # Check if task is explicitly AI-required
        reqs = context.effective_model_requirements or {}
        is_ai_required = bool(
            getattr(context, "worker_role", None) in _AI_REQUIRED_TASK_TYPES
            or reqs.get("required_capabilities")
            or reqs.get("coding_required")
            or reqs.get("structured_output_required")
            or (context.task_type in _AI_REQUIRED_TASK_TYPES)
        )
        if is_ai_required:
            return False

        # Fallback is permitted for unconfigured generic execution contexts with no model requirements
        if self._allow_fallback is None and not self._executor and not (self._router or self._capacity_router):
            return True

        return False

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

        # 4. Excluded / Preferred Providers
        excluded_providers = set(reqs.get("excluded_provider_ids") or [])
        target_node = reqs.get("node_id") or reqs.get("target_node_id") or reqs.get("preferred_provider")
        if target_node == "local-hp":
            excluded_providers.add("local-m1")
        elif target_node == "local-m1":
            excluded_providers.add("local-hp")

        # 5. Worker-specific intelligence preferences
        quality_priority = reqs.get("quality_priority") or reqs.get("quality_tier")
        latency_priority = reqs.get("latency_priority")
        reliability_minimum = reqs.get("reliability_minimum")
        preferred_caps = reqs.get("preferred_capabilities") or []

        return RoutingRequest(
            required_capabilities=frozenset(caps),
            preferred_capabilities=frozenset(preferred_caps),
            min_context_window_tokens=min_context,
            allowed_deployment_modes=allowed_deployments,
            excluded_provider_ids=frozenset(excluded_providers),
            quality_priority=int(quality_priority) if quality_priority is not None else None,
            latency_priority=latency_priority,
            reliability_minimum=float(reliability_minimum) if reliability_minimum is not None else None,
        )

    async def _execute_request(
        self,
        req: ExecutionRequest,
        routing: RoutingRequest,
    ) -> ExecutionResult:
        """Execute a model request through the bound executor.

        Supports three executor types:
        1. ExecutionContinuityService — routing + retry + failover
        2. RoutedModelExecutor — routing + single execution
        3. ExecutorRegistry — direct execution (requires router for target resolution)
        """
        if self._executor is None:
            raise RuntimeError("No model executor is bound to AIInfrastructureAdapter")

        from autoforge_ai_infrastructure.execution import (
            ExecutionTarget,
            ExecutorRegistry,
            execute_attempt,
        )

        # Handle CapacityAwareRouter allocation if available
        cap_mgr = getattr(self._capacity_router, "capacity_manager", None) if self._capacity_router else None
        allocated_model = None

        if self._capacity_router is not None:
            req_dict = {
                "required_capabilities": list(routing.required_capabilities),
                "preferred_capabilities": list(routing.preferred_capabilities),
                "min_context_window_tokens": routing.min_context_window_tokens,
                "privacy_policy": "local_only" if routing.allowed_deployment_modes == frozenset({DeploymentMode.LOCAL}) else "any",
                "quality_priority": routing.quality_priority,
                "latency_priority": routing.latency_priority,
                "reliability_minimum": routing.reliability_minimum,
            }
            model_meta, candidate = await self._capacity_router.route_task(req_dict)
            allocated_model = model_meta
            if cap_mgr:
                await cap_mgr.acquire_slot(model_meta.model_id, model_meta.provider_id)

        try:
            if isinstance(self._executor, ExecutorRegistry):
                if allocated_model is not None:
                    target = ExecutionTarget(
                        model_id=allocated_model.model_id,
                        provider_id=allocated_model.provider_id,
                    )
                else:
                    if self._router is None:
                        raise RuntimeError(
                            "AIInfrastructureAdapter has an ExecutorRegistry but no ModelRouterService; "
                            "cannot resolve a model target for execution"
                        )
                    decision = self._router.route(routing)
                    candidate = decision.selected
                    target = ExecutionTarget(
                        model_id=candidate.model.model_id,
                        provider_id=candidate.model.provider_id,
                    )
                return await execute_attempt(self._executor, req, target)

            try:
                # Try ExecutionContinuityService signature
                return await self._executor.execute(
                    payload=req.payload,
                    routing_request=routing,
                    parameters=req.parameters,
                    timeout_seconds=req.timeout_seconds,
                )
            except TypeError:
                # Fallback to RoutedModelExecutor signature
                return await self._executor.execute(req, routing)
        finally:
            if cap_mgr and allocated_model is not None:
                await cap_mgr.release_slot(allocated_model.model_id)

    async def generate_plan(self, context: ExecutionContext) -> str:
        if self._executor and (self._router or self._capacity_router):
            system_msg = (
                "You are an expert software engineering assistant. "
                "Produce a structured, high-level, step-by-step implementation plan for the given task."
            )
            user_msg = (
                f"Task: {context.task_name}\n"
                f"Description:\n{context.task_description}\n\n"
                f"Produce the implementation plan covering:\n"
                f"1. Architecture & components\n"
                f"2. Data models & schemas\n"
                f"3. API endpoints & validation\n"
                f"4. Testing strategy\n"
                f"5. Documentation"
            )
            # Phase 18-D: append retrieved-knowledge evidence block
            evidence_block = assemble_evidence(context.retrieved_knowledge)
            if evidence_block:
                user_msg = user_msg + "\n\n" + evidence_block
            max_toks = (
                context.effective_model_requirements.get("max_tokens")
                or context.effective_model_requirements.get("max_output_tokens")
                or 350
            )
            req = ExecutionRequest(
                payload={
                    "system": system_msg,
                    "prompt": user_msg,
                    "context": context.format_reasoning_prompt(1),
                },
                parameters={"temperature": 0.2, "max_tokens": int(max_toks)},
            )
            routing = self._build_routing_request(
                context, default_capability=CapabilityIds.REASONING
            )
            try:
                res: ExecutionResult = await self._execute_request(req, routing)
                self._record_result(res)
                plan_text = res.output.get("plan") or res.output.get("content")
                if plan_text:
                    return str(plan_text).strip()
            except Exception as e:
                logger.warning(f"Model plan generation failed: {e}")
                if not self._should_allow_fallback(context):
                    raise

        if not self._should_allow_fallback(context):
            raise RuntimeError(
                f"AI reasoning execution failed or was not configured for task '{context.task_name}'. "
                "Deterministic fallback is disabled for this AI-required worker."
            )
        return f"Implementation plan for {context.task_name}: analyze requirements, inspect files, apply edits, and verify."

    async def generate_implementation(
        self,
        context: ExecutionContext,
        plan: str,
    ) -> list[dict[str, Any]]:
        if self._executor and (self._router or self._capacity_router):
            prompt_content = (
                f"You are an expert software engineer implementing a software task.\n"
                f"Task: {context.task_name}\n"
                f"Plan: {plan}\n"
                f"Context: {context.format_reasoning_prompt(1)}\n\n"
                f"Generate the exact file modifications required. "
                f"Return JSON format:\n"
                f'{{"file_edits": [{{"path": "relative/path/to/file.py", "content": "complete file content"}}]}}'
            )
            req = ExecutionRequest(
                payload={
                    "system": "You are an expert software engineer implementing software tasks. Always output valid JSON.",
                    "task": "implementation",
                    "prompt": prompt_content,
                    "plan": plan,
                    "format": "json",
                    "structured_output": True,
                },
                parameters={"temperature": 0.1, "structured_output": True},
            )
            routing = self._build_routing_request(
                context, default_capability=CapabilityIds.CODE_GENERATION
            )
            try:
                res: ExecutionResult = await self._execute_request(req, routing)
                self._record_result(res)
                out = res.output
                
                # Check for file_edits in top-level output or structured_output
                edits = out.get("file_edits")
                if not edits and isinstance(out.get("structured_output"), dict):
                    edits = out["structured_output"].get("file_edits")
                elif not edits and isinstance(out.get("structured_output"), list):
                    edits = out["structured_output"]

                if isinstance(edits, list) and edits:
                    return [
                        {"path": str(e.get("path", "")), "content": str(e.get("content", ""))}
                        for e in edits
                        if isinstance(e, dict) and "path" in e and "content" in e
                    ]
            except Exception as e:
                logger.warning(f"Model implementation generation failed: {e}")
                if not self._should_allow_fallback(context):
                    raise

        # Check if fallback is explicitly permitted
        if self._should_allow_fallback(context):
            input_files = context.input_data.get("files") or context.input_data.get("file_edits")
            if isinstance(input_files, list):
                return input_files
            if isinstance(input_files, dict):
                return [{"path": k, "content": v} for k, v in input_files.items()]
            return []

        raise RuntimeError(
            f"AI implementation generation failed or was not configured for task '{context.task_name}'. "
            "Deterministic fallback is disabled for this AI-required worker."
        )

    async def diagnose_failure(
        self,
        context: ExecutionContext,
        failure_evidence: dict[str, Any],
    ) -> DiagnosisReport:
        if self._executor and (self._router or self._capacity_router):
            prompt_content = (
                f"Analyze the following verification or test failure and diagnose the root cause.\n"
                f"Task: {context.task_name}\n"
                f"Failure Evidence: {json.dumps(failure_evidence, indent=2)}\n\n"
                f"Return JSON format:\n"
                f'{{"root_cause": "description of root cause", "failure_mechanism": "how it failed", "affected_files": ["path/to/file.py"], "suggested_fix": "how to fix it", "confidence_score": 0.95}}'
            )
            req = ExecutionRequest(
                payload={
                    "system": "You are an automated software test failure diagnosis expert. Output JSON only.",
                    "task": "diagnose",
                    "prompt": prompt_content,
                    "evidence": failure_evidence,
                    "format": "json",
                    "structured_output": True,
                },
                parameters={"temperature": 0.1, "structured_output": True},
            )
            routing = self._build_routing_request(
                context, default_capability=CapabilityIds.REASONING
            )
            try:
                res: ExecutionResult = await self._execute_request(req, routing)
                self._record_result(res)
                out = res.output
                struct = out.get("structured_output") if isinstance(out.get("structured_output"), dict) else out
                
                if isinstance(struct, dict) and "root_cause" in struct:
                    return DiagnosisReport(
                        root_cause=str(struct.get("root_cause", "Execution or test check failed")),
                        failure_mechanism=str(struct.get("failure_mechanism", str(failure_evidence))),
                        affected_files=list(struct.get("affected_files", [])),
                        suggested_fix=str(struct.get("suggested_fix", "Apply necessary fixes to passing condition")),
                        confidence_score=float(struct.get("confidence_score", 0.9)),
                    )
            except Exception as e:
                logger.warning(f"Model diagnosis generation failed: {e}")
                if not self._should_allow_fallback(context):
                    raise

        if not self._should_allow_fallback(context):
            raise RuntimeError(
                f"AI diagnosis execution failed or was not configured for task '{context.task_name}'."
            )

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
        if self._executor and (self._router or self._capacity_router):
            prompt_content = (
                f"Given the following diagnosis of a test/execution failure, generate the repaired file content.\n"
                f"Task: {context.task_name}\n"
                f"Diagnosis:\n{diagnosis.model_dump_json(indent=2)}\n\n"
                f"Return JSON format:\n"
                f'{{"file_edits": [{{"path": "relative/path/to/file.py", "content": "complete repaired file content"}}]}}'
            )
            req = ExecutionRequest(
                payload={
                    "system": "You are a software repair expert fixing code defects. Output JSON only.",
                    "task": "repair",
                    "prompt": prompt_content,
                    "diagnosis": diagnosis.model_dump(),
                    "format": "json",
                    "structured_output": True,
                },
                parameters={"temperature": 0.1, "structured_output": True},
            )
            routing = self._build_routing_request(
                context, default_capability=CapabilityIds.CODE_GENERATION
            )
            try:
                res: ExecutionResult = await self._execute_request(req, routing)
                self._record_result(res)
                out = res.output
                
                edits = out.get("file_edits")
                if not edits and isinstance(out.get("structured_output"), dict):
                    edits = out["structured_output"].get("file_edits")
                elif not edits and isinstance(out.get("structured_output"), list):
                    edits = out["structured_output"]

                if isinstance(edits, list) and edits:
                    return [
                        {"path": str(e.get("path", "")), "content": str(e.get("content", ""))}
                        for e in edits
                        if isinstance(e, dict) and "path" in e and "content" in e
                    ]
            except Exception as e:
                logger.warning(f"Model repair generation failed: {e}")
                if not self._should_allow_fallback(context):
                    raise

        if self._should_allow_fallback(context):
            repair_files = context.input_data.get("repair_files") or context.input_data.get("repair_edits")
            if isinstance(repair_files, list):
                return repair_files
            if isinstance(repair_files, dict):
                return [{"path": k, "content": v} for k, v in repair_files.items()]
            return []

        raise RuntimeError(
            f"AI repair execution failed or was not configured for task '{context.task_name}'."
        )
