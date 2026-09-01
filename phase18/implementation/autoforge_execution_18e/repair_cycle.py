"""Phase 18-E — Bounded Repair Cycle."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from autoforge_execution.context import ExecutionContext
from autoforge_execution.ai_adapter import AIEngineeringProvider
from autoforge_execution.diagnosis import FailureDiagnoser
from autoforge_execution.evaluation import EvaluationEngine
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.models import (
    CommandResult, CommandSpec, DiagnosisReport,
    EvaluationResult, EvaluationStatus,
)
from autoforge_execution_18e.confidence_models import DiagnosisConfidence
from autoforge_execution_18e.confidence import DiagnosisConfidenceCalculator
from autoforge_execution_18e.diagnosis_rag import RAGIntegratedDiagnoser
from autoforge_execution_18e.safe_edit import SafeFileEditor
from autoforge_execution_18e.repair_models import (
    SafeFileEdit, SafeFileEditResult, RepairAttempt,
    RepairFailureReason, RepairResult, RepairStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class RepairCycleConfig:
    """Configuration for the bounded repair cycle."""
    max_repair_attempts: int = 3
    stop_on_first_repair_success: bool = True
    rag_enabled: bool = True
    require_target_verification: bool = True
    min_confidence_threshold: float = 0.3


class RepairCycle:
    """
    Orchestrates the bounded diagnosis -> RAG repair -> re-execute -> re-evaluate cycle.
    """

    def __init__(
        self,
        environment: WorkspaceEnvironment,
        ai_provider: AIEngineeringProvider,
        *,
        evaluation_engine: EvaluationEngine | None = None,
        diagnoser: FailureDiagnoser | None = None,
        rag_engine=None,
        file_editor: SafeFileEditor | None = None,
        config: RepairCycleConfig | None = None,
    ) -> None:
        self._env = environment
        self._ai = ai_provider
        self._evaluator = evaluation_engine or EvaluationEngine()
        self._file_editor = file_editor or SafeFileEditor()
        self._config = config or RepairCycleConfig()

        base_diagnoser = diagnoser or FailureDiagnoser(ai_provider)
        if self._config.rag_enabled and rag_engine is not None:
            self._diagnoser = RAGIntegratedDiagnoser(base_diagnoser, rag_engine=rag_engine)
        else:
            self._diagnoser = RAGIntegratedDiagnoser(base_diagnoser, rag_engine=None)

    @property
    def diagnoser(self) -> RAGIntegratedDiagnoser:
        return self._diagnoser
    def _should_continue(self, attempts, consecutive_failures) -> bool:
        """Check if we should continue retrying."""
        current_attempt = len(attempts)
        if current_attempt >= self._config.max_repair_attempts:
            return False
        return True
    async def run(self, context, evaluation, command_results, verification_commands, *, on_attempt_callback=None):
        """Run the bounded repair cycle."""
        attempts = []
        consecutive_repair_failures = 0
        for attempt_num in range(1, self._config.max_repair_attempts + 1):
            attempt = RepairAttempt(attempt_number=attempt_num)
            attempts.append(attempt)
            try:
                if isinstance(self._diagnoser, RAGIntegratedDiagnoser):
                    diagnosis, rk, confidence = await self._diagnoser.diagnose_with_rag(context, evaluation, command_results)
                else:
                    diagnosis = await self._diagnoser.diagnose(context, evaluation, command_results)
                    rk = []
                    _, confidence = DiagnosisConfidenceCalculator.build_evidence_from_failure(command_results, evaluation, diagnosis, None, context.project_files)
                attempt.diagnosis = diagnosis
                attempt.retrieved_knowledge = rk
                attempt.confidence = confidence
            except Exception as e:
                logger.error(f'Diagnosis failure: {e}')
                attempt.status = RepairStatus.REJECTED
                attempt.failure_reason = RepairFailureReason.DIAGNOSIS_FAILURE
                if on_attempt_callback: on_attempt_callback(attempt)
                consecutive_repair_failures += 1
                continue
            if self._config.rag_enabled and self._diagnoser._rag_engine is not None and not rk:
                attempt.failure_reason = RepairFailureReason.RAG_UNAVAILABLE
            repair_edits = await self._ai.generate_repair(context, diagnosis)
            if not repair_edits:
                attempt.status = RepairStatus.REJECTED
                attempt.failure_reason = RepairFailureReason.EMPTY_REPAIR
                if on_attempt_callback: on_attempt_callback(attempt)
                consecutive_repair_failures += 1
                if not self._should_continue(attempts, consecutive_repair_failures): break
                continue
            safe_edits = []
            for edit_dict in repair_edits:
                if not isinstance(edit_dict, dict) or "path" not in edit_dict: continue
                path = edit_dict["path"]
                new_content = edit_dict.get("content", edit_dict.get("new_content", ""))
                old_content = edit_dict.get("expected_content")
                old_hash = edit_dict.get("expected_content_hash")
                if not self._config.require_target_verification and old_content is None and old_hash is None:
                    try: old_content = self._env.filesystem.read_text(path)
                    except Exception: pass
                se = SafeFileEdit(target_path=path, new_content=new_content,
                    expected_content=old_content, expected_content_hash=old_hash,
                    edit_description=edit_dict.get("description", ""))
                safe_edits.append(se)
            if not safe_edits:
                attempt.status = RepairStatus.REJECTED
                attempt.failure_reason = RepairFailureReason.INVALID_REPAIR
                if on_attempt_callback: on_attempt_callback(attempt)
                consecutive_repair_failures += 1
                if not self._should_continue(attempts, consecutive_repair_failures): break
                continue
            attempt.file_edits = safe_edits
            edit_results = self._file_editor.apply_edits(safe_edits, context.workspace_root)
            attempt.edit_results = edit_results
            failed_edits = [er for er in edit_results if not er.success]
            if failed_edits:
                attempt.status = RepairStatus.REJECTED
                if any(er.status == RepairFailureReason.TARGET_MISMATCH for er in failed_edits):
                    attempt.failure_reason = RepairFailureReason.TARGET_MISMATCH
                else:
                    attempt.failure_reason = RepairFailureReason.INVALID_EDIT
                if on_attempt_callback: on_attempt_callback(attempt)
                consecutive_repair_failures += 1
                if not self._should_continue(attempts, consecutive_repair_failures): break
                continue
            reexec_results = []
            for cmd in verification_commands:
                if isinstance(cmd, CommandSpec):
                    cmd_res = await self._env.execute_command(cmd)
                elif isinstance(cmd, list):
                    cmd_res = await self._env.execute_command(CommandSpec(argv=cmd))
                else: continue
                reexec_results.append(cmd_res)
            attempt.reexecution_results = reexec_results
            reeval = self._evaluator.evaluate_attempt(reexec_results)
            attempt.reevaluation = reeval
            if reeval.passed:
                attempt.status = RepairStatus.SUCCESS
                attempt.failure_reason = RepairFailureReason.NONE
                consecutive_repair_failures = 0
                if on_attempt_callback: on_attempt_callback(attempt)
                if self._config.stop_on_first_repair_success:
                    return RepairResult(cycle_complete=True, final_status=RepairStatus.SUCCESS,
                        final_evaluation=reeval, attempts=attempts, total_attempts=attempt_num,
                        retry_exhausted=False, failure_reason=RepairFailureReason.NONE,
                        final_confidence=confidence)
            else:
                attempt.status = RepairStatus.FAILED
                attempt.failure_reason = RepairFailureReason.TESTS_STILL_FAILING
                consecutive_repair_failures += 1
                if on_attempt_callback: on_attempt_callback(attempt)
                evaluation = reeval
                if not self._should_continue(attempts, consecutive_repair_failures): break
        final_attempt = attempts[-1] if attempts else None
        return RepairResult(cycle_complete=True,
            final_status=(final_attempt.status if final_attempt and final_attempt.status != RepairStatus.SKIPPED else RepairStatus.FAILED),
            final_evaluation=(final_attempt.reevaluation if final_attempt else evaluation),
            attempts=attempts, total_attempts=len(attempts), retry_exhausted=True,
            failure_reason=(final_attempt.failure_reason if final_attempt else RepairFailureReason.RETRY_EXHAUSTED),
            final_confidence=(final_attempt.confidence if final_attempt else None))
