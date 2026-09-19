"""
Specialized loops for Greenfield and Legacy Engineering Workers.
"""

from __future__ import annotations
import re
import uuid
import time
from typing import Any, Callable, Tuple

from autoforge_execution.loop import EngineeringLoop
from autoforge_execution.context import ExecutionContext
from autoforge_execution.models import (
    ArtifactRecord,
    ArtifactType,
    EvaluationResult,
    EvaluationStatus,
    LoopStatus,
    ArtifactProvenance,
)

from autoforge_workforce.legacy_models import LegacySystemModel, LegacyEvidence, FactState, BusinessRule
from autoforge_workforce.legacy_analyzers import get_analyzer_for_file


# ── Shared AI output validation ────────────────────────────────────────────────

# The ONLY known deterministic fallback produced by
# ``AIInfrastructureAdapter.generate_plan()`` is the exact template:
#
#   "Implementation plan for {task_name}: analyze requirements, inspect files,
#    apply edits, and verify."
#
# The old substring detector ("Implementation plan for" in output) was too
# aggressive and rejected legitimate LLM output that happened to use a common
# phrase. Real LLM models frequently produce plans starting with
# "Implementation plan for" or "Research plan for" or "Architecture for" —
# these are NOT deterministic fallbacks.
#
# The structural detector matches the EXACT known template format:
#   - starts with "Implementation plan for "
#   - has a task name (any short non-newline string)
#   - followed by the literal suffix
#   - AND the total length is short (< _MIN_OUTPUT_LENGTH * 4) — real model
#     output is always substantially longer than the template.
#
# If the AI adapter reported a successful execution via its
# ``last_execution_result``, that is authoritative proof of AI provenance
# and is used to bypass the template heuristic (the heuristic remains as a
# narrow defense against unknown regressions of the old deterministic
# fallback).

_FALLBACK_TEMPLATE_RE = re.compile(
    r"^\s*Implementation plan for [^:\n]{1,200}: "
    r"analyze requirements, inspect files, apply edits, and verify\.\s*$",
    re.IGNORECASE | re.DOTALL,
)

# Heuristic thresholds: real model output is always substantially longer
# than the deterministic fallback template.
_MIN_OUTPUT_LENGTH = 50
# Deterministic template is ~80-120 chars; anything ≤ 4x MIN is suspicious
_MAX_FALLBACK_LENGTH = _MIN_OUTPUT_LENGTH * 4  # 200 chars


def _has_ai_execution_provenance(ai_provider: Any) -> bool:
    """Check whether the AI provider has authoritative evidence of real AI execution.

    The AI adapter's ``last_execution_result`` is set after a successful
    provider call. If present, it proves AI execution beyond any text
    heuristic.
    """
    if ai_provider is None:
        return False
    last_result = getattr(ai_provider, "last_execution_result", None)
    if last_result is None:
        return False
    # ExecutionResult must have a non-empty model_id and provider_id
    model_id = getattr(last_result, "model_id", None)
    provider_id = getattr(last_result, "provider_id", None)
    return bool(model_id and provider_id)


def _is_real_ai_output(output: Any, ai_provider: Any = None) -> bool:
    """Determine if ``output`` is real AI output vs known deterministic fallback.

    Validation strategy (H1 — 18-C hardening):
      1. Empty / None / very short output → INVALID.
      2. If the AI provider has authoritative ExecutionResult metadata,
         trust the AI provenance. Real AI output is acceptable.
      3. If output matches the EXACT structural template of the known
         deterministic fallback AND is suspiciously short, treat as
         fallback. This is the narrow structural check.
      4. Otherwise, accept the output. Generic phrases like "Implementation
         plan for", "Research plan for", "Architecture for" appearing in
         real model output are NOT rejected.

    Args:
        output: Candidate output text from the AI adapter.
        ai_provider: Optional AI provider used to check execution
            provenance via ``last_execution_result``.

    Returns:
        True if the output is real AI output, False if it appears to be
        the deterministic fallback template.
    """
    if output is None:
        return False
    if not isinstance(output, str):
        return False
    stripped = output.strip()
    if len(stripped) < _MIN_OUTPUT_LENGTH:
        return False

    # Authoritative AI execution evidence from the adapter.
    if _has_ai_execution_provenance(ai_provider):
        # Real AI execution was recorded. Accept the output.
        return True

    # No authoritative provenance. Apply the narrow structural check.
    # The old substring heuristic was too aggressive — it rejected real
    # model output containing "Implementation plan for" as a common phrase.
    # The new check is structural: the output must match the EXACT
    # fallback template format AND be suspiciously short.
    if len(stripped) <= _MAX_FALLBACK_LENGTH and _FALLBACK_TEMPLATE_RE.match(stripped):
        return False

    return True


