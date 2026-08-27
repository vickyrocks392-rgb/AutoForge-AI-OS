"""
Engineering Loop — bounded autonomous engineering execution loop.

Implements the canonical loop:
  UNDERSTAND → PLAN → IMPLEMENT → EXECUTE / TEST → EVALUATE
                     ┌─┴─┐
                 PASS     FAIL
                  │        │
                DONE    DIAGNOSE
                           │
                         REPAIR
                           │
                      REIMPLEMENT
                           │
                         RETEST
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

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
    ConsequentialActionType,
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    LoopConfig,
    LoopIterationRecord,
    LoopStatus,
)


class EngineeringLoop:
    """
    Executes a bounded, observable, recoverable autonomous engineering loop.
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
    ) -> None:
        self._env = environment
        self._ai = ai_provider
        self._evaluator = evaluation_engine or EvaluationEngine()
        self._diagnoser = diagnoser or FailureDiagnoser(self._ai)
        self._artifacts = artifact_pipeline or ArtifactPipeline()
        self._governance = governance or ExecutionGovernance()
        self._config = config or LoopConfig()
        self._callback = on_iteration_callback

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
        """
        Run the autonomous engineering loop until success or limits exhausted.

        Args:
            context: The assembled task context.
            worker_id: The ID of the worker executing this loop.
            verification_commands: Commands to run to verify the implementation.
            is_cancelled: Optional callback checking if execution was cancelled.

        Returns:
            (passed, produced_artifacts, last_evaluation)
        """
        self._status = LoopStatus.RUNNING
        start_time = time.perf_counter()
        produced_artifacts: list[ArtifactRecord] = []

        # If verification commands not specified, check task input_data
        commands_to_run = verification_commands or []
        if not commands_to_run:
            input_cmds = context.input_data.get("commands") or context.input_data.get("test_commands")
            if isinstance(input_cmds, list):
                for cmd in input_cmds:
                    if isinstance(cmd, list):
                        commands_to_run.append(CommandSpec(argv=cmd))
                    elif isinstance(cmd, str):
                        commands_to_run.append(CommandSpec(argv=cmd.split()))

        current_iteration = 0
        last_eval: EvaluationResult | None = None
        consecutive_failures = 0

        while current_iteration < self._config.max_iterations:
            current_iteration += 1
            iter_start = time.perf_counter()

            # Check timeout
            elapsed = time.perf_counter() - start_time
            if elapsed > self._config.timeout_seconds:
                self._status = LoopStatus.TIMED_OUT
                break

            # Check cancellation
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

            # 1. UNDERSTAND & PLAN / REPAIR
            if current_iteration == 1:
                # Initial plan
                plan = await self._ai.generate_plan(context)
                file_edits = await self._ai.generate_implementation(context, plan)
            else:
                # Repair step informed by previous diagnosis
                self._status = LoopStatus.REPAIRING
                diagnosis = context.last_diagnosis or DiagnosisReport(root_cause="Previous attempt failed")
                plan = f"Repair plan based on root cause: {diagnosis.root_cause}"
                file_edits = await self._ai.generate_repair(context, diagnosis)

            # 2. IMPLEMENT: Apply file edits through Filesystem connector
            changed_files: list[str] = []
            for edit in file_edits:
                path = edit.get("path")
                content = edit.get("content", "")
                if path:
                    # Write through WorkspaceFilesystem connector
                    self._env.filesystem.write_text(path, content, overwrite=True)
                    changed_files.append(path)

            # Record source code / diff artifact if any files were changed
            if changed_files:
                diff_summary = f"Modified files: {', '.join(changed_files)}"
                diff_art = self._artifacts.record_diff_artifact(diff_summary, provenance)
                produced_artifacts.append(diff_art)

            # 3. EXECUTE / TEST
            cmd_results: list[CommandResult] = []
            for cmd_spec in commands_to_run:
                if is_cancelled and is_cancelled():
                    self._status = LoopStatus.CANCELLED
                    break
                cmd_res = await self._env.execute_command(cmd_spec)
                cmd_results.append(cmd_res)

                # Record execution log artifact
                log_art = self._artifacts.record_artifact(
                    name=f"cmd_{cmd_spec.argv[0] if isinstance(cmd_spec, CommandSpec) else cmd_spec[0]}_iter_{current_iteration}.log",
                    artifact_type=ArtifactType.EXECUTION_LOG,
                    content=f"STDOUT:\n{cmd_res.stdout}\nSTDERR:\n{cmd_res.stderr}\nEXIT_CODE: {cmd_res.exit_code}",
                    provenance=provenance,
                )
                produced_artifacts.append(log_art)

            # 4. EVALUATE
            self._status = LoopStatus.EVALUATING
            eval_res = self._evaluator.evaluate_attempt(cmd_results)
            last_eval = eval_res
            context.last_evaluation = eval_res

            # Record evaluation artifact
            eval_art = self._artifacts.record_evaluation_artifact(eval_res, provenance)
            produced_artifacts.append(eval_art)

            # 5. DIAGNOSE (if failed)
            diagnosis_report: DiagnosisReport | None = None
            if not eval_res.passed:
                consecutive_failures += 1
                diagnosis_report = await self._diagnoser.diagnose(context, eval_res, cmd_results)
                context.last_diagnosis = diagnosis_report

                # Record diagnosis artifact
                diag_art = self._artifacts.record_diagnosis_artifact(diagnosis_report, provenance)
                produced_artifacts.append(diag_art)
            else:
                consecutive_failures = 0

            # Record iteration history
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

            # 6. TERMINATION DECISION
            if eval_res.passed and self._config.stop_on_first_pass:
                self._status = LoopStatus.COMPLETED
                return True, produced_artifacts, eval_res

            # Check consecutive failure escalation
            if consecutive_failures >= self._config.max_consecutive_failures and current_iteration >= self._config.max_iterations:
                break

        passed = (last_eval is not None and last_eval.passed)
        if passed:
            self._status = LoopStatus.COMPLETED
        elif self._status != LoopStatus.TIMED_OUT and self._status != LoopStatus.CANCELLED:
            self._status = LoopStatus.FAILED

        return passed, produced_artifacts, last_eval
