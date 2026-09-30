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

import inspect
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from autoforge_composition.capability_router import (
    UnknownCapabilityError,
    read_capability,
)

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


def _test_summary_from_context(ctx: Dict[str, Any]) -> Any | None:
    """Build a real ``TestResultSummary`` from deterministic validation truth.

    DEF-18LR-D8. The previous behaviour synthesised a one-test placeholder
    (``total_tests=1, failed_tests=1``) whenever a boolean said "there were
    failures", so the Review Engine never saw how many tests ran, how many
    passed, or what actually failed. The final review is a quality gate over
    evidence; it deserves the real numbers.

    Precedence:
      1. ``ctx["test_results"]`` -- a full structured summary from the
         deterministic validation port. Used verbatim.
      2. ``ctx["has_test_failures"]`` -- the legacy boolean, preserved exactly
         for callers that still pass it.

    Returns ``None`` when nothing is asserted, which preserves the existing
    "absence is not a failure" review semantics.
    """
    from autoforge_execution.models import TestResultSummary

    raw = ctx.get("test_results")
    if isinstance(raw, dict):
        try:
            return TestResultSummary(
                total_tests=int(raw.get("total_tests", 0) or 0),
                passed_tests=int(raw.get("passed_tests", 0) or 0),
                failed_tests=int(raw.get("failed_tests", 0) or 0),
                error_tests=int(raw.get("error_tests", 0) or 0),
                skipped_tests=int(raw.get("skipped_tests", 0) or 0),
                failure_details=[str(d) for d in (raw.get("failure_details") or [])],
                raw_summary_line=str(raw.get("raw_summary_line", "") or ""),
            )
        except (TypeError, ValueError):
            # Malformed structured truth must not become a fabricated summary.
            # Fall through to the legacy boolean so the caller still fails closed.
            pass

    if ctx.get("has_test_failures") or ctx.get("has_errors"):
        return TestResultSummary(
            total_tests=1,
            passed_tests=0,
            failed_tests=1,
            error_tests=1 if ctx.get("has_errors") else 0,
            skipped_tests=0,
            failure_details=[str(ctx.get("test_error", "Test failed"))],
            raw_summary_line="1 failed",
        )
    return None


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

    DEF-18LE-A: this adapter is also the canonical capability-routing seam that
    18-LD isolated. When a Commercial Power Engine is requested, the loop is
    dispatched to that engine through its own existing contract and the result is
    returned in the SAME dict shape ``handle_loop_completion`` already consumes.

    When NO capability is declared the method is byte-for-byte the generic path:
    generic engineering requests are unaffected.
    """

    def __init__(
        self,
        concrete_engine: ConcreteExecutionEngine,
        *,
        capability_router: Any | None = None,
        project_configuration_reader: Any | None = None,
    ) -> None:
        self.concrete_engine = concrete_engine
        self._router = capability_router
        self._config_reader = project_configuration_reader

    async def _project_configuration(self, project_id: Any) -> Dict[str, Any]:
        """Read the project's durable configuration, if a reader is wired.

        The existing ``KernelRuntimeFacade.get_project_state`` returns the
        Runtime's ``ProjectState`` *model*, and the validation port's reader
        returns a plain dict. Both shapes are accepted so the two consumers of
        the same durable state can never disagree.
        """
        if self._config_reader is None:
            return {}
        try:
            # Accept either a reader callable (production: the bound
            # ``KernelRuntimeFacade.get_project_state``) or an object exposing
            # ``get_project_state`` (a test double or an alternative facade).
            reader = self._config_reader
            if not callable(reader):
                reader = reader.get_project_state
            state = reader(project_id)
            if inspect.isawaitable(state):
                state = await state
        except Exception as exc:  # pragma: no cover - defensive only
            logger.warning("Could not read project configuration: %s", exc)
            return {}
        return _project_configuration_of(state)

    @staticmethod
    def _with_verification_commands(
        input_data: Any, project_configuration: Dict[str, Any]
    ) -> Any:
        """Return ``input_data`` carrying the declared verification command.

        DECISION B layer 1 transport. The declared command is read with the SAME
        existing resolver the completion gate uses
        (``validation_wiring.resolve_verification_command``), so the loop and the
        gate can never disagree about what was declared. The value is placed in
        ``input_data["verification_commands"]`` as an argv list, which is the
        shape ``WorkforceWorker.execute_task`` already reads.

        The input is copied, never mutated, and is returned unchanged when the
        project declares no verification command.
        """
        if not project_configuration:
            return input_data
        from autoforge_composition.validation_wiring import (
            resolve_verification_command,
        )

        argv = resolve_verification_command(project_configuration)
        if not argv:
            return input_data
        if not isinstance(input_data, dict):
            input_data = {}
        else:
            input_data = dict(input_data)
        # Never overwrite an explicit, more specific declaration on the loop.
        if not input_data.get("verification_commands"):
            input_data["verification_commands"] = [list(argv)]
        return input_data
        # Never overwrite an explicit, more specific declaration on the loop.
        if not input_data.get("verification_commands"):
            input_data["verification_commands"] = [list(argv)]
        return input_data

    async def _execute_commercial_loop(
        self,
        *,
        capability: str,
        capability_source: Optional[str],
        loop_type: str,
        task_id: str,
        task_name: str,
        loop_input: Dict[str, Any],
        context: Dict[str, Any],
        project_id: Any,
        project_configuration: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Dispatch this loop to the requested Commercial Power Engine.

        The engine is invoked through its OWN existing contract and the outcome is
        returned in the dict shape ``handle_loop_completion`` already consumes, so
        O-2 completion, the durable artifact path, Review and Completion all work
        unchanged.

        Fail-closed: an unknown capability, an engine failure, or a routing error
        is reported as a loop ``failed``/``remediate`` result. It is never silently
        downgraded to the generic engine, which would hide the defect.
        """
        request_text = str(context.get("request_text") or "")
        try:
            routed = await self._router.invoke(
                capability,
                project_id=str(project_id or task_id),
                request_text=request_text,
                project_configuration=_unwrap_configuration(project_configuration),
            )
        except UnknownCapabilityError as exc:
            logger.error("Unknown commercial capability %r: %s", capability, exc)
            return {
                "status": "failed",
                "loop_type": loop_type,
                "passed": False,
                "error": str(exc),
                "capability": capability,
                "routed": False,
            }
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            logger.error(
                "Commercial engine %r failed during %s: %s",
                capability, loop_type, exc, exc_info=True,
            )
            return {
                "status": "remediate",
                "loop_type": loop_type,
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                "capability": capability,
                "engine_class": type(self._router).__name__,
                "routed": True,
            }

        # Publish the engine's own deterministic evidence as a durable artifact so
        # it flows through the SAME 18-K pipeline as everything else and reaches
        # the final Review as real evidence (DECISION B layer 2).
        artifacts = await self._publish_routed_evidence(
            routed=routed,
            task_id=task_id,
            task_name=task_name,
            context=context,
        )

        return {
            "status": routed.status,
            "loop_type": loop_type,
            "passed": routed.success,
            "artifacts": artifacts,
            "evaluation": routed.status,
            "findings": [] if routed.success else [routed.error_message or "engine reported failure"],
            # Routing evidence: the ACTUAL engine that executed.
            "routed": True,
            "capability": capability,
            "capability_source": capability_source,
            "engine_class": routed.engine_class,
            "delivery_dir": routed.delivery_dir,
            "stages_executed": routed.stages_executed,
            "repair_count": routed.repair_count,
            "verification_scorecard": routed.verification_scorecard,
            "summary_report": routed.summary_report,
            "error": routed.error_message,
        }

    async def _publish_routed_evidence(
        self,
        *,
        routed: Any,
        task_id: str,
        task_name: str,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Record a routed engine's own verification scorecard as a durable artifact.

        The Commercial Power Engines already produce deterministic verification
        internally (``_stage_verify`` -> ``verification_scorecard``, or
        ``PipelineResult`` for Legacy Modernization). DECISION B requires that
        evidence to reach canonical validation/review/completion rather than be
        replaced by a second authority, so it is published through the EXISTING
        ``ArtifactPipeline`` (and therefore 18-K DurableArtifactCatalog +
        PhysicalArtifactStore) instead of a private channel.
        """
        import json

        from autoforge_execution.models import ArtifactProvenance, ArtifactType

        wf_raw = context.get("workflow_id")
        try:
            wf_id = uuid.UUID(wf_raw) if wf_raw else None
        except (ValueError, AttributeError, TypeError):
            wf_id = None

        try:
            pipeline = getattr(self.concrete_engine, "artifacts", None)
            if pipeline is None:
                return []
            record = pipeline.record_artifact(
                name=f"commercial_verification_{routed.capability}_{task_id}.json",
                artifact_type=ArtifactType.TEST_REPORT,
                content=json.dumps(routed.to_dict(), indent=2, default=str),
                provenance=ArtifactProvenance(
                    task_id=str(task_id),
                    worker_id=f"commercial-{routed.capability}",
                    workflow_id=wf_id,
                    metadata={
                        "capability": routed.capability,
                        "engine_class": routed.engine_class,
                        "loop": task_name,
                    },
                ),
            )
            return [
                record.model_dump(mode="json") if hasattr(record, "model_dump")
                else dict(record.__dict__)
            ]
        except Exception as exc:  # noqa: BLE001 - evidence publication is best-effort
            logger.warning(
                "Could not publish routed verification evidence for %s: %s",
                routed.capability, exc,
            )
            return []


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

        # ── DEF-18LE-A: canonical capability routing (DECISION A) ──────────
        #
        # 18-LD proved this is the last boundary before the generic engine
        # commits, and that capability identity already arrives here through the
        # durable configuration channel. A declared capability routes to its
        # Commercial Power Engine; NO capability means the generic path below,
        # which is unchanged.
        project_id = context.get("project_id") or loop_input.get("project_id")
        project_configuration: Dict[str, Any] = {}
        if self._router is not None:
            project_configuration = await self._project_configuration(project_id)
            capability, capability_source = read_capability(
                loop_input, project_configuration
            )
            if capability:
                routed = await self._execute_commercial_loop(
                    capability=capability,
                    capability_source=capability_source,
                    loop_type=loop_type,
                    task_id=task_id,
                    task_name=task_name,
                    loop_input=loop_input,
                    context=context,
                    project_id=project_id,
                    project_configuration=project_configuration,
                )
                if routed is not None:
                    return routed

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

        # DEF-18LE-B: transport the declared verification command.
        #
        # DECISION B layer 1. 18-LD proved the whole downstream chain already
        # exists and is LIVE but is fed by nothing:
        #   WorkforceWorker.execute_task  reads input_data["verification_commands"]
        #   EngineeringLoop.run          honours verification_commands (and the
        #                                  input_data["commands"] /
        #                                  ["test_commands"] fallbacks)
        # and that exactly ONE write was missing, here. This is that write.
        #
        # It is applied AFTER the DEF-18L-03 fallback above so a fallback-created
        # input mapping cannot discard the declaration. The command is read with
        # the SAME existing resolver the completion gate uses, so the loop and
        # the gate can never disagree about what was declared. No new validation
        # system is created: the existing WorkspaceEnvironment, EvaluationEngine,
        # parse_test_output and durable evaluation artifacts do all the work.
        input_data = self._with_verification_commands(
            input_data, project_configuration
        )

        # DEF-18L-04: carry the specification onto ``TaskDefinition.description``.
        #
        # ``EngineeringContextBuilder`` builds the model's context from
        # ``task_def.name`` and ``task_def.description``
        # (context_builder.py:235,306). The description was never populated, so
        # the canonical Context Engineering path -- the one that is globally
        # enabled and certified -- assembled a prompt from the loop NAME alone
        # ("Core Implementation"). The model therefore had no access to the
        # project specification even though ``input_data`` carried it, and
        # produced an unrelated generic project.
        #
        # ``input_data`` is preserved exactly as before; this only fills the
        # field the context builder already reads. The request is used only when
        # no more specific description was supplied.
        description = str(loop_input.get("loop", {}).get("description") or "")
        if not description and "request_text" in context:
            description = str(context.get("request_text") or "")
        if not description and isinstance(input_data, dict):
            description = str(input_data.get("description") or "")

        # ``input_data`` was already decorated with the declared verification
        # command above, so the TaskDefinition carries it into the real worker
        # contract (``WorkforceWorker.execute_task``) unchanged.
        task_def = TaskDefinition(
            task_id=task_id,
            name=task_name,
            description=description,
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


def _project_configuration_of(state: Any) -> Dict[str, Any]:
    """Return a project state's ``configuration`` from either supported shape.

    The Runtime exposes the same durable state in two forms that already exist in
    this repository:

    * ``ProjectState`` (a model) via ``KernelRuntimeFacade.get_project_state``;
    * a plain ``dict`` via ``model_dump(mode="python")`` (what the D-8 validation
      port receives).

    Both are read here so the routing seam and the validation gate resolve the
    SAME project configuration. No new state model is introduced.
    """
    if state is None:
        return {}
    configuration = getattr(state, "configuration", None)
    if configuration is None and isinstance(state, dict):
        configuration = state.get("configuration")
    return dict(configuration) if isinstance(configuration, dict) else {}


def _unwrap_configuration(project_configuration: Dict[str, Any]) -> Dict[str, Any]:
    """Return the requester's own configuration mapping.

    The existing intake persists ``Request.configuration`` one level deep inside
    ``ProjectState.configuration`` (``Project.metadata["configuration"]``). Both
    the flat and nested shapes are accepted so callers cannot disagree about the
    shape, exactly as ``resolve_verification_command`` already does.
    """
    if not isinstance(project_configuration, dict):
        return {}
    nested = project_configuration.get("configuration")
    if isinstance(nested, dict):
        merged = dict(project_configuration)
        merged.pop("configuration", None)
        merged.update(nested)
        return merged
    return dict(project_configuration)


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

        # DEF-P1-EVIDENCE. The Review Engine does NOT require a file or signal to
        # be present: it has an explicit, inspectable branch for genuinely empty
        # evidence that returns APPROVED with a ``no_target`` gate
        # (autoforge_review/engine.py). The previous code injected a synthetic
        # ``{"manifest.json": "{}"}`` placeholder to "satisfy" that requirement,
        # which instead defeated the empty-evidence branch and produced a real
        # ``high / Required Files`` documentation finding, rejecting every
        # project regardless of quality. No evidence is fabricated here.
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
        """Run the canonical final project review over REAL project evidence.

        DEF-P1-EVIDENCE. ``evidence`` may carry the project's actual deliverable
        content as ``{filename: content}``. When supplied it is passed to the
        Review Engine verbatim, so the review evaluates the real project output.

        When no content is supplied the Review Engine's own explicitly-empty
        branch runs and returns an inspectable ``no_target`` verdict. No
        synthetic placeholder file is manufactured here: the previous
        ``{"manifest.json": "{}"}`` fallback defeated that branch and rejected
        every project with a spurious ``Required Files`` finding.
        """
        from autoforge_execution.models import TestResultSummary

        # ``evidence`` is the authoritative source of reviewable content. The
        # legacy ``context`` dict remains supported for callers that still pass
        # the older shape.
        source_files: dict[str, str] = {}
        ctx: dict[str, Any] = {}
        if isinstance(evidence, dict) and evidence:
            source_files = {str(k): str(v) for k, v in evidence.items()}
        if context:
            ctx = dict(context)
        elif isinstance(evidence, dict):
            ctx = {k: v for k, v in evidence.items() if not isinstance(v, str)}

        test_results = _test_summary_from_context(ctx)
        rev_evidence = ReviewEvidence(
            source_files=source_files,
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
            "evidence_files": len(source_files),
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