class SpecializedLoop(EngineeringLoop):
    """
    Base class for workforce specialized loops.
    """
    # Backwards-compat: subclasses may reference these via inheritance.
    _FALLBACK_PATTERNS = ()
    _MIN_OUTPUT_LENGTH = _MIN_OUTPUT_LENGTH

    def _is_real_ai_output(self, output: str) -> bool:
        """Backward-compatible instance method. Delegates to module helper."""
        return _is_real_ai_output(output, ai_provider=getattr(self, "_ai", None))

    async def _run_ai_specialized_task(
        self,
        context: ExecutionContext,
        worker_id: str,
        task_type: str,
        prompt_instruction: str,
        artifact_name: str,
        artifact_type: ArtifactType = ArtifactType.SUMMARY,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        """Execute a specialized task via the canonical AI infrastructure.

        Ensures genuine AI reasoning occurs, validates AI output provenance,
        and fails visibly if LLM execution fails or returns unpermitted fallback.
        """
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        content = ""
        routing_info = "unknown"

        if self._ai is None:
            is_real_output = False
        else:
            try:
                from copy import copy
                spec_ctx = copy(context)
                spec_ctx.task_type = task_type
                spec_ctx.task_description = (
                    f"{prompt_instruction}\n\n"
                    f"Task: {context.task_name}\n"
                    f"Details: {context.task_description or 'No additional description provided'}"
                )
                content = await self._ai.generate_plan(spec_ctx)

                if hasattr(self._ai, "last_execution_result") and self._ai.last_execution_result:
                    result = self._ai.last_execution_result
                    routing_info = f"{result.provider_id}/{result.model_id}"
                else:
                    routing_info = "no-execution-result"
            except Exception as exc:
                content = ""
                routing_info = f"error: {type(exc).__name__}: {exc}"
                is_real_output = False
            else:
                is_real_output = self._is_real_ai_output(content)

        produced_artifacts: list[ArtifactRecord] = []
        if is_real_output:
            art = self._artifacts.record_artifact(
                name=artifact_name,
                artifact_type=artifact_type,
                content=content,
                provenance=provenance,
            )
            produced_artifacts.append(art)
            eval_status = EvaluationStatus.PASSED
            findings = f"{artifact_name} generated ({len(content)} chars, routed via {routing_info})"
        else:
            eval_status = EvaluationStatus.FAILED
            findings = f"AI {task_type} generation failed or returned fallback. routing={routing_info}"

        eval_res = EvaluationResult(
            status=eval_status,
            qualitative_findings=findings,
        )
        self._status = LoopStatus.COMPLETED if is_real_output else LoopStatus.FAILED
        return is_real_output, produced_artifacts, eval_res


# ── Greenfield Loops ─────────────────────────────────────────────────────────

class ResearchLoop(SpecializedLoop):
    """
    Real AI-driven research loop.

    Invokes the AI infrastructure to perform domain investigation and produce
    a research brief with evidence-backed understanding. Uses the shared AI
    execution path (AIInfrastructureAdapter → ModelRouterService → provider → model).
    """

    # Deterministic fallback pattern from AIInfrastructureAdapter.generate_plan()
    # When routing fails, the adapter returns this deterministic string.
    _FALLBACK_PATTERNS = (
        "Implementation plan for",
        "analyze requirements, inspect files, apply edits, and verify.",
    )
    _MIN_OUTPUT_LENGTH = 50  # Real AI output must be substantive

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        # Invoke real AI infrastructure for research
        brief_content = ""
        routing_info = "unknown"

        if self._ai is None:
            # No AI provider configured — configuration error, not false success
            is_real_output = False
        else:
            try:
                # Build research-focused system context
                research_context = self._build_research_context(context)

                # Call the shared AI infrastructure
                brief_content = await self._ai.generate_plan(research_context)

                # Capture routing info from adapter if available
                if hasattr(self._ai, 'last_execution_result') and self._ai.last_execution_result:
                    result = self._ai.last_execution_result
                    routing_info = f"{result.provider_id}/{result.model_id}"
                else:
                    routing_info = "no-execution-result"

            except Exception as exc:
                # AI invocation failed — do NOT substitute deterministic content
                brief_content = ""
                routing_info = f"error: {type(exc).__name__}: {exc}"
                is_real_output = False
            else:
                # Evaluate: must have real AI output, not fallback
                is_real_output = self._is_real_ai_output(brief_content)

        produced_artifacts: list[ArtifactRecord] = []

        if is_real_output:
            brief_art = self._artifacts.record_artifact(
                name="research_brief.md",
                artifact_type=ArtifactType.SUMMARY,
                content=brief_content,
                provenance=provenance,
            )
            produced_artifacts.append(brief_art)
            eval_status = EvaluationStatus.PASSED
            findings = f"Research brief generated ({len(brief_content)} chars, routed via {routing_info})"
        else:
            # No real AI output — this is a failure, not a false success
            eval_status = EvaluationStatus.FAILED
            findings = f"AI research generation failed or returned fallback. routing={routing_info}"

        eval_res = EvaluationResult(
            status=eval_status,
            qualitative_findings=findings,
        )
        self._status = LoopStatus.COMPLETED if is_real_output else LoopStatus.FAILED
        return is_real_output, produced_artifacts, eval_res

    def _build_research_context(self, context: ExecutionContext) -> ExecutionContext:
        """Build a research-focused context for the AI."""
        from copy import copy
        research_ctx = copy(context)
        research_ctx.task_type = "research"
        research_ctx.task_description = (
            f"Research and analyze: {context.task_description or context.task_name}\n\n"
            "Provide a comprehensive domain investigation covering:\n"
            "1. Problem understanding and scope\n"
            "2. User needs and constraints\n"
            "3. Technology landscape and options\n"
            "4. Risks and tradeoffs\n"
            "5. Recommended approach and rationale"
        )
        return research_ctx


class ArchitectureLoop(SpecializedLoop):
    """
    Real AI-driven architecture loop.

    Invokes the AI infrastructure to produce system architecture covering
    components, interfaces, data flow, storage, APIs, runtime boundaries,
    and security considerations. Uses the shared AI execution path.
    """

    # Deterministic fallback pattern from AIInfrastructureAdapter.generate_plan()
    _FALLBACK_PATTERNS = (
        "Implementation plan for",
        "analyze requirements, inspect files, apply edits, and verify.",
    )
    _MIN_OUTPUT_LENGTH = 50

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        # Invoke real AI infrastructure for architecture
        proposal_content = ""
        routing_info = "unknown"

        if self._ai is None:
            is_real_output = False
        else:
            try:
                arch_context = self._build_architecture_context(context)
                proposal_content = await self._ai.generate_plan(arch_context)

                if hasattr(self._ai, 'last_execution_result') and self._ai.last_execution_result:
                    result = self._ai.last_execution_result
                    routing_info = f"{result.provider_id}/{result.model_id}"
                else:
                    routing_info = "no-execution-result"

            except Exception as exc:
                proposal_content = ""
                routing_info = f"error: {type(exc).__name__}: {exc}"
                is_real_output = False
            else:
                # Evaluate: must have real AI output
                is_real_output = self._is_real_ai_output(proposal_content)

        produced_artifacts: list[ArtifactRecord] = []

        if is_real_output:
            proposal_art = self._artifacts.record_artifact(
                name="architecture_proposal.md",
                artifact_type=ArtifactType.SUMMARY,
                content=proposal_content,
                provenance=provenance,
            )
            produced_artifacts.append(proposal_art)
            eval_status = EvaluationStatus.PASSED
            findings = f"Architecture proposal generated ({len(proposal_content)} chars, routed via {routing_info})"
        else:
            eval_status = EvaluationStatus.FAILED
            findings = f"AI architecture generation failed or returned fallback. routing={routing_info}"

        eval_res = EvaluationResult(
            status=eval_status,
            qualitative_findings=findings,
        )
        self._status = LoopStatus.COMPLETED if is_real_output else LoopStatus.FAILED
        return is_real_output, produced_artifacts, eval_res

    def _build_architecture_context(self, context: ExecutionContext) -> ExecutionContext:
        """Build an architecture-focused context for the AI."""
        from copy import copy
        arch_ctx = copy(context)
        arch_ctx.task_type = "architecture"
        arch_ctx.task_description = (
            f"Design the system architecture for: {context.task_description or context.task_name}\n\n"
            "Produce a comprehensive architecture proposal covering:\n"
            "1. Components and their responsibilities\n"
            "2. Interfaces and contracts between components\n"
            "3. Data flow and storage strategy\n"
            "4. Dependencies and integration points\n"
            "5. APIs and runtime boundaries\n"
            "6. Security considerations\n"
            "7. Scalability and operational characteristics"
        )
        return arch_ctx


class PlanningLoop(SpecializedLoop):
    """
    Real AI-driven planning loop.

    Invokes the AI infrastructure to transform available understanding into a
    structured execution plan (work breakdown structure) with objectives,
    workstreams, tasks, dependencies, sequencing, and acceptance considerations.
    Uses the shared AI execution path.
    """

    # Deterministic fallback pattern from AIInfrastructureAdapter.generate_plan()
    _FALLBACK_PATTERNS = (
        "Implementation plan for",
        "analyze requirements, inspect files, apply edits, and verify.",
    )
    _MIN_OUTPUT_LENGTH = 50

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        # Invoke real AI infrastructure for planning
        wbs_content = ""
        routing_info = "unknown"

        if self._ai is None:
            is_real_output = False
        else:
            try:
                plan_context = self._build_planning_context(context)
                wbs_content = await self._ai.generate_plan(plan_context)

                if hasattr(self._ai, 'last_execution_result') and self._ai.last_execution_result:
                    result = self._ai.last_execution_result
                    routing_info = f"{result.provider_id}/{result.model_id}"
                else:
                    routing_info = "no-execution-result"

            except Exception as exc:
                wbs_content = ""
                routing_info = f"error: {type(exc).__name__}: {exc}"
                is_real_output = False
            else:
                # Evaluate: must have real AI output
                is_real_output = self._is_real_ai_output(wbs_content)

        produced_artifacts: list[ArtifactRecord] = []

        if is_real_output:
            wbs_art = self._artifacts.record_artifact(
                name="work_breakdown_structure.md",
                artifact_type=ArtifactType.SUMMARY,
                content=wbs_content,
                provenance=provenance,
            )
            produced_artifacts.append(wbs_art)
            eval_status = EvaluationStatus.PASSED
            findings = f"Work breakdown structure generated ({len(wbs_content)} chars, routed via {routing_info})"
        else:
            eval_status = EvaluationStatus.FAILED
            findings = f"AI planning generation failed or returned fallback. routing={routing_info}"

        eval_res = EvaluationResult(
            status=eval_status,
            qualitative_findings=findings,
        )
        self._status = LoopStatus.COMPLETED if is_real_output else LoopStatus.FAILED
        return is_real_output, produced_artifacts, eval_res

    def _build_planning_context(self, context: ExecutionContext) -> ExecutionContext:
        """Build a planning-focused context for the AI."""
        from copy import copy
        plan_ctx = copy(context)
        plan_ctx.task_type = "planning"
        plan_ctx.task_description = (
            f"Create an execution plan for: {context.task_description or context.task_name}\n\n"
            "Produce a structured work breakdown covering:\n"
            "1. Objectives and success criteria\n"
            "2. Workstreams and major phases\n"
            "3. Tasks with clear deliverables\n"
            "4. Dependencies between tasks\n"
            "5. Sequencing and parallelization opportunities\n"
            "6. Acceptance considerations per workstream\n"
            "7. Risks and mitigations"
        )
        return plan_ctx


class UIDesignLoop(SpecializedLoop):
    """Real AI-driven UI design loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="ui_design",
            prompt_instruction=(
                "You are an expert UI/UX Designer. Produce a comprehensive UI Design Specification covering:\n"
                "1. User flows, interaction patterns, and visual hierarchy\n"
                "2. Layout grids, typography scale, spacing, and design tokens\n"
                "3. Component wireframes, states (default, hover, active, disabled, loading)\n"
                "4. Responsive design breakpoints and adaptivity\n"
                "5. Accessibility (WCAG 2.1 AA) considerations and color contrast"
            ),
            artifact_name="ui_design_specification.md",
        )


class BackendLoop(EngineeringLoop):
    """Specialized coding loop for Backend Engineering."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        if not context.task_type or context.task_type in ("general", "backend_engineer"):
            context.task_type = "backend"
        return await super().run(
            context=context,
            worker_id=worker_id,
            verification_commands=verification_commands,
            is_cancelled=is_cancelled,
        )


class FrontendLoop(EngineeringLoop):
    """Specialized coding loop for Frontend Engineering."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        if not context.task_type or context.task_type in ("general", "frontend_engineer"):
            context.task_type = "frontend"
        return await super().run(
            context=context,
            worker_id=worker_id,
            verification_commands=verification_commands,
            is_cancelled=is_cancelled,
        )


class DatabaseLoop(SpecializedLoop):
    """Real AI-driven database architecture and schema loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="database",
            prompt_instruction=(
                "You are an expert Database Architect and Engineer. Produce a database schema and data model specification covering:\n"
                "1. Entity-relationship model and entity definitions\n"
                "2. PostgreSQL DDL statements with tables, primary keys, and foreign keys\n"
                "3. Indexing strategy for query performance and constraints\n"
                "4. Data migration considerations and versioning\n"
                "5. Concurrency, isolation levels, and transactional integrity"
            ),
            artifact_name="db_schema.sql",
            artifact_type=ArtifactType.SOURCE_CODE,
        )


