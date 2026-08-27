"""Tests for deterministic review checks (sections 7, 11, 12, 13).

Every check is a pure function of its inputs: repeated runs over identical
inputs must return equivalent results (deterministic reproducibility,
section 32).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from autoforge_execution.models import TestResultSummary

from autoforge_review.checks import (
    FORBIDDEN_FRAMEWORKS,
    RuleCheck,
    check_architecture_import,
    check_bare_exceptions,
    check_build_success,
    check_complexity,
    check_dangerous_execution,
    check_execution_time,
    check_forbidden_imports,
    check_path_traversal,
    check_readme_sections,
    check_required_files,
    check_secret_leak,
    check_test_results,
    check_timeout,
)


def test_forbidden_frameworks_defined() -> None:
    """FORBIDDEN_FRAMEWORKS must ban the reconciled-out frameworks (section 35)."""
    for fw in ("langchain", "langgraph", "crewai", "temporalio"):
        assert fw in FORBIDDEN_FRAMEWORKS


def test_check_forbidden_imports_detects_langgraph() -> None:
    """check_forbidden_imports must detect forbidden framework imports."""
    result = check_forbidden_imports("from langgraph import Graph\n")
    assert not result.passed
    assert "langgraph" in result.message.lower()


def test_check_forbidden_imports_passes_clean() -> None:
    """check_forbidden_imports must pass for clean imports."""
    result = check_forbidden_imports("import os\nimport sys\n")
    assert result.passed


def test_check_bare_exceptions_detects_bare_except() -> None:
    """check_bare_exceptions must detect bare except clauses."""
    result = check_bare_exceptions("try:\n    x = 1\nexcept:\n    pass\n")
    assert not result.passed


def test_check_secret_leak_detects_api_key() -> None:
    """check_secret_leak must detect hardcoded API keys."""
    result = check_secret_leak("API_KEY = 'sk-1234567890abcdef'\n")
    assert not result.passed


def test_check_secret_leak_passes_clean() -> None:
    """check_secret_leak must pass for clean code."""
    result = check_secret_leak("API_KEY = os.environ['KEY']\n")
    assert result.passed


def test_check_path_traversal_detects_traversal() -> None:
    """check_path_traversal must detect path traversal patterns."""
    result = check_path_traversal("open('../etc/passwd')")
    assert not result.passed


def test_check_dangerous_execution_detects_shell_true() -> None:
    """check_dangerous_execution must detect dangerous subprocess usage."""
    result = check_dangerous_execution("subprocess.call('ls', shell=True)")
    assert not result.passed


def test_check_required_files_detects_missing_readme() -> None:
    """check_required_files must detect missing required files."""
    result = check_required_files({"app.py": "x = 1\n"}, ["README.md"])
    assert not result.passed




def test_check_execution_time_detects_slow() -> None:
    """check_execution_time must flag timings beyond the regression budget."""
    result = check_execution_time({"task": 120.0}, budget_ms=100.0)
    assert not result.passed


def test_check_execution_time_passes_within_budget() -> None:
    """check_execution_time must pass within budget."""
    result = check_execution_time({"task": 10.0}, budget_ms=100.0)
    assert result.passed


def test_check_timeout_detects_timeout() -> None:
    """check_timeout must detect timeout events from command evidence."""
    timed_out = SimpleNamespace(command=["pytest", "-q"], timed_out=True)
    result = check_timeout([timed_out])
    assert not result.passed


def test_check_timeout_passes_without_timeouts() -> None:
    """check_timeout must pass when no command timed out."""
    ok = SimpleNamespace(command=["pytest", "-q"], timed_out=False)
    result = check_timeout([ok])
    assert result.passed


def test_check_complexity_detects_deep_nesting() -> None:
    """check_complexity must detect excessive nesting depth."""
    nested = "\n".join("    " * i + "if True:" for i in range(6))
    result = check_complexity(nested)
    assert not result.passed


def test_check_complexity_passes_simple_code() -> None:
    """check_complexity must pass simple code."""
    result = check_complexity("def f():\n    return 1\n")
    assert result.passed


def test_check_test_results_detects_failures() -> None:
    """check_test_results must detect test failures from Phase 10 evidence."""
    summary = TestResultSummary(total_tests=8, passed_tests=5, failed_tests=2)
    result = check_test_results(summary)
    assert not result.passed


def test_check_test_results_passes_clean() -> None:
    """check_test_results must pass when all tests passed."""
    summary = TestResultSummary(total_tests=10, passed_tests=10)
    result = check_test_results(summary)
    assert result.passed


def test_check_build_success_detects_failure() -> None:
    """check_build_success must treat a non-zero exit code as failure."""
    result = check_build_success(1)
    assert not result.passed


def test_check_build_success_passes_zero_exit() -> None:
    """check_build_success must pass on exit code 0."""
    result = check_build_success(0)
    assert result.passed


def test_check_architecture_import_detects_forbidden() -> None:
    """check_architecture_import must detect boundary violations."""
    result = check_architecture_import(
        "from autoforge_workflows import engine\n",
        importer_prefix="packages/review/",
        boundary={"packages/review/": ("autoforge_workflows",)},
        file="packages/review/app.py",
    )
    assert not result.passed


def test_check_architecture_import_passes_within_boundary() -> None:
    """check_architecture_import must pass imports inside the boundary."""
    result = check_architecture_import(
        "from autoforge_review import checks\n",
        importer_prefix="packages/review/",
        boundary={"packages/review/": ("autoforge_workflows",)},
    )
    assert result.passed


def test_all_checks_return_rule_check() -> None:
    """All check functions must return a RuleCheck."""
    checks = [
        lambda: check_forbidden_imports("x = 1"),
        lambda: check_bare_exceptions("x = 1"),
        lambda: check_secret_leak("x = 1"),
        lambda: check_path_traversal("x = 1"),
        lambda: check_dangerous_execution("x = 1"),
        lambda: check_required_files({"README.md": "# T"}, ["README.md"]),
        lambda: check_readme_sections({"README.md": "## Usage"}, ["Usage"]),
        lambda: check_execution_time({"t": 1.0}),
        lambda: check_timeout([SimpleNamespace(command=["ls"], timed_out=False)]),
        lambda: check_complexity("x = 1"),
        lambda: check_test_results(TestResultSummary(total_tests=1, passed_tests=1)),
        lambda: check_build_success(0),
        lambda: check_architecture_import(
            "import os", importer_prefix="pkg/", boundary={}
        ),
    ]
    for check_fn in checks:
        result = check_fn()
        assert isinstance(result, RuleCheck)
        assert hasattr(result, "rule_id")
        assert hasattr(result, "passed")
        assert hasattr(result, "message")


def test_deterministic_checks_are_reproducible() -> None:
    """Identical inputs must produce identical RuleCheck outcomes (section 32)."""
    source = "import subprocess\nsubprocess.call('x', shell=True)\n"
    first = check_dangerous_execution(source, file="a.py")
    second = check_dangerous_execution(source, file="a.py")
    assert first.passed == second.passed
    assert first.severity == second.severity
    assert first.message == second.message
    assert first.line == second.line

def test_check_required_files_passes_when_present() -> None:
    """check_required_files must pass when all required files exist."""
    result = check_required_files({"README.md": "# T\n"}, ["README.md"])
    assert result.passed

def test_check_execution_time_detects_slow() -> None:
    """check_execution_time must flag timings beyond the regression budget."""
    result = check_execution_time({"task": 120.0}, budget_ms=100.0)
    assert not result.passed


def test_check_execution_time_passes_within_budget() -> None:
    """check_execution_time must pass within budget."""
    result = check_execution_time({"task": 10.0}, budget_ms=100.0)
    assert result.passed


def test_check_timeout_detects_timeout() -> None:
    """check_timeout must detect timeout events from command evidence."""
    timed_out = SimpleNamespace(command=["pytest", "-q"], timed_out=True)
    result = check_timeout([timed_out])
    assert not result.passed


def test_check_timeout_passes_without_timeouts() -> None:
    """check_timeout must pass when no command timed out."""
    ok = SimpleNamespace(command=["pytest", "-q"], timed_out=False)
    result = check_timeout([ok])
    assert result.passed


def test_check_complexity_detects_deep_nesting() -> None:
    """check_complexity must detect excessive nesting depth."""
    nested = "\n".join("    " * i + "if True:" for i in range(6))
    result = check_complexity(nested)
    assert not result.passed


def test_check_complexity_passes_simple_code() -> None:
    """check_complexity must pass simple code."""
    result = check_complexity("def f():\n    return 1\n")
    assert result.passed


def test_check_test_results_detects_failures() -> None:
    """check_test_results must detect test failures from Phase 10 evidence."""
    summary = TestResultSummary(total_tests=8, passed_tests=5, failed_tests=2)
    result = check_test_results(summary)
    assert not result.passed


def test_check_test_results_passes_clean() -> None:
    """check_test_results must pass when all tests passed."""
    summary = TestResultSummary(total_tests=10, passed_tests=10)
    result = check_test_results(summary)
    assert result.passed


def test_check_build_success_detects_failure() -> None:
    """check_build_success must treat a non-zero exit code as failure."""
    result = check_build_success(1)
    assert not result.passed


def test_check_build_success_passes_zero_exit() -> None:
    """check_build_success must pass on exit code 0."""
    result = check_build_success(0)
    assert result.passed


def test_check_architecture_import_detects_forbidden() -> None:
    """check_architecture_import must detect boundary violations."""
    result = check_architecture_import(
        "from autoforge_workflows import engine\n",
        importer_prefix="packages/review/",
        boundary={"packages/review/": ("autoforge_workflows",)},
        file="packages/review/app.py",
    )
    assert not result.passed


def test_check_architecture_import_passes_within_boundary() -> None:
    """check_architecture_import must pass imports inside the boundary."""
    result = check_architecture_import(
        "from autoforge_review import checks\n",
        importer_prefix="packages/review/",
        boundary={"packages/review/": ("autoforge_workflows",)},
    )
    assert result.passed


def test_all_checks_return_rule_check() -> None:
    """All check functions must return a RuleCheck."""
    checks = [
        lambda: check_forbidden_imports("x = 1"),
        lambda: check_bare_exceptions("x = 1"),
        lambda: check_secret_leak("x = 1"),
        lambda: check_path_traversal("x = 1"),
        lambda: check_dangerous_execution("x = 1"),
        lambda: check_required_files({"README.md": "# T"}, ["README.md"]),
        lambda: check_readme_sections({"README.md": "## Usage"}, ["Usage"]),
        lambda: check_execution_time({"t": 1.0}),
        lambda: check_timeout([SimpleNamespace(command=["ls"], timed_out=False)]),
        lambda: check_complexity("x = 1"),
        lambda: check_test_results(TestResultSummary(total_tests=1, passed_tests=1)),
        lambda: check_build_success(0),
        lambda: check_architecture_import(
            "import os", importer_prefix="pkg/", boundary={}
        ),
    ]
    for check_fn in checks:
        result = check_fn()
        assert isinstance(result, RuleCheck)
        assert hasattr(result, "rule_id")
        assert hasattr(result, "passed")
        assert hasattr(result, "message")


def test_deterministic_checks_are_reproducible() -> None:
    """Identical inputs must produce identical RuleCheck outcomes (section 32)."""
    source = "import subprocess\nsubprocess.call('x', shell=True)\n"
    first = check_dangerous_execution(source, file="a.py")
    second = check_dangerous_execution(source, file="a.py")
    assert first.passed == second.passed
    assert first.severity == second.severity
    assert first.message == second.message
    assert first.line == second.line


def test_check_readme_sections_detects_incomplete() -> None:
    """check_readme_sections must detect missing README sections."""
    result = check_readme_sections({"README.md": "# Title\n\nBody.\n"}, ["Usage"])
    assert not result.passed


def test_check_readme_sections_passes_complete() -> None:
    """check_readme_sections must pass a README with required sections."""
    result = check_readme_sections(
        {"README.md": "# Title\n\n## Usage\n"}, ["Usage"]
    )
    assert result.passed
