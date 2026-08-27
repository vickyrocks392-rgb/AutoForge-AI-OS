"""
Unit tests for EvaluationEngine and test output parsing.
"""

from autoforge_execution.evaluation import EvaluationEngine, parse_test_output
from autoforge_execution.models import (
    CommandResult,
    DeterministicCheckResult,
    EvaluationStatus,
)


def test_parse_pytest_output_passed():
    stdout = "=== 10 passed in 0.45s ==="
    summary = parse_test_output(stdout, "")
    assert summary.total_tests == 10
    assert summary.passed_tests == 10
    assert summary.failed_tests == 0
    assert summary.all_passed


def test_parse_pytest_output_failed():
    stdout = "FAILED tests/test_calc.py::test_add - AssertionError\n=== 2 failed, 8 passed in 1.20s ==="
    summary = parse_test_output(stdout, "")
    assert summary.total_tests == 10
    assert summary.passed_tests == 8
    assert summary.failed_tests == 2
    assert not summary.all_passed
    assert len(summary.failure_details) > 0


def test_parse_unittest_output_ok():
    stderr = "Ran 4 tests in 0.002s\n\nOK"
    summary = parse_test_output("", stderr)
    assert summary.total_tests == 4
    assert summary.passed_tests == 4
    assert summary.failed_tests == 0
    assert summary.all_passed


def test_parse_unittest_output_failed():
    stderr = "FAIL: test_sub (__main__.TestCalc)\nAssertionError: 2 != 3\n\nRan 4 tests in 0.003s\n\nFAILED (failures=1)"
    summary = parse_test_output("", stderr)
    assert summary.total_tests == 4
    assert summary.failed_tests == 1
    assert not summary.all_passed


def test_evaluation_engine_all_passed():
    evaluator = EvaluationEngine()
    cmd = CommandResult(
        command=["pytest"],
        exit_code=0,
        stdout="=== 5 passed in 0.2s ===",
        stderr="",
        duration_seconds=0.2,
        timed_out=False,
    )
    res = evaluator.evaluate_attempt([cmd], required_files_exist=[True])
    assert res.status == EvaluationStatus.PASSED
    assert res.passed
    assert len(res.failures) == 0


def test_evaluation_engine_command_failed():
    evaluator = EvaluationEngine()
    cmd = CommandResult(
        command=["pytest"],
        exit_code=1,
        stdout="=== 1 failed in 0.2s ===",
        stderr="AssertionError",
        duration_seconds=0.2,
        timed_out=False,
    )
    res = evaluator.evaluate_attempt([cmd])
    assert res.status == EvaluationStatus.FAILED
    assert not res.passed
    assert len(res.failures) > 0
