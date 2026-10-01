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


#: Labels pytest uses in its terminal summary that denote an actual test
#: outcome. Anything else on the summary line (notably ``warning``) is
#: deliberately ignored so a warning is never counted as a test.
_PYTEST_OUTCOME_LABELS: dict[str, str] = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "xfailed": "xfailed",
    "error": "error",
    "errors": "error",
}


def _parse_pytest_summary(combined: str) -> TestResultSummary | None:
    """Parse a real pytest terminal summary line.

    Real ``pytest -q`` output ends in an unwrapped timing line, e.g.::

        2 passed in 0.04s
        1 failed, 1 passed in 0.05s
        1 passed, 1 xfailed, 1 skipped in 0.05s

    The previous implementation required an ``=== ... in Xs ===`` wrapper that
    pytest never emits, so a real run was reported as "0 tests". This parses the
    summary line itself and is deliberately tolerant: the historical wrapped
    form still matches because the ``===`` characters are simply not part of any
    count label.

    ``total_tests`` is defined as the sum of the *outcome* categories
    (passed + failed + errors + skipped + xfailed). Warnings, deselections and
    other non-outcome annotations are excluded, so they can never inflate the
    total.

    Returns ``None`` when no outcome-bearing summary line is present, which lets
    the caller fall through to the unittest parser instead of fabricating an
    empty summary.
    """
    best: dict[str, int] | None = None
    best_line = ""

    for line in combined.splitlines():
        line = line.strip()
        # The timing clause anchors the match: "… in 1.20s", optionally wrapped
        # in "===" by the legacy format. ``re.search`` over the whole line keeps
        # this independent of leading progress characters or dots.
        timing = re.search(r"\bin\s+([\d.]+m?s)\b", line)
        if timing is None:
            continue
        head = line[: timing.start()]

        counts: dict[str, int] = {}
        for count_m in re.finditer(r"(\d+)\s+([A-Za-z_]+)", head):
            field = _PYTEST_OUTCOME_LABELS.get(count_m.group(2))
            if field is not None:
                counts[field] = counts.get(field, 0) + int(count_m.group(1))

        if not counts:
            continue
        # Prefer the last outcome-bearing line: pytest emits its final summary
        # after any progress output.
        best = counts
        best_line = line

    if best is None:
        return None

    passed = best.get("passed", 0)
    failed = best.get("failed", 0)
    errors = best.get("error", 0)
    skipped = best.get("skipped", 0)
    xfailed = best.get("xfailed", 0)
    total = passed + failed + errors + skipped + xfailed

    failures: list[str] = []
    if failed > 0 or errors > 0:
        for line in combined.splitlines():
            stripped = line.strip()
            if (
                stripped.startswith("FAILED ")
                or stripped.startswith("ERROR ")
                or "AssertionError" in stripped
            ):
                failures.append(stripped)

    return TestResultSummary(
        total_tests=total,
        passed_tests=passed,
        failed_tests=failed,
        error_tests=errors,
        skipped_tests=skipped,
        xfailed_tests=xfailed,
        failure_details=failures[:20],
        raw_summary_line=best_line.strip(),
    )


def parse_test_output(stdout: str, stderr: str) -> TestResultSummary:
    """
    Parse standard test runner output (pytest, unittest, or generic) into TestResultSummary.
    """
    combined = f"{stdout}\n{stderr}"

    # 1. pytest terminal summary, wrapped ("=== 5 passed in 0.12s ===") or not
    #    ("5 passed in 0.12s"). Real pytest emits the unwrapped form.
    pytest_summary = _parse_pytest_summary(combined)
    if pytest_summary is not None:
        return pytest_summary

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
