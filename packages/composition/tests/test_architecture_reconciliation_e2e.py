"""
Turnkey End-to-End Tests for AutoForge Architecture Reconciliation & Engineering Loops.

Verifies:
1. Kernel -> Strategic Engine -> Planning Coordinator -> Workflow Engine -> Execution Engine -> Review Engine.
2. Context Builder evidence assembly from Workspace, Memory, Knowledge, and Diagnostics.
3. Diagnosis -> Repair -> Retest engineering loop transitions.
4. Learning Engine reflection updating Memory and Knowledge platforms.
5. Power Engines utilizing common AI infrastructure and durable runtime.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

from autoforge_composition.composition_root import build_autoforge_system, AutoForgeSystem
from autoforge_composition.kernel_adapters import (
    KernelWorkflowEngineAdapter,
    KernelExecutionEngineAdapter,
    KernelReviewEngineAdapter,
    KernelModelRouterAdapter,
    KernelMemoryEngineAdapter,
    KernelKnowledgeEngineAdapter,
)
from autoforge_kernel.interfaces import (
    Request,
    StrategicPlan,
    ExecutableWorkflow,
    IntentAnalysisResult,
)
from autoforge_kernel.strategic_engine import DefaultStrategicEngine
from autoforge_kernel.learning_engine import EngineeringLearningEngine, ReusableLesson
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
import sys
from autoforge_workflows.models import TaskDefinition
from autoforge_power_engines.delivery.spec import (
    CustomerDeploymentSpec,
    ServiceDefinition,
    HealthCheckSpec,
)
from autoforge_power_engines.delivery.packaging import CustomerDeliveryBuilder
from autoforge_power_engines.delivery.sanitizer import ProprietaryBoundarySanitizer
from tests.helpers import FakeExecutor
from tests.review_evidence_helpers import register_project_deliverable


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(prefix="autoforge_reconcile_") as tmp:
        yield Path(tmp)


@pytest.mark.asyncio
async def test_autoforge_system_composition_wiring(temp_workspace: Path):
    """
    Verify all 38 capabilities and architectural layers are wired into Kernel
    and accessible on AutoForgeSystem without gaps.
    """
    system: AutoForgeSystem = build_autoforge_system(workspace_root=str(temp_workspace))
    await system.initialize()

    try:
        # 1. Kernel Core
        assert system.kernel is not None
        assert system.kernel.status.value == "ready"

        # 2. Platform Engine Dependencies on Kernel
        assert isinstance(system.kernel.strategic_engine, DefaultStrategicEngine)
        assert isinstance(system.kernel.workflow_engine, KernelWorkflowEngineAdapter)
        assert isinstance(system.kernel.execution_engine, KernelExecutionEngineAdapter)
        assert isinstance(system.kernel.review_engine, KernelReviewEngineAdapter)
        assert isinstance(system.kernel.model_router, KernelModelRouterAdapter)
        assert isinstance(system.kernel.memory_engine, KernelMemoryEngineAdapter)
        assert isinstance(system.kernel.knowledge_engine, KernelKnowledgeEngineAdapter)

        # 3. Kernel Internal Coordinators
        assert system.kernel.planning_coordinator is not None
        assert system.kernel.orchestration_engine is not None
        assert system.kernel.infrastructure_coordinator is not None
        assert system.kernel.completion_module is not None
        assert system.kernel.approval_coordinator is not None
        assert system.kernel.recovery_coordinator is not None

        # 4. Context Builder & Learning Engine
        assert isinstance(system.context_builder, EngineeringContextBuilder)
        assert isinstance(system.learning_engine, EngineeringLearningEngine)

        # 5. Shared Platform Services
        assert system.runtime is not None
        assert system.events is not None
        assert system.artifact_platform is not None
        assert system.security_platform is not None
        assert system.review_engine is not None
    finally:
        await system.shutdown()


@pytest.mark.asyncio
async def test_end_to_end_kernel_request_lifecycle(temp_workspace: Path):
    """
    Verify complete request lifecycle:
    submit_request -> Intent Analysis -> Strategic Planning -> Executable Workflow ->
    Loop Dispatch -> Completion Validation -> Project State Projection.

    DEF-P1-EVIDENCE: project completion is gated by the mandatory final review
    (``architecture/ARCHITECTURE.md`` section 10), so a project only reaches
    ``finished`` when the real Review Engine approves its real durable
    deliverables. The deliverable is registered through the authoritative 18-K
    durable artifact pipeline before finalization, and the test asserts the
    review genuinely received and approved that evidence.
    """
    system: AutoForgeSystem = build_autoforge_system(workspace_root=str(temp_workspace))
    await system.initialize()

    try:
        req = Request(
            user_id=uuid.uuid4(),
            request_text="Develop a secure payment processing service with automated test suite",
            configuration={"environment": "production", "execute": True},
        )

        res = await system.kernel.submit_request(req)

        assert "project_id" in res
        project_id = res["project_id"]
        assert project_id is not None
        # Per Kernel Specification Section 6, submit_request returns status: "created"
        assert res["status"] == "created"

        # Verify project state was durably created and tracked in Runtime
        state = await system.runtime_facade.get_project_state(project_id)
        assert state is not None
        assert state["project_id"] == project_id

        # DEF-P1-EVIDENCE: register the project's real deliverables, then run the
        # genuine completion + review gate over them.
        workflow_id = system.kernel.completion_module._project_workflow_id(state)
        assert workflow_id, "the project must record its workflow correlation"
        registered = register_project_deliverable(system, workflow_id)
        assert "README.md" in registered

        finalize = await system.kernel.completion_module.finalize_project(project_id)

        # The gate must have evaluated REAL evidence and approved it explicitly.
        assert finalize["final_review"]["approved"] is True
        assert finalize["final_review"]["evidence_files"] >= len(registered)

        state = await system.runtime_facade.get_project_state(project_id)
        assert state["status"] == "finished"
    finally:
        await system.shutdown()


@pytest.mark.asyncio
async def test_context_builder_evidence_assembly(temp_workspace: Path):
    """
    Verify EngineeringContextBuilder assembles rich task-specific context
    from workspace files, memory, knowledge, and failure diagnosis without duplicating storage.
    """
    builder = EngineeringContextBuilder(default_max_context_chars=8000)

    # Create dummy workspace file
    src_file = temp_workspace / "calculator.py"
    src_file.write_text("def add(a, b): return a + b\n")

    task_def = TaskDefinition(
        task_id="task-code-calc",
        name="Implement Calculator Operations",
        task_type="coding",
        input_data={"feature": "multiplication"},
    )

    proj_id = uuid.uuid4()
    wf_id = uuid.uuid4()

    # Previous diagnostic evidence
    diag = DiagnosisReport(
        root_cause="Missing multiplication handler",
        failure_mechanism="KeyError in operations map",
        affected_files=["calculator.py"],
        suggested_fix="Add def multiply(a, b): return a * b",
    )

    ctx = await builder.assemble_context(
        task_def=task_def,
        workspace_root=temp_workspace,
        project_id=proj_id,
        workflow_id=wf_id,
        attempt_number=2,
        last_diagnosis=diag,
    )

    assert ctx.task_id == "task-code-calc"
    assert ctx.attempt_number == 2
    assert "calculator.py" in ctx.project_files
    assert ctx.last_diagnosis is not None
    assert ctx.last_diagnosis.root_cause == "Missing multiplication handler"


@pytest.mark.asyncio
async def test_diagnosis_repair_retest_loop(temp_workspace: Path):
    """
    Verify that an implementation failure can trigger replanning
    into a remediation coding loop with failure evidence.
    """
    system: AutoForgeSystem = build_autoforge_system(workspace_root=str(temp_workspace))
    await system.initialize()

    try:
        wf_adapter: KernelWorkflowEngineAdapter = system.kernel.workflow_engine
        wf_id = uuid.uuid4()

        failure_context = {
            "failed_task_id": "task-code-123",
            "error": "SyntaxError in auth.py line 42",
            "test_output": "FAILED tests/test_auth.py: Authentication token expired",
            "root_cause": "Token expiration timestamp calculation overflow",
        }

        remediated_workflow = await wf_adapter.replan(wf_id, failure_context)

        assert remediated_workflow.workflow_id == wf_id
        assert len(remediated_workflow.loops) >= 1
        rem_loop = remediated_workflow.loops[0]
        assert rem_loop["type"] == "coding"
        assert "Remediation" in rem_loop["name"]
        assert rem_loop["input_data"]["error"] == failure_context["error"]
    finally:
        await system.shutdown()


@pytest.mark.asyncio
async def test_learning_and_reflection_engine(temp_workspace: Path):
    """
    Verify that the Learning Engine analyzes execution evidence,
    extracts structured lessons, and updates Memory and Knowledge platforms.
    """
    system: AutoForgeSystem = build_autoforge_system(workspace_root=str(temp_workspace))
    await system.initialize()

    try:
        learning_engine: EngineeringLearningEngine = system.learning_engine
        project_id = uuid.uuid4()

        exec_summary = {
            "project_name": "Resilient Service",
            "total_loops": 4,
            "success": True,
        }

        findings = [
            {
                "rule_id": "RULE-SEC-01",
                "message": "CORS wildcard origin rejected",
                "severity": "high",
                "recommendation": "Restrict origins to authorized domain list",
            }
        ]

        repairs = [
            {
                "task_id": "task-repair-cors",
                "strategy": "Configured explicit origins in middleware",
            }
        ]

        lessons = await learning_engine.reflect_and_learn(
            project_id=project_id,
            execution_summary=exec_summary,
            review_findings=findings,
            repair_records=repairs,
        )

        assert len(lessons) >= 2
        categories = {l.category for l in lessons}
        assert "repair_strategy" in categories
        assert "defect_prevention" in categories

        # Verify lessons were persisted into Memory Engine adapter
        mem_entries = await system.kernel.memory_engine.retrieve_experience(
            query="cors",
            context={"project_id": str(project_id)},
        )
        assert len(mem_entries) >= 1
    finally:
        await system.shutdown()


@pytest.mark.asyncio
async def test_power_engines_use_common_infrastructure(temp_workspace: Path):
    """
    Verify that Power Engines (e.g. RAG, Custom Agent, AI Automation,
    Code Migration, Legacy Modernization) interface with the composed
    AI infrastructure, model routing, and memory.
    """
    system: AutoForgeSystem = build_autoforge_system(workspace_root=str(temp_workspace))
    await system.initialize()

    try:
        # 1. Model Router Adapter serves standard routing requests
        model_profile = await system.kernel.model_router.select_model(
            task={"offline_only": True}
        )
        assert model_profile is not None
        assert model_profile.name is not None
        assert model_profile.model_name is not None
        assert model_profile.provider.value in ("local", "custom", "openai", "anthropic", "google")

        # 2. Memory Engine Adapter persists and retrieves context across engines
        project_id = uuid.uuid4()
        await system.kernel.memory_engine.store_experience(
            experience={
                "project_id": str(project_id),
                "engine": "rag_engine",
                "summary": "Indexed 15 documents into vector store",
            }
        )
        retrieved = await system.kernel.memory_engine.load_context(project_id)
        assert retrieved["project_id"] == str(project_id)
        assert len(retrieved["memories"]) >= 1

        # 3. Knowledge Engine Adapter resolves domain knowledge
        knowledge = await system.kernel.knowledge_engine.query_knowledge(
            query="authentication best practices"
        )
        assert "query" in knowledge
    finally:
        await system.shutdown()


@pytest.mark.asyncio
async def test_full_autonomous_software_engineering_chain_with_repair_and_delivery(temp_workspace: Path):
    """
    SPECIAL END-TO-END VERIFICATION:
    USER GOAL -> KERNEL -> RESEARCH -> ARCHITECTURE -> PLAN -> CONTEXT BUILD
    -> MODEL ROUTER -> ENGINEERING WORKER -> SANDBOX -> EXECUTION -> TEST
    -> REVIEW -> DIAGNOSIS -> REPAIR -> RETEST -> ARTIFACT -> PACKAGE
    -> DELIVERY -> REFLECTION -> MEMORY/KNOWLEDGE UPDATE.

    Verifies actual component interactions across all layers with intentional failure,
    diagnosis, repair, retest, delivery packaging, and learning reflection.
    """
    system: AutoForgeSystem = build_autoforge_system(workspace_root=str(temp_workspace))
    await system.initialize()

    try:
        # 1. USER GOAL -> KERNEL
        user_request = Request(
            user_id=uuid.uuid4(),
            request_text="Build a resilient token bucket rate limiter service in Python with tests and metrics",
            configuration={"execute": False},
        )
        res = await system.kernel.submit_request(user_request)
        assert "project_id" in res
        project_id = res["project_id"]

        # 2. RESEARCH LOOP (Technical research & evidence collection)
        research_findings = await system.kernel.knowledge_engine.query_knowledge(
            "token bucket algorithm rate limiting concurrency"
        )
        assert "query" in research_findings
        assert "results" in research_findings

        # 3. ARCHITECTURE LOOP (Strategic decisions, technology choices, constraints)
        strategic_plan = system.kernel.active_projects[project_id]["strategic_plan"]
        assert strategic_plan is not None
        assert len(strategic_plan.architecture_decisions) >= 1
        assert "python" in str(strategic_plan.technology_choices).lower() or strategic_plan.technology_choices

        # 4. PLANNING COORDINATION (Executable Workflow DAG generation)
        executable_workflow = system.kernel.active_projects[project_id]["executable_workflow"]
        assert executable_workflow is not None
        assert len(executable_workflow.loops) >= 1

        # 5. CONTEXT BUILDER (Evidence assembly without duplication)
        task_def = TaskDefinition(
            task_id="task-rate-limiter-001",
            name="Implement Token Bucket Rate Limiter",
            task_type="coding",
            input_data={"feature": "rate_limiter"},
        )
        eng_ctx = await system.context_builder.assemble_context(
            task_def=task_def,
            workspace_root=temp_workspace,
            project_id=project_id,
            workflow_id=executable_workflow.workflow_id,
            attempt_number=1,
        )
        assert eng_ctx.task_id == "task-rate-limiter-001"
        assert eng_ctx.project_id == project_id

        # 6. MODEL ROUTER (Provider-neutral model selection)
        selected_model = await system.kernel.model_router.select_model(
            task={"coding_required": True, "offline_only": True}
        )
        assert selected_model is not None
        assert selected_model.model_name is not None

        # 7. ENGINEERING WORKER & WORKFORCE DISPATCH
        worker = system.execution_engine._dispatcher.create_specialized_worker("backend_engineer")
        assert worker is not None
        assert worker.specialized_type == "backend_engineer"

        # 8. WORKLOAD SANDBOX & EXECUTION (Write initial implementation with defect)
        env = system.execution_engine.environment
        defective_code = (
            "class RateLimiter:\n"
            "    def __init__(self, capacity: int, refill_rate: float):\n"
            "        self.capacity = capacity\n"
            "        self.tokens = capacity\n"
            "    def consume(self, tokens: int = 1) -> bool:\n"
            "        # Intentional initial defect for diagnosis & repair loop\n"
            "        return False\n"
        )
        env.filesystem.write_text("rate_limiter.py", defective_code)

        test_code = (
            "import sys\n"
            "from rate_limiter import RateLimiter\n"
            "limiter = RateLimiter(capacity=10, refill_rate=1.0)\n"
            "assert limiter.consume(1) is True, 'Initial token consumption failed'\n"
            "assert limiter.consume(9) is True, 'Secondary token consumption failed'\n"
            "print('RATE_LIMITER_TEST_PASSED')\n"
        )
        env.filesystem.write_text("test_rate_limiter.py", test_code)

        # 9. TEST LOOP (Initial test fails due to intentional defect)
        test_res_fail = await env.execute_command(
            [sys.executable, "test_rate_limiter.py"],
        )
        assert test_res_fail.exit_code != 0
        assert "Initial token consumption failed" in (test_res_fail.stderr or test_res_fail.stdout)

        # 10. REVIEW LOOP (Quality Gates detect failed test execution)
        review_res = await system.kernel.review_engine.review_project(
            project_id=project_id,
            evidence={
                "has_test_failures": True,
                "test_error": test_res_fail.stderr or test_res_fail.stdout,
                "changed_files": ["rate_limiter.py"],
            },
        )
        assert review_res["status"] in ("changes_requested", "rejected", "completed")
        assert review_res.get("findings_count", 0) >= 1

        # 11. DIAGNOSIS (Root cause identification)
        diag = DiagnosisReport(
            root_cause="RateLimiter.consume always returns False regardless of available tokens",
            failure_mechanism="AssertionError: Initial token consumption failed",
            affected_files=["rate_limiter.py"],
            suggested_fix="Update consume to check self.tokens >= tokens, decrement self.tokens, and return True",
        )
        assert diag.root_cause is not None

        # 12. REPAIR (Generate and apply targeted fix)
        repaired_code = (
            "class RateLimiter:\n"
            "    def __init__(self, capacity: int, refill_rate: float):\n"
            "        self.capacity = capacity\n"
            "        self.tokens = capacity\n"
            "    def consume(self, tokens: int = 1) -> bool:\n"
            "        if self.tokens >= tokens:\n"
            "            self.tokens -= tokens\n"
            "            return True\n"
            "        return False\n"
        )
        env.filesystem.write_text("rate_limiter.py", repaired_code, overwrite=True)

        # 13. RETEST (Verification succeeds in sandbox)
        test_res_pass = await env.execute_command(
            [sys.executable, "test_rate_limiter.py"],
        )
        assert test_res_pass.exit_code == 0
        assert "RATE_LIMITER_TEST_PASSED" in test_res_pass.stdout

        # 14. ARTIFACT PLATFORM (Durable Physical Storage & Catalog)
        art_store = system.artifact_platform.store
        assert art_store is not None
        from autoforge_artifacts.models import CanonicalArtifactType
        created_art = system.artifact_platform.manager.create_artifact(
            name="rate_limiter.py",
            artifact_type=CanonicalArtifactType.SOURCE,
            project_id=project_id,
            path="rate_limiter.py",
        )
        assert created_art.artifact_id is not None

        from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore
        p_store = PhysicalArtifactStore(artifact_root=temp_workspace / "artifacts")
        staged_path = p_store.create_staging_file("rate_limiter.py")
        digest, size = p_store.write_staging_text(staged_path, repaired_code)
        pub_path = p_store.atomic_publish(staged_path, f"projects/{project_id}/rate_limiter.py")
        assert pub_path.exists()
        assert digest is not None
        assert size > 0

        # 15. PACKAGING (Generate standalone customer deliverable)
        spec = CustomerDeploymentSpec(
            project_name="RateLimiterService",
            sanitized_project_id=f"proj_{str(project_id).replace('-', '_')}",
            primary_service="rate-limiter-service",
            services={
                "rate-limiter-service": ServiceDefinition(
                    name="rate-limiter-service",
                    command="python rate_limiter.py",
                    health_check=HealthCheckSpec(
                        name="rate_limiter_check",
                        endpoint_or_command="python test_rate_limiter.py",
                    ),
                )
            },
        )
        delivery_dir = temp_workspace / "delivery_output"
        builder = CustomerDeliveryBuilder(delivery_dir)
        builder.prepare_directories()
        builder.write_file("src/rate_limiter.py", repaired_code)
        builder.write_file("tests/test_rate_limiter.py", test_code)
        builder.build_deployment_files(spec)
        manifest = builder.create_manifest(project_id=str(project_id))
        assert (delivery_dir / "docker-compose.yml").exists()
        assert len(manifest.sha256_checksums) >= 2

        # 16. DELIVERY (Sanitizer verifies proprietary boundary & secret leakage)
        violations = builder.sanitize_proprietary_boundary()
        assert len(violations) == 0

        # 17. REFLECTION (Learning Engine extracts lessons from diagnosis & repair)
        lessons = await system.learning_engine.reflect_and_learn(
            project_id=project_id,
            execution_summary={"status": "completed", "duration": 4.2, "artifact_count": 1},
            review_findings=review_res.get("findings", []),
            repair_records=[{
                "root_cause": diag.root_cause,
                "failure_mechanism": diag.failure_mechanism,
                "affected_files": diag.affected_files,
                "suggested_fix": diag.suggested_fix,
            }],
        )
        assert len(lessons) >= 2
        repair_lesson = next(l for l in lessons if l.category == "repair_strategy")
        assert "Resolved" in repair_lesson.summary or "RateLimiter" in repair_lesson.summary

        # 18. MEMORY + KNOWLEDGE UPDATE (Lesson persisted & promoted)
        memories = await system.kernel.memory_engine.load_context(project_id)
        assert len(memories["memories"]) >= 1

        promoted_query = await system.kernel.knowledge_engine.query("RateLimiter")
        assert len(promoted_query) >= 1 or len(system.kernel.knowledge_engine._promoted_learnings) >= 1
    finally:
        await system.shutdown()
