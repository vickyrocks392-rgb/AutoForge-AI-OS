"""
Unit tests for FailureDiagnoser and repair generation.
"""

import pytest

from autoforge_execution.ai_adapter import AIInfrastructureAdapter
from autoforge_execution.context import ExecutionContext
from autoforge_execution.diagnosis import FailureDiagnoser
from autoforge_execution.models import (
    CommandResult,
    EvaluationResult,
    EvaluationStatus,
    TestResultSummary,
)


@pytest.mark.asyncio
async def test_failure_diagnosis_from_evidence(tmp_path):
    ai = AIInfrastructureAdapter()
    diagnoser = FailureDiagnoser(ai)

    context = ExecutionContext(
        task_id="t-diag",
        task_name="Diagnose Bug",
        workspace_root=tmp_path,
        project_files=["app.py"],
    )

    cmd_res = CommandResult(
        command=["python", "test_app.py"],
        exit_code=1,
        stdout="FAIL: test_calc",
        stderr="AssertionError: 4 != 5",
        duration_seconds=0.1,
        timed_out=False,
    )
    eval_res = EvaluationResult(
        status=EvaluationStatus.FAILED,
        failures=["AssertionError: 4 != 5"],
        execution_results=[cmd_res],
    )

    report = await diagnoser.diagnose(context, eval_res, [cmd_res])
    assert report is not None
    assert "AssertionError" in report.root_cause or "failed" in report.root_cause.lower()
    assert report.confidence_score > 0.0


@pytest.mark.asyncio
async def test_repair_generation(tmp_path):
    ai = AIInfrastructureAdapter()
    diagnoser = FailureDiagnoser(ai)

    context = ExecutionContext(
        task_id="t-repair",
        task_name="Repair Bug",
        workspace_root=tmp_path,
        input_data={
            "repair_files": [{"path": "app.py", "content": "def fix(): return True"}]
        },
    )

    cmd_res = CommandResult(
        command=["python", "test_app.py"],
        exit_code=1,
        stdout="",
        stderr="Error",
        duration_seconds=0.1,
        timed_out=False,
    )
    eval_res = EvaluationResult(
        status=EvaluationStatus.FAILED,
        failures=["Error"],
    )
    diagnosis = await diagnoser.diagnose(context, eval_res, [cmd_res])

    repair_edits = await ai.generate_repair(context, diagnosis)
    assert len(repair_edits) == 1
    assert repair_edits[0]["path"] == "app.py"
    assert "def fix()" in repair_edits[0]["content"]