class MLLoop(SpecializedLoop):
    """Real AI-driven machine learning architecture and inference loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="ml",
            prompt_instruction=(
                "You are an expert Machine Learning Engineer. Produce an ML model and inference pipeline specification covering:\n"
                "1. Model architecture and candidate selection\n"
                "2. Feature engineering and data preprocessing pipelines\n"
                "3. Training and fine-tuning methodology and objective functions\n"
                "4. Inference latency, hardware constraints, and batching\n"
                "5. Evaluation metrics, validation strategy, and drift monitoring"
            ),
            artifact_name="ml_inference_plan.md",
        )


class InfrastructureLoop(SpecializedLoop):
    """Real AI-driven cloud infrastructure and IaC loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="infrastructure",
            prompt_instruction=(
                "You are an expert Cloud Infrastructure Engineer. Produce an Infrastructure as Code (IaC) specification covering:\n"
                "1. Cloud resource architecture and provisioning plan\n"
                "2. Networking, VPCs, subnets, and security groups\n"
                "3. Container orchestration / compute runtime configuration\n"
                "4. Secrets management and IAM least-privilege policies\n"
                "5. Disaster recovery and high-availability configuration"
            ),
            artifact_name="infrastructure_specification.md",
        )


class DevOpsLoop(SpecializedLoop):
    """Real AI-driven DevOps and CI/CD automation loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="devops",
            prompt_instruction=(
                "You are an expert DevOps Engineer. Produce a CI/CD pipeline and release automation specification covering:\n"
                "1. Automated build and packaging workflow\n"
                "2. Automated test stages (unit, integration, linting, security scans)\n"
                "3. Container image build, tagging, and registry push\n"
                "4. Deployment environments and promotion gates\n"
                "5. Rollback mechanisms and pipeline telemetry"
            ),
            artifact_name="cicd_pipeline_specification.md",
        )


class QALoop(SpecializedLoop):
    """Real AI-driven QA strategy and test automation loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="qa",
            prompt_instruction=(
                "You are an expert QA and Test Automation Engineer. Produce a QA test strategy and verification plan covering:\n"
                "1. Test coverage targets across unit, integration, and end-to-end tiers\n"
                "2. Specific test cases with setup, execution steps, and expected outcomes\n"
                "3. Edge cases, boundary values, and negative testing scenarios\n"
                "4. Automation framework and runner configuration\n"
                "5. Quality gates and regression criteria"
            ),
            artifact_name="qa_test_strategy.md",
        )


