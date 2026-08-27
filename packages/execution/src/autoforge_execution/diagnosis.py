"""
Failure Diagnosis — analyzes failed attempts to guide reimplementation.

Captures failure evidence (stderr, stdout, exit codes, failed test names, file changes)
and produces a structured DiagnosisReport via AI Infrastructure reasoning.
"""

from __future__ import annotations

from typing import Any

from autoforge_execution.ai_adapter import AIEngineeringProvider
from autoforge_execution.context import ExecutionContext
from autoforge_execution.models import CommandResult, DiagnosisReport, EvaluationResult


class FailureDiagnoser:
    """
    Diagnoses failure mechanism and root cause from execution evidence.
    """

    def __init__(self, ai_provider: AIEngineeringProvider) -> None:
        self._ai = ai_provider

    async def diagnose(
        self,
        context: ExecutionContext,
        evaluation: EvaluationResult,
        command_results: list[CommandResult],
    ) -> DiagnosisReport:
        """
        Assemble failure evidence and run diagnostic reasoning.
        """
        # Collect failure evidence
        stderr_snippets = [c.stderr.strip() for c in command_results if c.stderr.strip()]
        stdout_snippets = [c.stdout.strip() for c in command_results if c.stdout.strip()]

        evidence: dict[str, Any] = {
            "status": evaluation.status.value,
            "failures": evaluation.failures,
            "recommendations": evaluation.recommendations,
            "test_summary": evaluation.test_results.model_dump() if evaluation.test_results else None,
            "stderr": "\n---\n".join(stderr_snippets)[:2000],
            "stdout": "\n---\n".join(stdout_snippets)[:2000],
            "failed_commands": [
                {"argv": c.command, "exit_code": c.exit_code, "timed_out": c.timed_out}
                for c in command_results
                if c.exit_code != 0 or c.timed_out
            ],
            "changed_files": context.project_files,
        }

        report = await self._ai.diagnose_failure(context, evidence)
        return report
