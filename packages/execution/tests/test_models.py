"""
Unit tests for Execution Platform domain models and value objects.
"""

import uuid
from datetime import datetime, timezone

import pytest

from autoforge_execution.models import (
    ArtifactProvenance,
    ArtifactRecord,
    ArtifactType,
    CommandResult,
    CommandSpec,
    ConsequentialActionType,
    DeterministicCheckResult,
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    GovernancePolicy,
    LoopConfig,
    LoopIterationRecord,
    LoopStatus,
    TestResultSummary,
    WorkerState,
    WorkerStatus,
    WorkerType,
)


def test_worker_status_and_state():
    state = WorkerState(
        worker_id="w-1",
        worker_type=WorkerType.CODING,
        task_id="t-1",
        status=WorkerStatus.CREATED,
    )
    assert state.status == WorkerStatus.CREATED
    assert not state.is_terminal

    state.status = WorkerStatus.COMPLETED
    assert state.is_terminal

    snap = state.to_snapshot()
    assert snap["worker_id"] == "w-1"
    assert snap["status"] == "completed"


def test_command_spec_and_result():
    spec = CommandSpec(argv=["pytest", "-q"], timeout_seconds=10.0)
    assert spec.argv == ["pytest", "-q"]
    assert spec.timeout_seconds == 10.0

    res = CommandResult(
        command=["python", "test.py"],
        exit_code=0,
        stdout="OK",
        stderr="",
        duration_seconds=0.5,
        timed_out=False,
    )
    assert res.passed
    assert res.exit_code == 0

    fail_res = CommandResult(
        command=["python", "test.py"],
        exit_code=1,
        stdout="",
        stderr="Error",
        duration_seconds=0.2,
        timed_out=False,
    )
    assert not fail_res.passed


def test_evaluation_result_and_deterministic_checks():
    check1 = DeterministicCheckResult(
        check_name="exit_code",
        passed=True,
        message="Process exited with 0",
    )
    test_summary = TestResultSummary(
        total_tests=5,
        passed_tests=5,
        failed_tests=0,
        error_tests=0,
    )
    eval_res = EvaluationResult(
        status=EvaluationStatus.PASSED,
        deterministic_checks=[check1],
        test_results=test_summary,
        failures=[],
    )
    assert eval_res.passed
    assert eval_res.status == EvaluationStatus.PASSED


def test_artifact_record_and_provenance():
    prov = ArtifactProvenance(
        task_id="t-100",
        worker_id="w-1",
        attempt_number=1,
        iteration=1,
    )
    art = ArtifactRecord.create(
        name="test.py",
        artifact_type=ArtifactType.SOURCE_CODE,
        content="print('hello')",
        provenance=prov,
    )
    assert art.name == "test.py"
    assert art.size_bytes == 14
    assert len(art.checksum) == 64  # SHA256 hex string


def test_governance_policy():
    policy = GovernancePolicy()
    assert ConsequentialActionType.TECH_STACK_FINALIZATION in policy.consequential_actions_requiring_approval
    assert ConsequentialActionType.GIT_PUSH in policy.consequential_actions_requiring_approval
    assert policy.auto_approve_safe_actions
