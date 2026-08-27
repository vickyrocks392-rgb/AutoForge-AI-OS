"""
Evaluation Engine — deterministic verification boundary for the engineering loop.

Follows the Deterministic-First principle:
- Exit codes, test outputs, file existence, and static assertions are evaluated
  deterministically.
- AI qualitative analysis is an adjunct — model confidence can NEVER override
  a deterministic failure.
"""

from __future__ import annotations

import re
from typing import Any

from autoforge_execution.models import (
    CommandResult,
    DeterministicCheckResult,
    EvaluationResult,
    EvaluationStatus,
    TestResultSummary,
)


def parse_test_output(stdout: str, stderr: str) -> TestResultSummary:
    """
    Parse standard test runner output (pytest, unittest, or generic) into TestResultSummary.
    """
    combined = f"{stdout}\n{stderr}"
    
    # 1. Look for pytest style: e.g. "=== 5 passed, 1 failed in 0.12s ===" or "=== 2 failed, 8 passed in 1.20s ==="
    pytest_summary_match = re.search(r"===+\s*([^\n=]+in\s+[\d\.]+s)\s*===+", combined)
    if pytest_summary_match:
        summary_str = pytest_summary_match.group(1)
        passed_m = re.search(r"(\d+)\s+passed", summary_str)
        failed_m = re.search(r"(\d+)\s+failed", summary_str)
        skipped_m = re.search(r"(\d+)\s+skipped", summary_str)
        errors_m = re.search(r"(\d+)\s+error", summary_str)

        passed = int(passed_m.group(1)) if passed_m else 0
        failed = int(failed_m.group(1)) if failed_m else 0
        skipped = int(skipped_m.group(1)) if skipped_m else 0
        errors = int(errors_m.group(1)) if errors_m else 0
        total = passed + failed + skipped + errors
        if total > 0:
            failures = []
            if failed > 0 or errors > 0:
                for line in combined.splitlines():
                    if line.startswith("FAILED ") or line.startswith("ERROR ") or "AssertionError" in line:
                        failures.append(line.strip())
            return TestResultSummary(
                total_tests=total,
                passed_tests=passed,
                failed_tests=failed,
                error_tests=errors,
                skipped_tests=skipped,
                failure_details=failures[:20],
                raw_summary_line=summary_str.strip(),
            )

    # 2. Look for Python unittest style: "Ran 5 tests in 0.001s ... FAILED (failures=1)" or "OK"
    unittest_ran = re.search(r"Ran\s+(\d+)\s+tests?\s+in", combined)
    if unittest_ran:
        total = int(unittest_ran.group(1))
        if "OK" in combined:
            return TestResultSummary(
                total_tests=total,
                passed_tests=total,
                failed_tests=0,
                error_tests=0,
                skipped_tests=0,
                raw_summary_line=f"Ran {total} tests: OK",
            )
        failures = 0
        errors = 0
        fail_match = re.search(r"failures=(\d+)", combined)
        err_match = re.search(r"errors=(\d+)", combined)
        if fail_match:
            failures = int(fail_match.group(1))
        if err_match:
            errors = int(err_match.group(1))
        passed = max(0, total - failures - errors)
        return TestResultSummary(
            total_tests=total,
            passed_tests=passed,
            failed_tests=failures,
            error_tests=errors,
            skipped_tests=0,
            failure_details=[line.strip() for line in combined.splitlines() if line.startswith("FAIL:") or line.startswith("ERROR:")][:20],
            raw_summary_line=f"Ran {total} tests: FAILED (failures={failures}, errors={errors})",
        )

    # 3. Generic fallback
    return TestResultSummary(
        total_tests=0,
        passed_tests=0,
        failed_tests=0,
        error_tests=0,
        skipped_tests=0,
        raw_summary_line="",
    )


