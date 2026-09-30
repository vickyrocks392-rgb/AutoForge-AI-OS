"""
Engineering Loop - bounded autonomous engineering execution loop.

Phase 18-E Enhancement:
  When a rag_engine is provided, the diagnose->repair->re-test cycle is
  routed through RepairCycle which enforces:
    - real RAG evidence (Phase 18-D local Qdrant)
    - safe file edits with target/hash verification
    - bounded retry (max_repair_attempts)
    - deterministic re-evaluation before claiming PASS
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Protocol, runtime_checkable

from autoforge_connectors.filesystem import WorkspaceFilesystem
from autoforge_connectors.git import GitConnector

from autoforge_execution.ai_adapter import AIEngineeringProvider
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.context import ExecutionContext
from autoforge_execution.diagnosis import FailureDiagnoser
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.evaluation import EvaluationEngine
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.models import (
    ArtifactProvenance,
    ArtifactRecord,
    ArtifactType,
    CommandResult,
    CommandSpec,
    DiagnosisReport,
    EvaluationResult,
    LoopConfig,
    LoopIterationRecord,
    LoopStatus,
    RAGRetrievalEngine,
)


logger = logging.getLogger(__name__)


class EngineeringLoop:
    """
    Executes a bounded, observable, recoverable autonomous engineering loop
    with optional Phase 18-E RAG-integrated repair cycle support.
    """

    def __init__(
        self,
        environment: WorkspaceEnvironment,
        ai_provider: AIEngineeringProvider,
        *,
        evaluation_engine: EvaluationEngine | None = None,
        diagnoser: FailureDiagnoser | None = None,
        artifact_pipeline: ArtifactPipeline | None = None,
        governance: ExecutionGovernance | None = None,
        config: LoopConfig | None = None,
        on_iteration_callback: Callable[[LoopIterationRecord], None] | None = None,
        rag_engine: RAGRetrievalEngine | None = None,
    ) -> None:
        self._env = environment
        self._ai = ai_provider
        self._evaluator = evaluation_engine or EvaluationEngine()
        base_diagnoser = diagnoser or FailureDiagnoser(self._ai)
        self._artifacts = artifact_pipeline or ArtifactPipeline()
        self._governance = governance or ExecutionGovernance()
        self._config = config or LoopConfig()
        self._callback = on_iteration_callback
        self._rag_engine: RAGRetrievalEngine | None = rag_engine
        if rag_engine is not None:
            try:
                from autoforge_execution_18e.diagnosis_rag import RAGIntegratedDiagnoser
                self._diagnoser: FailureDiagnoser = RAGIntegratedDiagnoser(
                    base_diagnoser, rag_engine=rag_engine
                )
            except Exception as exc:
                logger.warning("Failed to wire RAGIntegratedDiagnoser: %s", exc)
                self._diagnoser = base_diagnoser
        else:
            self._diagnoser = base_diagnoser
        self._status = LoopStatus.NOT_STARTED
        self._iterations: list[LoopIterationRecord] = []

    @property
    def status(self) -> LoopStatus:
        return self._status

    @property
    def iteration_history(self) -> list[LoopIterationRecord]:
        return list(self._iterations)

    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: list[CommandSpec | list[str]] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        start_time = time.perf_counter()
        produced_artifacts: list[ArtifactRecord] = []
        commands_to_run: list[Any] = list(verification_commands) if verification_commands else []
        if not commands_to_run:
            input_cmds = context.input_data.get("commands") or context.input_data.get("test_commands")
            if isinstance(input_cmds, list):
                for cmd in input_cmds:
                    if isinstance(cmd, list):
                        commands_to_run.append(CommandSpec(argv=cmd))
                    elif isinstance(cmd, str):
                        commands_to_run.append(CommandSpec(argv=cmd.split()))
        repair_cycle = None
        if self._rag_engine is not None:
            try:
                from autoforge_execution_18e.repair_cycle import RepairCycle, RepairCycleConfig
                repair_cfg = RepairCycleConfig(
                    max_repair_attempts=max(1, self._config.max_consecutive_failures),
                    stop_on_first_repair_success=True,
                    rag_enabled=True,
                    require_target_verification=True,
                    min_confidence_threshold=0.3,
                )
                repair_cycle = RepairCycle(
                    environment=self._env,
                    ai_provider=self._ai,
                    evaluation_engine=self._evaluator,
                    rag_engine=self._rag_engine,
                    file_editor=None,
                    config=repair_cfg,
                )
            except Exception as exc:
                logger.warning("Could not create RepairCycle: %s", exc)
                repair_cycle = None
        current_iteration = 0
        last_eval: EvaluationResult | None = None
        consecutive_failures = 0
        while current_iteration < self._config.max_iterations:
            current_iteration += 1
            elapsed = time.perf_counter() - start_time
            if elapsed > self._config.timeout_seconds:
                self._status = LoopStatus.TIMED_OUT
                break
            if is_cancelled and is_cancelled():
                self._status = LoopStatus.CANCELLED
                break
            provenance = ArtifactProvenance(
                task_id=context.task_id,
                worker_id=worker_id,
                workflow_id=context.workflow_id,
                correlation_id=context.correlation_id,
                attempt_number=context.attempt_number,
                iteration=current_iteration,
            )

            if current_iteration == 1:
                plan = await self._ai.generate_plan(context)
                file_edits = await self._ai.generate_implementation(context, plan)
            elif repair_cycle is not None:
                self._status = LoopStatus.REPAIRING
                last_eval_for_repair = context.last_evaluation
                if last_eval_for_repair is None:
                    from autoforge_execution.models import EvaluationStatus
                    last_eval_for_repair = EvaluationResult(
                        status=EvaluationStatus.FAILED,
                        failures=["previous iteration failed"],
                    )
                last_cmd_results = (
                    self._iterations[-1].commands_executed if self._iterations else []
                )
                repair_result = await repair_cycle.run(
                    context=context,
                    evaluation=last_eval_for_repair,
                    command_results=last_cmd_results,
                    verification_commands=commands_to_run,
                    on_attempt_callback=None,
                )
                plan = "Phase 18-E repair cycle"
                eval_res = repair_result.final_evaluation or last_eval_for_repair
                last_eval = eval_res
                context.last_evaluation = eval_res
                context.last_diagnosis = (
                    repair_result.attempts[-1].diagnosis
                    if repair_result.attempts else None
                )
                reeval_art = self._artifacts.record_evaluation_artifact(eval_res, provenance)
                produced_artifacts.append(reeval_art)
                changed_files: list[str] = []
                for attempt in repair_result.attempts:
                    for er in attempt.edit_results:
                        if er.success and er.edit:
                            changed_files.append(er.edit.target_path)
                iter_record = LoopIterationRecord(
                    iteration=current_iteration,
                    finished_at=None,
                    action_plan=plan,
                    changed_files=changed_files,
                    commands_executed=last_cmd_results,
                    evaluation=eval_res,
                    diagnosis=context.last_diagnosis,
                    passed=eval_res.passed if eval_res else False,
                )
                self._iterations.append(iter_record)
                context.prior_iterations.append(iter_record)
                if self._callback:
                    self._callback(iter_record)
                if not eval_res.passed:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                if eval_res.passed and self._config.stop_on_first_pass:
                    self._status = LoopStatus.COMPLETED
                    return True, produced_artifacts, eval_res
                if (consecutive_failures >= self._config.max_consecutive_failures
                    and current_iteration >= self._config.max_iterations):
                    break
                continue
            else:
                self._status = LoopStatus.REPAIRING
                diagnosis = context.last_diagnosis or DiagnosisReport(
                    root_cause="Previous attempt failed"
                )
                plan = "Repair plan based on root cause: " + diagnosis.root_cause
                file_edits = await self._ai.generate_repair(context, diagnosis)

            changed_files: list[str] = []
            for edit in file_edits:
                edit_path = edit.get("path")
                edit_content = edit.get("content", "")
                if edit_path:
                    self._env.filesystem.write_text(edit_path, edit_content, overwrite=True)
                    changed_files.append(edit_path)
                    # DEF-18L-01: register the ACTUAL generated source as a
                    # durable artifact, not just the file name.
                    #
                    # Before this, only a diff SUMMARY ("Modified files: ...")
                    # became durable, so a project's real deliverable existed
                    # only on the workspace filesystem and never reached the
                    # authoritative 18-K catalog. The final review therefore
                    # inspected platform bookkeeping instead of the project.
                    #
                    # This is the existing artifact boundary: the bytes flow
                    # through the same ArtifactPipeline -> DurableArtifactCatalog
                    # -> PhysicalArtifactStore -> COMMITTED path used by every
                    # other execution artifact. No second artifact store, no new
                    # persistence model, and no change to the 18-J/18-K state
                    # machine (the pipeline already honours idempotent replay).
                    source_art = self._artifacts.record_artifact(
                        name=edit_path,
                        artifact_type=ArtifactType.SOURCE_CODE,
                        content=edit_content,
                        provenance=provenance,
                        path=edit_path,
                    )
                    produced_artifacts.append(source_art)
            if changed_files:
                diff_summary = "Modified files: " + ", ".join(changed_files)
                diff_art = self._artifacts.record_diff_artifact(diff_summary, provenance)
                produced_artifacts.append(diff_art)
            cmd_results: list[CommandResult] = []
            for cmd_spec in commands_to_run:
                if is_cancelled and is_cancelled():
                    self._status = LoopStatus.CANCELLED
                    break
                if isinstance(cmd_spec, CommandSpec):
                    cmd_res = await self._env.execute_command(cmd_spec)
                elif isinstance(cmd_spec, list):
                    cmd_res = await self._env.execute_command(CommandSpec(argv=cmd_spec))
                else:
                    continue
                cmd_results.append(cmd_res)
                cmd_name = cmd_spec.argv[0] if isinstance(cmd_spec, CommandSpec) else cmd_spec[0]
                log_art = self._artifacts.record_artifact(
                    name="cmd_" + cmd_name + "_iter_" + str(current_iteration) + ".log",
                    artifact_type=ArtifactType.EXECUTION_LOG,
                    content="STDOUT:\n" + cmd_res.stdout + "\nSTDERR:\n" + cmd_res.stderr + "\nEXIT_CODE: " + str(cmd_res.exit_code),
                    provenance=provenance,
                )
                produced_artifacts.append(log_art)

            self._status = LoopStatus.EVALUATING
            eval_res = self._evaluator.evaluate_attempt(cmd_results)
            last_eval = eval_res
            context.last_evaluation = eval_res
            eval_art = self._artifacts.record_evaluation_artifact(eval_res, provenance)
            produced_artifacts.append(eval_art)
            diagnosis_report: DiagnosisReport | None = None
            if not eval_res.passed:
                consecutive_failures += 1
                diagnosis_report = await self._diagnoser.diagnose(context, eval_res, cmd_results)
                context.last_diagnosis = diagnosis_report
                diag_art = self._artifacts.record_diagnosis_artifact(diagnosis_report, provenance)
                produced_artifacts.append(diag_art)
            else:
                consecutive_failures = 0
            iter_record = LoopIterationRecord(
                iteration=current_iteration,
                finished_at=None,
                action_plan=plan,
                changed_files=changed_files,
                commands_executed=cmd_results,
                evaluation=eval_res,
                diagnosis=diagnosis_report,
                passed=eval_res.passed,
            )
            self._iterations.append(iter_record)
            context.prior_iterations.append(iter_record)
            if self._callback:
                self._callback(iter_record)
            if eval_res.passed and self._config.stop_on_first_pass:
                self._status = LoopStatus.COMPLETED
                return True, produced_artifacts, eval_res
            if (consecutive_failures >= self._config.max_consecutive_failures
                and current_iteration >= self._config.max_iterations):
                break
        passed = last_eval is not None and last_eval.passed
        if passed:
            self._status = LoopStatus.COMPLETED
        elif self._status not in (LoopStatus.TIMED_OUT, LoopStatus.CANCELLED):
            self._status = LoopStatus.FAILED
        return passed, produced_artifacts, last_eval