class SecurityLoop(SpecializedLoop):
    """Real AI-driven security threat modeling and audit loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="security",
            prompt_instruction=(
                "You are an expert Security Engineer. Produce a security threat model and vulnerability assessment covering:\n"
                "1. STRIDE threat modeling analysis of system components\n"
                "2. Attack surface identification and threat vectors\n"
                "3. Authentication, authorization, and cryptographic controls\n"
                "4. Input validation, sanitization, and OWASP Top 10 mitigation\n"
                "5. Audit logging, security monitoring, and incident response requirements"
            ),
            artifact_name="security_threat_model.md",
        )


class PerformanceLoop(SpecializedLoop):
    """Real AI-driven performance assessment and scalability loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="performance",
            prompt_instruction=(
                "You are an expert Performance and Scalability Engineer. Produce a performance assessment and optimization plan covering:\n"
                "1. Latency and throughput targets (p50, p95, p99 SLOs)\n"
                "2. Critical path analysis and identified bottlenecks\n"
                "3. Caching strategy (memory, Redis, HTTP caching)\n"
                "4. Database query optimization and connection pooling\n"
                "5. Load testing methodology and capacity sizing"
            ),
            artifact_name="performance_assessment.md",
        )


class DocumentationLoop(SpecializedLoop):
    """Real AI-driven technical documentation loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="documentation",
            prompt_instruction=(
                "You are an expert Technical Writer and Documentation Engineer. Produce comprehensive technical documentation covering:\n"
                "1. System overview and high-level architectural concepts\n"
                "2. Getting started guide and local development setup\n"
                "3. API reference with request/response schemas and examples\n"
                "4. Configuration parameters, environment variables, and defaults\n"
                "5. Troubleshooting guide and common operational procedures"
            ),
            artifact_name="technical_documentation.md",
        )


# ── Legacy Modernization Loops ────────────────────────────────────────────────

class LegacyDiscoveryLoop(SpecializedLoop):
    """
    Deterministic by design:
    Scans files in the workspace environment, detects technologies,
    extracts metadata deterministically using AST parsers, and produces a LegacySystemModel.
    """
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        model = LegacySystemModel(
            system_id=str(uuid.uuid4()),
            name=context.task_name,
            description=context.task_description,
        )

        root = getattr(self._env.filesystem, "root", None)
        files = []
        if root and root.exists():
            for p in root.rglob("*"):
                if p.is_file():
                    files.append(str(p.relative_to(root)))
        for f in files:
            content = self._env.filesystem.read_text(f)
            analyzer = get_analyzer_for_file(content, f)
            analysis = analyzer.analyze(content, f)

            lang = analysis.get("language", "UNKNOWN")
            model.technologies[lang] = FactState.FACT

            for sym in analysis.get("symbols", []):
                ev = LegacyEvidence(
                    evidence_id=str(uuid.uuid4())[:8],
                    source_file=f,
                    analyzer_id=analyzer.__class__.__name__,
                    observation=f"Extracted symbol: {sym}",
                    confidence=1.0,
                )
                model.record_evidence(ev)

            if "analysis_gap" in analysis:
                model.record_gap("Technology Ingestion", analysis["analysis_gap"], severity="medium")

        model_art = self._artifacts.record_artifact(
            name="legacy_system_model.json",
            artifact_type=ArtifactType.SUMMARY,
            content=model.model_dump_json(indent=2),
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings=f"Discovered {len(model.technologies)} technologies and {len(model.evidence_ledger)} evidence points.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [model_art], eval_res


class LegacyCodeArchaeologyLoop(SpecializedLoop):
    """Real AI-driven legacy code archaeology loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        file_summary = []
        root = getattr(self._env.filesystem, "root", None)
        if root and root.exists():
            for p in list(root.rglob("*"))[:20]:
                if p.is_file():
                    try:
                        content_sample = self._env.filesystem.read_text(str(p.relative_to(root)))[:300]
                        file_summary.append(f"File: {p.relative_to(root)}\n{content_sample}\n---")
                    except Exception:
                        pass
        code_context = "\n".join(file_summary) if file_summary else "No source files found in workspace."

        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="code_archaeology",
            prompt_instruction=(
                "You are an expert Legacy Code Archaeologist. Analyze the legacy codebase structure and produce archaeology findings covering:\n"
                "1. Main entry points and batch execution interfaces\n"
                "2. Shared global state and data coupling structures\n"
                "3. Dead or unreachable code blocks\n"
                "4. Idiomatic language patterns and dialects\n"
                "5. Technical debt and hidden risks\n\n"
                f"Workspace Source Code Samples:\n{code_context[:3000]}"
            ),
            artifact_name="code_archaeology_finding.md",
        )