class EvaluationEngine:
    """
    Evaluates engineering attempt outcomes deterministically.
    """

    def evaluate_attempt(
        self,
        command_results: list[CommandResult],
        *,
        required_files_exist: list[bool] | None = None,
        custom_checks: list[DeterministicCheckResult] | None = None,
        qualitative_notes: str = "",
    ) -> EvaluationResult:
        """
        Produce a structured EvaluationResult for an engineering attempt.
        """
        deterministic_checks: list[DeterministicCheckResult] = []
        failures: list[str] = []
        recommendations: list[str] = []
        parsed_tests: TestResultSummary | None = None

        # Check 1: Command exit codes
        for cmd_res in command_results:
            cmd_str = " ".join(cmd_res.command)
            if cmd_res.timed_out:
                deterministic_checks.append(
                    DeterministicCheckResult(
                        check_name=f"command_timeout:{cmd_str[:30]}",
                        passed=False,
                        message=f"Command '{cmd_str}' timed out after {cmd_res.duration_seconds:.1f}s",
                    )
                )
                failures.append(f"Command '{cmd_str}' timed out")
                recommendations.append(f"Optimize command '{cmd_str}' or resolve infinite loop/deadlock")
            elif cmd_res.exit_code != 0:
                deterministic_checks.append(
                    DeterministicCheckResult(
                        check_name=f"command_exit_code:{cmd_str[:30]}",
                        passed=False,
                        message=f"Command '{cmd_str}' exited with non-zero code {cmd_res.exit_code}",
                        details={"exit_code": cmd_res.exit_code, "stderr": cmd_res.stderr[:500]},
                    )
                )
                failures.append(f"Command '{cmd_str}' failed with exit code {cmd_res.exit_code}")
            else:
                deterministic_checks.append(
                    DeterministicCheckResult(
                        check_name=f"command_exit_code:{cmd_str[:30]}",
                        passed=True,
                        message=f"Command '{cmd_str}' exited with code 0",
                    )
                )

            # Extract test summary if available
            test_summary = parse_test_output(cmd_res.stdout, cmd_res.stderr)
            if test_summary.total_tests > 0:
                parsed_tests = test_summary
                if not test_summary.all_passed:
                    deterministic_checks.append(
                        DeterministicCheckResult(
                            check_name="test_suite_passing",
                            passed=False,
                            message=f"{test_summary.failed_tests} failed, {test_summary.error_tests} errors out of {test_summary.total_tests} tests",
                            details={"details": test_summary.failure_details},
                        )
                    )
                    failures.append(f"Test suite failure: {test_summary.failed_tests} failed, {test_summary.error_tests} errors")
                    recommendations.append("Diagnose and fix failing unit test assertions")
                else:
                    deterministic_checks.append(
                        DeterministicCheckResult(
                            check_name="test_suite_passing",
                            passed=True,
                            message=f"All {test_summary.total_tests} tests passed",
                        )
                    )

        # Check 2: Required files check
        if required_files_exist is not None:
            all_exist = all(required_files_exist)
            deterministic_checks.append(
                DeterministicCheckResult(
                    check_name="required_files_exist",
                    passed=all_exist,
                    message="All required files exist" if all_exist else "Some required files are missing",
                )
            )
            if not all_exist:
                failures.append("Required output files were not generated")
                recommendations.append("Ensure target files are created and saved to workspace")

        # Check 3: Custom checks
        if custom_checks:
            for check in custom_checks:
                deterministic_checks.append(check)
                if not check.passed:
                    failures.append(f"Custom check '{check.check_name}' failed: {check.message}")

        # Determine overall status
        any_failed = any(not c.passed for c in deterministic_checks)
        if not command_results and not deterministic_checks:
            status = EvaluationStatus.INCONCLUSIVE
        elif any_failed:
            status = EvaluationStatus.FAILED
        else:
            status = EvaluationStatus.PASSED

        return EvaluationResult(
            status=status,
            deterministic_checks=deterministic_checks,
            test_results=parsed_tests,
            execution_results=command_results,
            qualitative_findings=qualitative_notes,
            failures=failures,
            recommendations=recommendations,
        )
