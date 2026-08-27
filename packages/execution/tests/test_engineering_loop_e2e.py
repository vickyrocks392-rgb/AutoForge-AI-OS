"""
Mandatory Real End-to-End Acceptance Test for Autonomous Engineering Loop (Phase 10).

Demonstrates the genuine autonomous engineering cycle:
1. Understand engineering objective
2. Generate initial implementation
3. Execute real subprocess test command in workspace
4. Detect real test failure (non-zero exit code / AssertionError)
5. Deterministic evaluation records FAILED
6. AI reasoning diagnoses failure from stderr/stdout evidence
7. Informed repair/reimplementation generated from diagnosis
8. Retest in workspace with real command execution
9. Retest PASSES (exit code 0)
10. Final artifacts & provenance recorded and loop completed
"""

import sys
from pathlib import Path
import pytest

from autoforge_workflows.models import TaskDefinition

from autoforge_execution.ai_adapter import AIEngineeringProvider
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.context import ExecutionContext
from autoforge_execution.diagnosis import FailureDiagnoser
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.evaluation import EvaluationEngine
from autoforge_execution.loop import EngineeringLoop
from autoforge_execution.models import (
    ArtifactType,
    CommandSpec,
    DiagnosisReport,
    EvaluationStatus,
    LoopConfig,
    LoopStatus,
    WorkerType,
)
from autoforge_execution.worker import EngineeringWorker


class DeterministicE2EAIProvider(AIEngineeringProvider):
    """
    Deterministic AI provider test double simulating model reasoning over attempts.
    Attempt 1: Intentionally implements buggy logic (addition instead of multiplication).
    Diagnosis: Analyzes the real failure output (e.g. 7 != 12) and diagnoses root cause.
    Attempt 2 (Repair): Generates the correct multiplication logic informed by diagnosis.
    """

    def __init__(self) -> None:
        self.diagnoses_performed: list[DiagnosisReport] = []
        self.plans_generated: list[str] = []
        self.repairs_generated: list[dict] = []

    async def generate_plan(self, context: ExecutionContext) -> str:
        plan = f"Plan to implement calculator multiply function for {context.task_name}"
        self.plans_generated.append(plan)
        return plan

    async def generate_implementation(
        self,
        context: ExecutionContext,
        plan: str,
    ) -> list[dict]:
        # Buggy initial implementation: addition instead of multiplication
        return [
            {
                "path": "calculator.py",
                "content": "def multiply(a: int, b: int) -> int:\n    # Bug: returns addition instead of product\n    return a + b\n",
            }
        ]

    async def diagnose_failure(
        self,
        context: ExecutionContext,
        failure_evidence: dict,
    ) -> DiagnosisReport:
        stderr = failure_evidence.get("stderr", "")
        stdout = failure_evidence.get("stdout", "")
        combined = f"{stdout}\n{stderr}"

        # Diagnose that addition was used instead of multiplication
        root_cause = "Calculator.multiply implemented addition (a + b) instead of multiplication (a * b)"
        if "7 != 12" in combined or "AssertionError" in combined or "FAIL" in combined:
            failure_mechanism = "Assertion failure: multiply(3, 4) returned 7 (3+4) instead of expected 12 (3*4)"
        else:
            failure_mechanism = "Test failed with non-zero exit code"

        diagnosis = DiagnosisReport(
            root_cause=root_cause,
            failure_mechanism=failure_mechanism,
            affected_files=["calculator.py"],
            suggested_fix="Change 'return a + b' to 'return a * b' in calculator.py",
            confidence_score=0.98,
        )
        self.diagnoses_performed.append(diagnosis)
        return diagnosis

    async def generate_repair(
        self,
        context: ExecutionContext,
        diagnosis: DiagnosisReport,
    ) -> list[dict]:
        # Informed repair generated based on root cause diagnosis
        repair = [
            {
                "path": "calculator.py",
                "content": "def multiply(a: int, b: int) -> int:\n    # Repaired: correct multiplication\n    return a * b\n",
            }
        ]
        self.repairs_generated.append(repair)
        return repair


