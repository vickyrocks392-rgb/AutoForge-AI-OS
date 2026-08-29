"""
AI Adapter for Execution Platform — bridges workers to AI Infrastructure Platform.

Preserves provider agnosticism and local-first routing by dispatching reasoning
tasks (planning, coding, failure diagnosis, repair) through AI Infrastructure's
ModelRouter / ExecutionContinuityService and capturing real execution telemetry.
"""

from __future__ import annotations

import json
import logging
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
    Dynamically maps task context and worker effective model requirements to RoutingRequest.
    """

    def __init__(
        self,
        router: ModelRouterService | None = None,
        model_executor: Any | None = None,
    ) -> None:
        self._router = router
        self._executor = model_executor
        self._last_execution_result: ExecutionResult | None = None
        self._execution_history: list[ExecutionResult] = []

    @property
    def last_execution_result(self) -> ExecutionResult | None:
        return self._last_execution_result

    @property
    def execution_history(self) -> list[ExecutionResult]:
        return list(self._execution_history)

    def _record_result(self, result: ExecutionResult) -> None:
        self._last_execution_result = result
        self._execution_history.append(result)

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

        return RoutingRequest(
            required_capabilities=frozenset(caps),
            min_context_window_tokens=min_context,
            allowed_deployment_modes=allowed_deployments,
            excluded_provider_ids=frozenset(excluded_providers),
        )



    async def _execute_request(
        self,
        req: ExecutionRequest,
        routing: RoutingRequest,
    ) -> ExecutionResult:
        if self._executor is None:
            raise RuntimeError("No model executor is bound to AIInfrastructureAdapter")

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

    async def generate_plan(self, context: ExecutionContext) -> str:
        if self._executor and self._router:
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

        return f"Implementation plan for {context.task_name}: analyze requirements, inspect files, apply edits, and verify."

    async def generate_implementation(
        self,
        context: ExecutionContext,
        plan: str,
    ) -> list[dict[str, Any]]:
        if self._executor and self._router:
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

        # Check if task input_data has a repair strategy or repaired files specified
        repair_files = context.input_data.get("repair_files") or context.input_data.get("repair_edits")
        if isinstance(repair_files, list):
            return repair_files
        if isinstance(repair_files, dict):
            return [{"path": k, "content": v} for k, v in repair_files.items()]

        return []