class BusinessRuleExtractionLoop(SpecializedLoop):
    """
    Deterministic by design:
    Scans for business rules using regex / pattern rules and returns a structured rule list with evidence.
    """
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        root = getattr(self._env.filesystem, "root", None)
        files = []
        if root and root.exists():
            for p in root.rglob("*"):
                if p.is_file():
                    files.append(str(p.relative_to(root)))
        rules = []
        for f in files:
            content = self._env.filesystem.read_text(f)
            if "IF" in content or "compute" in content:
                ev = LegacyEvidence(
                    evidence_id=str(uuid.uuid4())[:8],
                    source_file=f,
                    analyzer_id="BusinessRulesAnalyst",
                    observation="Calculation logic matching IF/COMPUTE statements",
                    confidence=0.9,
                )
                rule = BusinessRule(
                    rule_id=f"rule_{len(rules) + 1}",
                    statement=f"Calculate output values using rules defined in {f}",
                    evidence=[ev],
                    state=FactState.FACT,
                )
                rules.append(rule)

        rules_art = self._artifacts.record_artifact(
            name="business_rules_list.json",
            artifact_type=ArtifactType.SUMMARY,
            content=f"[{','.join(r.model_dump_json(indent=2) for r in rules)}]" if rules else "[]",
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings=f"Extracted {len(rules)} business rules.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [rules_art], eval_res


class ModernizationArchitectureLoop(SpecializedLoop):
    """Real AI-driven modernization architecture proposal loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="modernization_architecture",
            prompt_instruction=(
                "You are an expert Modernization Architect. Produce a comprehensive modernization proposal covering:\n"
                "1. Modernization strategy (Strangler Fig, Rehost, Refactor, Replatform)\n"
                "2. Target technology stack and cloud-native architecture\n"
                "3. Incremental cutover plan and anti-corruption layer design\n"
                "4. Data synchronization between legacy and target systems\n"
                "5. Risk mitigation and architectural governance"
            ),
            artifact_name="modernization_proposal.md",
        )


class LegacyArchitectureReconstructionLoop(SpecializedLoop):
    """Real AI-driven legacy architecture reconstruction loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="architecture_reconstruction",
            prompt_instruction=(
                "You are an expert Legacy Architecture Analyst. Reconstruct the legacy system architecture covering:\n"
                "1. Monolithic component boundaries and module responsibilities\n"
                "2. Inter-subsystem communication and coupling mechanisms\n"
                "3. Persistence layer architecture and shared datastores\n"
                "4. Runtime execution environments and deployment topology\n"
                "5. Architecture drift and technical constraints"
            ),
            artifact_name="legacy_reconstruction.md",
        )