@pytest.mark.asyncio
async def test_real_autonomous_engineering_loop_e2e(tmp_path: Path):
    """
    Test genuine autonomous engineering loop with real file modification and command execution.
    """
    # 1. Setup workspace environment
    env = WorkspaceEnvironment(tmp_path)

    # 2. Create the test file in the workspace
    test_file_content = (
        "import unittest\n"
        "from calculator import multiply\n\n"
        "class TestCalculator(unittest.TestCase):\n"
        "    def test_multiply_positive(self):\n"
        "        self.assertEqual(multiply(3, 4), 12)\n\n"
        "    def test_multiply_negative(self):\n"
        "        self.assertEqual(multiply(-2, 5), -10)\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )
    env.filesystem.write_text("test_calculator.py", test_file_content)

    # 3. Setup AI provider and artifacts
    ai_provider = DeterministicE2EAIProvider()
    artifacts = ArtifactPipeline()

    # 4. Create worker
    worker = EngineeringWorker(
        worker_id="e2e-engineer-01",
        worker_type=WorkerType.CODING,
        environment=env,
        ai_provider=ai_provider,
        artifact_pipeline=artifacts,
        loop_config=LoopConfig(max_iterations=3, timeout_seconds=30.0),
    )

    # 5. Define task and context
    task_def = TaskDefinition(
        task_id="task-calc-multiply",
        name="Implement Calculator Multiply Function",
        description="Implement multiply(a, b) in calculator.py so test_calculator.py passes.",
        input_data={
            "commands": [[sys.executable, "test_calculator.py"]],
        },
    )
    context = ExecutionContext.from_task_definition(task_def, env.root)
    context.project_files = ["calculator.py", "test_calculator.py"]

    # 6. Execute task through worker
    passed, produced_artifacts, final_eval = await worker.execute_task(context)

    # ── VERIFICATIONS ────────────────────────────────────────────────────────

    # 1. Loop succeeded
    assert passed is True
    assert worker.status.value == "completed"
    assert final_eval is not None
    assert final_eval.status == EvaluationStatus.PASSED

    # 2. Exactly 2 iterations were executed (Iteration 1 failed, Iteration 2 passed)
    assert len(worker.state.iteration_history) == 2
    iter1 = worker.state.iteration_history[0]
    iter2 = worker.state.iteration_history[1]

    # Iteration 1 verification:
    assert iter1.iteration == 1
    assert iter1.passed is False
    assert iter1.evaluation is not None
    assert iter1.evaluation.status == EvaluationStatus.FAILED
    assert iter1.diagnosis is not None
    assert "calculator.multiply" in iter1.diagnosis.root_cause.lower() or "addition" in iter1.diagnosis.root_cause.lower()

    # Iteration 2 verification:
    assert iter2.iteration == 2
    assert iter2.passed is True
    assert iter2.evaluation is not None
    assert iter2.evaluation.status == EvaluationStatus.PASSED

    # 3. Verify real file on disk was modified to the working implementation
    calc_disk_content = env.filesystem.read_text("calculator.py")
    assert "return a * b" in calc_disk_content

    # 4. Verify AI provider methods were called in correct sequence
    assert len(ai_provider.plans_generated) == 1
    assert len(ai_provider.diagnoses_performed) == 1
    assert len(ai_provider.repairs_generated) == 1

    # 5. Verify rich artifacts and provenance were captured
    task_arts = artifacts.get_artifacts_for_task("task-calc-multiply")
    assert len(task_arts) > 0

    art_types = {a.artifact_type for a in task_arts}
    assert ArtifactType.DIFF in art_types
    assert ArtifactType.EXECUTION_LOG in art_types
    assert ArtifactType.EVALUATION_REPORT in art_types
    assert ArtifactType.DIAGNOSIS_REPORT in art_types

    # 6. Verify command execution actually succeeded on disk
    verify_cmd = await env.execute_command([sys.executable, "test_calculator.py"])
    assert verify_cmd.passed
    assert verify_cmd.exit_code == 0
