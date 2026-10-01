"""
F-01 regression: real ``pytest -q`` output parsing.

Phase 18-LF finding F-01: ``parse_test_output`` required an
``=== ... in Xs ===`` wrapper that pytest never emits, so a real run was
reported as "0 tests" ("Verification command passed (0 tests)."). The
completion gate was never at risk (it derives safety from ``exit_code``), but
the *evidence* reaching the Review Engine carried no counts.

Every string below is a real ``pytest`` terminal summary, captured verbatim from
actual pytest runs — including the progress line and the short-test-summary
block that precede it.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from autoforge_execution.evaluation import parse_test_output


# ── 1. all passed ───────────────────────────────────────────────────────────
def test_real_pytest_all_passed():
    stdout = (
        "..                                                                   [100%]\n"
        "2 passed in 0.04s\n"
    )
    s = parse_test_output(stdout, "")
    assert (s.passed_tests, s.failed_tests, s.error_tests) == (2, 0, 0)
    assert (s.skipped_tests, s.xfailed_tests) == (0, 0)
    assert s.total_tests == 2
    assert s.all_passed is True
    assert s.raw_summary_line == "2 passed in 0.04s"


# ── 2. failed + passed ──────────────────────────────────────────────────────
def test_real_pytest_failed_and_passed():
    stdout = (
        ".F.                                                                  [100%]\n"
        "=================================== FAILURES ===================================\n"
        "________________________________ test_bad _____________________________________\n"
        "    def test_bad():\n"
        ">       assert 1 == 999\n"
        "E       assert 1 == 999\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_probe.py::test_bad - assert 1 == 999\n"
        "1 failed, 1 passed in 0.05s\n"
    )
    s = parse_test_output(stdout, "")
    assert (s.passed_tests, s.failed_tests, s.error_tests) == (1, 1, 0)
    assert s.total_tests == 2
    assert s.all_passed is False
    assert any("test_bad" in d for d in s.failure_details)


# ── 3. all failed ───────────────────────────────────────────────────────────
def test_real_pytest_all_failed():
    stdout = (
        "FF                                                                   [100%]\n"
        "2 failed in 0.08s\n"
    )
    s = parse_test_output(stdout, "")
    assert (s.passed_tests, s.failed_tests) == (0, 2)
    assert s.total_tests == 2
    assert s.all_passed is False


# ── 4. skipped ──────────────────────────────────────────────────────────────
def test_real_pytest_skipped():
    s = parse_test_output(".s                                                                   [100%]\n"
                          "1 passed, 1 skipped in 0.05s\n", "")
    assert (s.passed_tests, s.skipped_tests) == (1, 1)
    # A skipped test is NOT a pass and NOT a failure.
    assert s.total_tests == 2
    assert s.all_passed is True  # nothing failed
    assert s.passed_tests == 1  # but it was not counted as passed


# ── 5. xfailed ──────────────────────────────────────────────────────────────
def test_real_pytest_xfailed():
    s = parse_test_output(".x                                                                   [100%]\n"
                          "1 passed, 1 xfailed in 0.05s\n", "")
    assert (s.passed_tests, s.xfailed_tests) == (1, 1)
    assert s.total_tests == 2
    assert s.passed_tests == 1  # xfailed is NOT treated as passed


# ── 6. mixed skipped + xfailed ─────────────────────────────────────────────
def test_real_pytest_mixed_skipped_xfailed():
    s = parse_test_output(".sx                                                                  [100%]\n"
                          "1 passed, 1 xfailed, 1 skipped in 0.05s\n", "")
    assert (s.passed_tests, s.xfailed_tests, s.skipped_tests) == (1, 1, 1)
    assert s.total_tests == 3
    assert s.failed_tests == 0


# ── 7. warnings must NOT be counted as tests ────────────────────────────────
def test_real_pytest_warnings_are_not_tests():
    stdout = (
        "..                                                                   [100%]\n"
        "=========================== warnings summary ===============================\n"
        "test_probe.py:3\n"
        "  DeprecationWarning: something is deprecated\n"
        "2 passed, 1 warning in 0.04s\n"
    )
    s = parse_test_output(stdout, "")
    assert s.passed_tests == 2
    assert s.total_tests == 2, "a warning must never inflate total_tests"
    assert s.all_passed is True


# ── 8. legacy wrapped format still supported ────────────────────────────────
def test_legacy_wrapped_format_still_supported():
    s = parse_test_output("=== 10 passed in 0.45s ===", "")
    assert (s.passed_tests, s.total_tests) == (10, 10)
    assert s.all_passed is True


def test_legacy_wrapped_format_failed_still_supported():
    s = parse_test_output(
        "FAILED tests/test_calc.py::test_add - AssertionError\n"
        "=== 2 failed, 8 passed in 1.20s ===",
        "",
    )
    assert (s.passed_tests, s.failed_tests, s.total_tests) == (8, 2, 10)
    assert s.failure_details


# ── 9. malformed / unrecognised output ──────────────────────────────────────
@pytest.mark.parametrize(
    "payload",
    [
        "",
        "some totally unrelated tool output",
        "Traceback (most recent call last):\n  RuntimeError: boom",
        "100% done, nothing to see here",  # no timing clause, no counts
    ],
)
def test_malformed_output_yields_no_fabricated_counts(payload):
    s = parse_test_output(payload, "")
    assert s.total_tests == 0
    assert s.passed_tests == 0
    assert s.failed_tests == 0


# ── 10. progress line present but NO summary line ───────────────────────────
def test_progress_dots_without_summary_line():
    """pytest killed mid-run: dots but no summary. Must not invent counts."""
    s = parse_test_output("..F..                                      [ 60%]\n", "")
    assert s.total_tests == 0
    assert s.passed_tests == 0


def test_no_tests_ran():
    s = parse_test_output("no tests ran in 0.01s\n", "")
    assert s.total_tests == 0


# ── 11. pluralisation variations ────────────────────────────────────────────
def test_singular_error_label():
    s = parse_test_output("E                                                                   [100%]\n"
                          "1 error in 0.02s\n", "")
    assert s.error_tests == 1
    assert s.total_tests == 1
    assert s.all_passed is False


def test_plural_errors_label():
    s = parse_test_output("EE                                                                  [100%]\n"
                          "2 errors in 0.03s\n", "")
    assert s.error_tests == 2
    assert s.total_tests == 2


def test_long_duration_format():
    """pytest's real long-run format is ``90.12s (0:01:30)``, not ``1m30s``.

    Verified against ``_pytest.terminal.format_session_duration``: below 60s it
    emits ``N.NNs``; at or above 60s it emits ``N.NNs (H:MM:SS)``.
    """
    s = parse_test_output(".....                                                                  [100%]\n"
                          "5 passed in 90.12s (0:01:30)\n", "")
    assert s.passed_tests == 5
    assert s.total_tests == 5


def test_microsecond_duration_format():
    s = parse_test_output("..                                                                   [100%]\n"
                          "2 passed in 0.00s\n", "")
    assert s.passed_tests == 2


# ── 12. unittest format must still win over the pytest branch ───────────────
def test_unittest_format_still_parsed():
    s = parse_test_output("", "Ran 4 tests in 0.002s\n\nOK")
    assert (s.passed_tests, s.total_tests) == (4, 4)


def test_unittest_failure_format_still_parsed():
    s = parse_test_output(
        "",
        "FAIL: test_sub (__main__.TestCalc)\nAssertionError: 2 != 3\n\n"
        "Ran 4 tests in 0.003s\n\nFAILED (failures=1)",
    )
    assert s.failed_tests == 1
    assert s.total_tests == 4


# ── 13. REAL pytest execution (the actual F-01 reproduction) ───────────────
def _run_real_pytest(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    (tmp_path / "test_generated.py").write_text(textwrap.dedent(body))
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_generated.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_real_pytest_execution_passing(tmp_path):
    """REAL pytest, all passing -> accurate counts, exit 0."""
    res = _run_real_pytest(
        tmp_path,
        """
        def test_a():
            assert True

        def test_b():
            assert True
        """,
    )
    s = parse_test_output(res.stdout, res.stderr)
    assert res.returncode == 0
    assert s.passed_tests == 2
    assert s.failed_tests == 0
    assert s.total_tests == 2
    assert s.all_passed is True


def test_real_pytest_execution_failing(tmp_path):
    """REAL pytest, one failure -> accurate counts, non-zero exit.

    This is the exact scenario F-01 mis-reported as "0 tests".
    """
    res = _run_real_pytest(
        tmp_path,
        """
        def test_ok():
            assert True

        def test_bad():
            assert 1 == 999
        """,
    )
    s = parse_test_output(res.stdout, res.stderr)
    assert res.returncode != 0
    assert s.passed_tests == 1
    assert s.failed_tests == 1
    assert s.total_tests == 2
    assert s.all_passed is False


def test_real_pytest_execution_skipped_and_xfail(tmp_path):
    """REAL pytest, skip + xfail -> neither counted as passed."""
    res = _run_real_pytest(
        tmp_path,
        """
        import pytest

        def test_ok():
            assert True

        @pytest.mark.skip(reason="not ready")
        def test_skipped():
            assert True

        @pytest.mark.xfail(reason="known bug")
        def test_xfail():
            assert False
        """,
    )
    s = parse_test_output(res.stdout, res.stderr)
    assert s.passed_tests == 1
    assert s.skipped_tests == 1
    assert s.xfailed_tests == 1
    assert s.total_tests == 3
    assert s.failed_tests == 0
