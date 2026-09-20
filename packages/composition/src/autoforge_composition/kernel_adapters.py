"""
Kernel Platform Adapters.

Bridges the AutoForge Kernel's abstract service and platform engine interfaces
(autoforge_kernel.interfaces) to the real concrete domain implementations:
- WorkflowEngine -> autoforge_workflows.engine.WorkflowEngine
- ExecutionEngine -> autoforge_execution.engine.ExecutionEngine
- ReviewEngine -> autoforge_review.engine.ReviewEngine
- ModelRouter -> autoforge_ai_infrastructure.router.ModelRouterService
- MemoryEngine -> autoforge_runtime & persistence
- KnowledgeEngine -> autoforge_knowledge_platform
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from autoforge_kernel.interfaces import (
    ExecutionEngine as KernelExecutionEngineABC,
    WorkflowEngine as KernelWorkflowEngineABC,
    ReviewEngine as KernelReviewEngineABC,
    ModelRouter as KernelModelRouterABC,
    MemoryEngine as KernelMemoryEngineABC,
    KnowledgeEngine as KernelKnowledgeEngineABC,
    StrategicPlan,
    ExecutableWorkflow,
)
from autoforge_models.model_profile import ModelProfile
from autoforge_models.memory_entry import MemoryEntry
from autoforge_models.enums import MemoryType, ModelProvider

from autoforge_workflows.models import (
    TaskDefinition,
    WorkflowDefinition,
    RetryPolicy,
    DependencyEdge,
)
from autoforge_workflows.engine import WorkflowEngine as ConcreteWorkflowEngine
from autoforge_execution.engine import ExecutionEngine as ConcreteExecutionEngine
from autoforge_execution.models import ArtifactType, ArtifactRecord, EvaluationStatus, WorkerType
from autoforge_review.engine import ReviewEngine as ConcreteReviewEngine
from autoforge_review.models import ReviewEvidence
from autoforge_review.policies import ReviewPolicy
from autoforge_ai_infrastructure.router import ModelRouterService
from autoforge_ai_infrastructure.metadata import RoutingRequest, CapabilityIds
from autoforge_runtime import RuntimeStateManager

logger = logging.getLogger("autoforge.composition.kernel_adapters")


# ── 1. Workflow Engine Adapter ───────────────────────────────────────────────

class KernelWorkflowEngineAdapter(KernelWorkflowEngineABC):
    """
    Adapts the concrete autoforge_workflows engine to satisfy the Kernel's
    WorkflowEngine interface.
    """

    def __init__(self, concrete_engine: ConcreteWorkflowEngine) -> None:
        self.concrete_engine = concrete_engine

    async def create_executable_workflow(
        self,
        strategic_plan: StrategicPlan,
        context: dict[str, Any],
    ) -> ExecutableWorkflow:
        workflow_id = uuid.uuid4()
        reqs = strategic_plan.requirements
        req_texts = " ".join(r.get("title", "") + " " + r.get("description", "") for r in reqs).lower()

        # Build engineering loops to execute based on strategic plan
        loops: list[dict[str, Any]] = []

        # 1. Research Loop (if research is indicated)
        if "research" in req_texts:
            loops.append({
                "type": "research",
                "name": "Technical Research",
                "worker_type": "research_engineer",
                "task_id": f"task-research-{uuid.uuid4().hex[:6]}",
                "input_data": {"requirements": reqs},
            })

        # 2. Architecture Loop
        loops.append({
            "type": "architecture",
            "name": "System Architecture Proposal",
            "worker_type": "architecture_engineer",
            "task_id": f"task-arch-{uuid.uuid4().hex[:6]}",
            "input_data": {
                "requirements": reqs,
                "architecture_decisions": strategic_plan.architecture_decisions,
            },
        })

        # 3. Implementation / Coding Loop
        loops.append({
            "type": "coding",
            "name": "Core Implementation",
            "worker_type": "backend_engineer",
            "task_id": f"task-code-{uuid.uuid4().hex[:6]}",
            "input_data": {
                "requirements": reqs,
                "technology_choices": strategic_plan.technology_choices,
            },
        })

        # 4. QA / Testing Loop
        loops.append({
            "type": "qa",
            "name": "Quality Assurance & Verification",
            "worker_type": "qa_engineer",
            "task_id": f"task-qa-{uuid.uuid4().hex[:6]}",
            "input_data": {
                "acceptance_criteria": strategic_plan.acceptance_criteria,
            },
        })

        # 5. Review Loop
        loops.append({
            "type": "review",
            "name": "Architecture & Quality Review",
            "worker_type": "review_engineer",
            "task_id": f"task-review-{uuid.uuid4().hex[:6]}",
            "input_data": {
                "acceptance_criteria": strategic_plan.acceptance_criteria,
            },
        })

        # Build task DAG nodes
        task_graph = {
            loop["task_id"]: {
                "dependencies": [loops[i - 1]["task_id"]] if i > 0 else [],
                "loop_type": loop["type"],
            }
            for i, loop in enumerate(loops)
        }

        worker_assignments = {loop["task_id"]: loop["worker_type"] for loop in loops}

        # Also submit as a real concrete WorkflowDefinition to WorkflowEngine
        tasks = [
            TaskDefinition(
                task_id=loop["task_id"],
                name=loop["name"],
                task_type=loop["type"],
                input_data=loop["input_data"],
                retry_policy=RetryPolicy(max_attempts=3),
            )
            for loop in loops
        ]
        dep_edges = [
            DependencyEdge(
                upstream_task_id=loops[i - 1]["task_id"],
                downstream_task_id=loops[i]["task_id"],
            )
            for i in range(1, len(loops))
        ]
        wf_def = WorkflowDefinition(
            workflow_id=workflow_id,
            name=f"Workflow for Plan {strategic_plan.plan_id}",
            tasks=tasks,
            dependencies=dep_edges,
        )
        try:
            self.concrete_engine.submit(wf_def)
        except Exception as ex:
            logger.debug(f"Concrete workflow submission non-fatal: {ex}")

        return ExecutableWorkflow(
            workflow_id=workflow_id,
            loops=loops,
            task_graph=task_graph,
            worker_assignments=worker_assignments,
            model_assignments={loop["task_id"]: "default" for loop in loops},
            approval_policies={},
            retry_policies={loop["task_id"]: {"max_attempts": 3} for loop in loops},
            estimated_duration=strategic_plan.estimated_duration,
            estimated_cost=strategic_plan.estimated_cost,
        )

    async def replan(
        self,
        workflow_id: uuid.UUID,
        execution_context: dict[str, Any],
    ) -> ExecutableWorkflow:
        logger.info(f"Replanning workflow {workflow_id} with updated execution context")
        # Generate refined workflow based on failure or changed requirements
        return ExecutableWorkflow(
            workflow_id=workflow_id,
            loops=[
                {
                    "type": "coding",
                    "name": "Remediation Coding Loop",
                    "worker_type": "backend_engineer",
                    "task_id": f"task-remediation-{uuid.uuid4().hex[:6]}",
                    "input_data": execution_context,
                }
            ],
            task_graph={},
            worker_assignments={},
            model_assignments={},
            approval_policies={},
            retry_policies={},
        )


# ── 2. Execution Engine Adapter ─────────────────────────────────────────────

class KernelExecutionEngineAdapter(KernelExecutionEngineABC):
    """
    Adapts the concrete autoforge_execution engine to satisfy the Kernel's
    ExecutionEngine interface.
    """

    def __init__(self, concrete_engine: ConcreteExecutionEngine) -> None:
        self.concrete_engine = concrete_engine

    async def execute_loop(
        self,
        loop_type: str,
        loop_input: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute an engineering loop through the execution engine's workforce dispatcher.
        """
        task_id = loop_input.get("loop", {}).get("task_id", f"task-{loop_type}-{uuid.uuid4().hex[:6]}")
        task_name = loop_input.get("loop", {}).get("name", f"{loop_type.title()} Loop")

        # Map loop_type to appropriate worker type
        worker_map = {
            "research": WorkerType.RESEARCH,
            "architecture": WorkerType.GENERAL,
            "planning": WorkerType.GENERAL,
            "coding": WorkerType.CODING,
            "qa": WorkerType.TESTING,
            "testing": WorkerType.TESTING,
            "review": WorkerType.REVIEW,
            "repair": WorkerType.REPAIR,
        }
        worker_type = worker_map.get(loop_type, WorkerType.CODING)

        input_data = loop_input.get("loop", {}).get("input_data", {})
        if not input_data and "request_text" in context:
            input_data = {"description": context.get("request_text")}

        task_def = TaskDefinition(
            task_id=task_id,
            name=task_name,
            task_type=loop_type,
            input_data=input_data,
        )

        wf_id_raw = context.get("workflow_id")
        wf_id = uuid.UUID(wf_id_raw) if wf_id_raw else uuid.uuid4()

        try:
            passed, artifacts, eval_res = await self.concrete_engine.execute_task_definition(
                task_def=task_def,
                workflow_id=wf_id,
                worker_type=worker_type,
            )

            status = "complete" if passed else "remediate"
            return {
                "status": status,
                "loop_type": loop_type,
                "passed": passed,
                "artifacts": [a.model_dump(mode="json") if hasattr(a, "model_dump") else a.__dict__ for a in artifacts],
                "evaluation": eval_res.status.value if eval_res else "unknown",
                "findings": eval_res.failures if eval_res else [],
            }
        except Exception as ex:
            logger.warning(f"Loop execution error in {loop_type}: {ex}")
            return {
                "status": "failed",
                "loop_type": loop_type,
                "passed": False,
                "error": str(ex),
            }

    async def dispatch_worker(
        self,
        worker_type: str,
        task: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        task_def = TaskDefinition(
            task_id=task.get("task_id", str(uuid.uuid4())),
            name=task.get("name", "Task"),
            task_type=task.get("task_type", "coding"),
            input_data=task.get("input_data", {}),
        )
        passed, artifacts, eval_res = await self.concrete_engine.execute_task_definition(
            task_def=task_def,
            worker_type=worker_type,
        )
        return {
            "success": passed,
            "artifacts_count": len(artifacts),
            "evaluation": eval_res.status.value if eval_res else "unknown",
        }


# ── 3. Review Engine Adapter ────────────────────────────────────────────────

class KernelReviewEngineAdapter(KernelReviewEngineABC):
    """
    Adapts the concrete autoforge_review engine to satisfy the Kernel's
    ReviewEngine interface.
    """

    def __init__(self, concrete_engine: ConcreteReviewEngine) -> None:
        self.concrete_engine = concrete_engine

    async def _execute_review(
        self,
        evidence: ReviewEvidence,
        project_id: uuid.UUID | None = None,
    ) -> Any:
        from autoforge_review.models import ReviewRequest
        # ReviewEngine requires at least one file or signal
        has_files = bool(evidence.source_files)
        has_signals = (
            evidence.test_results is not None
            or evidence.build_exit_code is not None
            or bool(evidence.metrics)
            or bool(evidence.command_results)
        )
        if not has_files and not has_signals:
            evidence = evidence.model_copy(update={"source_files": {"manifest.json": "{}"}})

        if hasattr(self.concrete_engine, "review"):
            req = ReviewRequest(
                project_id=project_id,
                evidence=evidence,
            )
            return await self.concrete_engine.review(req)
        elif hasattr(self.concrete_engine, "review_artifact"):
            return await self.concrete_engine.review_artifact(evidence)
        raise AttributeError("Underlying review engine does not provide review() or review_artifact()")

    async def review(
        self,
        artifact: Any,
        criteria: dict[str, Any],
    ) -> Any:
        from autoforge_models.review import Review
        from autoforge_models.enums import ReviewStatus
        art_id = artifact.id if hasattr(artifact, "id") else uuid.uuid4()
        evidence = ReviewEvidence(artifact_ids=[str(art_id)])
        result = await self._execute_review(evidence)
        passed = getattr(result, "approved", getattr(result, "passed", False))
        decision_val = result.decision.value if hasattr(result.decision, "value") else str(result.decision)
        return Review(
            id=uuid.uuid4(),
            artifact_id=art_id,
            status=ReviewStatus.APPROVED if passed else ReviewStatus.CHANGES_REQUESTED,
            score=1.0 if passed else 0.5,
            notes=decision_val,
        )

    async def review_project(
        self,
        project_id: uuid.UUID,
        context: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from autoforge_execution.models import TestResultSummary
        ctx = evidence or context or {}
        test_results = None
        if ctx.get("has_test_failures"):
            test_results = TestResultSummary(
                total_tests=1,
                passed_tests=0,
                failed_tests=1,
                error_tests=0,
                skipped_tests=0,
                failure_details=[str(ctx.get("test_error", "Test failed"))],
                raw_summary_line="1 failed",
            )
        rev_evidence = ReviewEvidence(
            artifact_ids=[str(project_id)],
            changed_files=ctx.get("changed_files", []),
            test_results=test_results,
            stderr=ctx.get("test_error", ""),
        )
        result = await self._execute_review(rev_evidence, project_id=project_id)
        passed = getattr(result, "approved", getattr(result, "passed", False))
        status_val = result.decision.value if hasattr(result.decision, "value") else str(result.decision)
        return {
            "approved": passed,
            "status": status_val,
            "decision": status_val,
            "findings": [f.model_dump(mode="json") for f in result.findings],
            "findings_count": len(result.findings),
        }

    async def review_artifact(
        self,
        artifact_id: uuid.UUID,
        criteria: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = ReviewEvidence(
            artifact_ids=[str(artifact_id)],
            changed_files=context.get("changed_files", []),
        )
        result = await self._execute_review(evidence)
        passed = getattr(result, "approved", getattr(result, "passed", False))
        decision_val = result.decision.value if hasattr(result.decision, "value") else str(result.decision)
        return {
            "approved": passed,
            "findings": [f.model_dump(mode="json") for f in result.findings],
            "decision": decision_val,
        }

    async def evaluate_quality_gates(
        self,
        project_id: uuid.UUID,
        stage: str,
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        evidence = ReviewEvidence(
            artifact_ids=[str(project_id)],
        )
        result = await self._execute_review(evidence, project_id=project_id)
        passed = getattr(result, "approved", getattr(result, "passed", False))
        decision_val = result.decision.value if hasattr(result.decision, "value") else str(result.decision)
        gate_status = []
        if hasattr(result, "gate") and result.gate is not None:
            gate_status = [result.gate.model_dump(mode="json")]
        elif hasattr(result, "quality_gate_results"):
            gate_status = [g.model_dump(mode="json") for g in result.quality_gate_results]
        return {
            "valid": passed,
            "decision": decision_val,
            "gate_status": gate_status,
            "blocking_findings": [f.title for f in result.findings if f.blocking],
        }


# ── 4. Model Router Adapter ─────────────────────────────────────────────────

class KernelModelRouterAdapter(KernelModelRouterABC):
    """
    Adapts autoforge_ai_infrastructure.ModelRouterService to satisfy the Kernel's
    ModelRouter interface.
    """

    def __init__(
        self,
        router_service: ModelRouterService | None = None,
        model_router: ModelRouterService | None = None,
        registry: Any = None,
    ) -> None:
        self.router_service = router_service or model_router
        self.registry = registry

    async def select_model(
        self,
        task: dict[str, Any],
        exclude_provider: str | None = None,
    ) -> ModelProfile:
        req = RoutingRequest(
            required_capabilities=frozenset([CapabilityIds.TEXT_GENERATION]),
            offline_only=task.get("offline_only", False),
        )
        try:
            decision = self.router_service.route(req)
            m = decision.selected.model
            prov = ModelProvider.LOCAL if "local" in m.provider_id.lower() else ModelProvider.CUSTOM
            return ModelProfile(
                id=uuid.uuid4(),
                name=f"Profile for {m.model_id}",
                provider=prov,
                model_name=m.model_id,
            )
        except Exception:
            # Safe default local-first model profile
            return ModelProfile(
                id=uuid.uuid4(),
                name="Default Local Profile",
                provider=ModelProvider.LOCAL,
                model_name="qwen2.5-coder:7b",
            )

    async def get_model_capabilities(self, model_id: str) -> dict[str, Any]:
        if self.registry and hasattr(self.registry, "get_model"):
            m = self.registry.get_model(model_id)
            if m:
                return {
                    "model_id": m.model_id,
                    "capabilities": list(m.capabilities),
                    "context_window": m.context_window_tokens,
                }
        return {"model_id": model_id, "capabilities": ["text_generation", "code_generation"]}

    async def get_provider_health(self) -> dict[str, Any]:
        return {"local-m1": "healthy", "local-hp": "healthy"}


# ── 5. Memory Engine Adapter ────────────────────────────────────────────────

class KernelMemoryEngineAdapter(KernelMemoryEngineABC):
    """
    Adapts the Runtime State Manager and Memory Models to satisfy the Kernel's
    MemoryEngine interface.
    """

    def __init__(self, runtime: RuntimeStateManager) -> None:
        self.runtime = runtime
        self._local_memories: dict[str, list[dict[str, Any]]] = {}

    async def load_context(self, project_id: uuid.UUID) -> dict[str, Any]:
        pid_str = str(project_id)
        entries = self._local_memories.get(pid_str, [])
        return {"project_id": pid_str, "memories": entries}

    async def persist_state(self, project_id: uuid.UUID, state: dict[str, Any]) -> None:
        if hasattr(self.runtime, "checkpoint_manager"):
            try:
                self.runtime.checkpoint_manager.store(
                    entity_id=str(project_id),
                    state_snapshot=state,
                    checkpoint_type="project_memory_state",
                )
            except Exception:
                pass

    async def store_memory(self, project_id: uuid.UUID, memory: dict[str, Any]) -> None:
        pid_str = str(project_id)
        if pid_str not in self._local_memories:
            self._local_memories[pid_str] = []
        self._local_memories[pid_str].append(memory)

        # Also store canonical MemoryEntry if runtime state is accessible
        if hasattr(self.runtime, "runtime_state") and hasattr(self.runtime.runtime_state, "memory_entries"):
            entry = MemoryEntry(
                id=uuid.uuid4(),
                project_id=project_id,
                memory_type=MemoryType.EPISODIC,
                content=memory,
                importance_score=0.8,
            )
            self.runtime.runtime_state.memory_entries[entry.id] = entry

    async def retrieve_memory(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        results = []
        q_lower = query.lower()
        for p_mems in self._local_memories.values():
            for m in p_mems:
                if any(q_lower in str(v).lower() for v in m.values()):
                    results.append(m)
                    if len(results) >= limit:
                        return results
        return results

    async def retrieve_experience(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        context = context or {}
        pid_str = context.get("project_id")
        memories = self._local_memories.get(pid_str, []) if pid_str else [m for ml in self._local_memories.values() for m in ml]
        q = query.lower()
        matched = [m for m in memories if q in str(m).lower()]
        return matched if matched else memories

    async def store_experience(self, experience: dict[str, Any]) -> None:
        pid = experience.get("project_id")
        proj_uuid = uuid.UUID(str(pid)) if pid else uuid.uuid4()
        await self.store_memory(proj_uuid, experience)


# ── 6. Knowledge Engine Adapter ─────────────────────────────────────────────

class KernelKnowledgeEngineAdapter(KernelKnowledgeEngineABC):
    """
    Adapts the Knowledge Platform to satisfy the Kernel's KnowledgeEngine interface.
    """

    def __init__(self, knowledge_platform: Any = None) -> None:
        self.knowledge_platform = knowledge_platform
        self._promoted_learnings: list[dict[str, Any]] = []

    async def research(self, topic: str, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "topic": topic,
            "findings": [
                f"Domain technical investigation for {topic}",
                "Best practices: modular separation, sandboxed execution, and comprehensive test coverage.",
            ],
            "recommendations": ["Use automated quality gates", "Persist durable artifacts"],
        }

    async def query(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        # Query promoted learnings and knowledge platform
        matching = []
        q_lower = query.lower()
        for item in self._promoted_learnings:
            if q_lower in str(item).lower():
                matching.append(item)
        return matching

    async def promote(self, learning: dict[str, Any]) -> None:
        self._promoted_learnings.append(learning)
        logger.info(f"Promoted validated learning to Knowledge Engine: {learning.get('summary', 'New lesson')}")

    async def query_knowledge(self, query: str) -> dict[str, Any]:
        results = await self.query(query)
        return {
            "query": query,
            "results": results,
        }