class LegacyDataAnalysisLoop(SpecializedLoop):
    """Real AI-driven legacy data analysis loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="legacy_data",
            prompt_instruction=(
                "You are an expert Legacy Data Engineer. Analyze legacy data storage and schemas covering:\n"
                "1. Schema layouts, copybooks, record definitions, and field encodings (EBCDIC/ASCII/packed decimal)\n"
                "2. Relational and non-relational datastores (VSAM, DB2, IMS, flat files)\n"
                "3. Referential integrity and implicit data dependencies\n"
                "4. Target schema mapping and normalization recommendations\n"
                "5. Data migration and validation strategy"
            ),
            artifact_name="legacy_data_analysis.md",
        )


class LegacyIntegrationAnalysisLoop(SpecializedLoop):
    """Real AI-driven legacy integration analysis loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="legacy_integration",
            prompt_instruction=(
                "You are an expert Legacy Integration Engineer. Analyze external interfaces and system boundaries covering:\n"
                "1. External APIs, web services, and remote procedure calls\n"
                "2. Messaging systems (MQ Series, message brokers, queues)\n"
                "3. Batch file exchange formats (FTP, EDI, fixed-width records)\n"
                "4. Authentication and network boundary protocols\n"
                "5. Integration risk points during modernization"
            ),
            artifact_name="legacy_integration_analysis.md",
        )


class DependencyImpactAnalysisLoop(SpecializedLoop):
    """Real AI-driven dependency and impact analysis loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="dependency_impact_analysis",
            prompt_instruction=(
                "You are an expert Dependency and Impact Analyst. Analyze the blast radius and dependencies covering:\n"
                "1. Direct and transitive component dependencies\n"
                "2. High-risk tightly coupled modules\n"
                "3. Blast radius of proposed changes or migrations\n"
                "4. Circular dependencies and shared state hazards\n"
                "5. Recommended decoupling sequence"
            ),
            artifact_name="dependency_impact_analysis.md",
        )


class MigrationPlanningLoop(SpecializedLoop):
    """Real AI-driven migration planning and cutover loop."""

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        return await self._run_ai_specialized_task(
            context=context,
            worker_id=worker_id,
            task_type="migration_planning",
            prompt_instruction=(
                "You are an expert Migration Planning Engineer. Produce a phased migration plan covering:\n"
                "1. Phase-by-phase execution sequencing and work packages\n"
                "2. Cutover milestones and dependency prerequisites\n"
                "3. Rollback plans and failure recovery criteria\n"
                "4. Resource requirements and execution timeline\n"
                "5. Validation checkpoints and signoff criteria"
            ),
            artifact_name="migration_plan.md",
        )


# ── Mapping from Loop Type to Class ─────────────────────────────────────────

_LOOP_CLASSES: dict[str, type[EngineeringLoop]] = {
    # Greenfield
    "research": ResearchLoop,
    "architecture": ArchitectureLoop,
    "planning": PlanningLoop,
    "ui_design": UIDesignLoop,
    "backend": BackendLoop,
    "frontend": FrontendLoop,
    "database": DatabaseLoop,
    "ml": MLLoop,
    "infrastructure": InfrastructureLoop,
    "devops": DevOpsLoop,
    "qa": QALoop,
    "security": SecurityLoop,
    "performance": PerformanceLoop,
    "documentation": DocumentationLoop,
    # Legacy
    "legacy_discovery": LegacyDiscoveryLoop,
    "legacy_code_archaeology": LegacyCodeArchaeologyLoop,
    "legacy_architecture_reconstruction": LegacyArchitectureReconstructionLoop,
    "legacy_data_analysis": LegacyDataAnalysisLoop,
    "legacy_integration_analysis": LegacyIntegrationAnalysisLoop,
    "business_rule_extraction": BusinessRuleExtractionLoop,
    "dependency_impact_analysis": DependencyImpactAnalysisLoop,
    "modernization_architecture": ModernizationArchitectureLoop,
    "migration_planning": MigrationPlanningLoop,
}

def get_loop_class(loop_type: str) -> type[EngineeringLoop]:
    return _LOOP_CLASSES.get(loop_type, EngineeringLoop)
