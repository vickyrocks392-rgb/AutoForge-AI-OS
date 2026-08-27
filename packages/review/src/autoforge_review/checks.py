"""Deterministic review rules — the NON-NEGOTIABLE core of Phase 11.

Every deterministic rule is a pure function of its inputs (source, evidence,
config).  AI reasoning NEVER overrides these checks (sections 7 and 21).

Each rule returns a ``RuleCheck`` which specialised reviewers translate into
a deterministic ``ReviewFinding``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from autoforge_review.models import FindingKind, Severity


@dataclass(frozen=True)
class RuleCheck:
    """One deterministic rule evaluation."""

    rule_id: str
    passed: bool
    message: str = ""
    severity: Severity = Severity.INFO
    file: str | None = None
    line: int | None = None
    kind: FindingKind = FindingKind.DEFECT
    evidence: list[str] = field(default_factory=list)


# ── Forbidden frameworks / dependencies ─────────────────────────────────────
# Sections 09, 21, 35: these frameworks must never enter the architecture.
FORBIDDEN_FRAMEWORKS: tuple[str, ...] = (
    "langchain",
    "langgraph",
    "crewai",
    "temporalio",
    "celery",
    "kafka",
    "redis",
    "airflow",
)

# Known good AutoForge package import prefixes (used by boundary default).
AUTOFORGE_PACKAGES = (
    "autoforge_models",
    "autoforge_events",
    "autoforge_runtime",
    "autoforge_ai_infrastructure",
    "autoforge_connectors",
    "autoforge_workflows",
    "autoforge_execution",
    "autoforge_kernel",
    "autoforge_review",
)


def check_forbidden_imports(
    source: str,
    *,
    file: str | None = None,
    forbidden: tuple[str, ...] = FORBIDDEN_FRAMEWORKS,
) -> RuleCheck:
    """Detect forbidden framework imports (deterministic)."""
    hits = [
        f
        for f in forbidden
        if re.search(rf"^\s*(import|from)\s+{f}\b", source, re.MULTILINE)
    ]
    return RuleCheck(
        rule_id="forbidden_framework",
        passed=not hits,
        message=(
            "Forbidden framework import: " + ", ".join(hits) if hits
            else "No forbidden framework imports."
        ),
        severity=Severity.CRITICAL if hits else Severity.MEDIUM,
        file=file,
        kind=FindingKind.POLICY_VIOLATION,
        evidence=[f"imported: {h}" for h in hits],
    )


def check_architecture_import(
    source: str,
    *,
    importer_prefix: str,
    boundary: dict[str, tuple[str, ...]],
    file: str | None = None,
) -> RuleCheck:
    """FAIL if a source matching ``importer_prefix`` imports a forbidden target.

    ``boundary`` maps an importer prefix to the forbidden import prefixes.
    """
    violations: list[str] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        m = re.match(r"^\s*(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", line)
        if not m:
            continue
        target = m.group(1)
        for forbidden in boundary.get(importer_prefix, ()):
            if target == forbidden or target.startswith(forbidden + "."):
                violations.append(
                    f"{file or importer_prefix}:{line_no} imports {target} (forbidden)"
                )
    return RuleCheck(
        rule_id="architecture_boundary",
        passed=not violations,
        message="; ".join(violations) if violations else f"Boundary respected for {importer_prefix}.",
        severity=Severity.HIGH,
        file=file,
        kind=FindingKind.ARCHITECTURE_EXCEPTION,
        evidence=violations,
    )

# ── Dangerous / insecure execution ────────────────────────────────────────
DANGEROUS_EXECUTION: tuple[tuple[str, tuple[Severity, str]], ...] = (
    (r"eval\s*\(", (Severity.HIGH, "dynamic evaluator (eval)")),
    (r"\bexec\s*\(", (Severity.HIGH, "dynamic exec")),
    (r"os\.system\s*\(", (Severity.HIGH, "OS shell invocation")),
    (r"shell\s*=\s*True", (Severity.HIGH, "subprocess shell=True")),
    (r"pickle\.loads?\s*\(", (Severity.MEDIUM, "unsafe pickle deserialization")),
    (r"yaml\.load\s*\([^)]*UnsafeLoader", (Severity.MEDIUM, "unsafe YAML loader")),
)


def check_dangerous_execution(source: str, *, file: str | None = None) -> RuleCheck:
    """Flag eval/exec/shell/pickle/unsafe-YAML patterns (deterministic)."""
    hits: list[tuple[int, str]] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        for pattern, (flag, name) in DANGEROUS_EXECUTION:
            if re.search(pattern, line):
                hits.append((line_no, f"{name} on line {line_no}"))
    if not hits:
        return RuleCheck(
            rule_id="dangerous_execution",
            passed=True,
            message="No dangerous execution patterns.",
            file=file,
        )
    return RuleCheck(
        rule_id="dangerous_execution",
        passed=False,
        message=f"{len(hits)} dangerous execution pattern(s).",
        severity=Severity.HIGH,
        file=file,
        line=hits[0][0],
        kind=FindingKind.SECURITY_VULNERABILITY,
        evidence=[m for _, m in hits],
    )


# ── Secret / credential leakage ────────────────────────────────────────────────────
_SECRET_PATTERNS: tuple[tuple[re.Pattern, Severity, str], ...] = (
    (re.compile(r"AKIA[0-9A-Z]{16}"), Severity.HIGH, "AWS access key"),
    (re.compile(r"BEGIN\s+(RSA|OPENSSH|EC|DSA)\s+PRIVATE\s+KEY"), Severity.HIGH, "private key"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), Severity.HIGH, "Google API key"),
    (re.compile(r"github_pat_[0-9A-Za-z_]{22,}"), Severity.HIGH, "GitHub PAT"),
    (re.compile(r"(api[\-_]?key|secret|passwd|password|token)\s*[=:]\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE), Severity.MEDIUM, "hardcoded credential"),
)


def check_secret_leak(source: str, *, file: str | None = None) -> RuleCheck:
    """Detect secrets / credentials in source (deterministic)."""
    found: list[tuple[int, str]] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        for pattern, severity, name in _SECRET_PATTERNS:
            if pattern.search(line):
                found.append((line_no, name))
    if not found:
        return RuleCheck(
            rule_id="secret_leak",
            passed=True,
            message="No credentials detected.",
            file=file,
        )
    sev = Severity.HIGH if any(any(k[1] == Severity.HIGH for k in _SECRET_PATTERNS
                                   if k[2] == name) for _, name in found) else Severity.MEDIUM
    return RuleCheck(
        rule_id="secret_leak",
        passed=False,
        message=f"{len(found)} secret(s) detected.",
        severity=sev,
        file=file,
        line=found[0][0],
        kind=FindingKind.SECURITY_VULNERABILITY,
        evidence=[f"line {ln}: {name}" for ln, name in found],
    )


def check_path_traversal(source: str, *, file: str | None = None) -> RuleCheck:
    """Flag unsanitised path usage (deterministic heuristics)."""
    hits: list[tuple[int, str]] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        if re.search(r"os\.path\.join\s*\([^)]*\.\.", line) and "validate" not in line:
            hits.append((line_no, "path join with .. segment"))
        if re.search(r"open\s*\([^)]*\.\.", line):
            hits.append((line_no, "open with .. segment"))
    if not hits:
        return RuleCheck(rule_id="path_traversal", passed=True, message="No traversal pattern.", file=file)
    return RuleCheck(
        rule_id="path_traversal",
        passed=False,
        message=f"{len(hits)} traversal-pattern(s).",
        severity=Severity.HIGH,
        file=file,
        line=hits[0][0],
        kind=FindingKind.SECURITY_VULNERABILITY,
        evidence=[m for _, m in hits],
    )
# ── Code complexity / error handling ───────────────────────────────────────


def check_complexity(
    source: str,
    *,
    file: str | None = None,
    max_nesting: int = 5,
    max_function_lines: int = 60,
) -> RuleCheck:
    """Heuristic nesting + oversized-function metric (deterministic)."""
    issues: list[str] = []
    max_depth = 0
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        depth = len(line) - len(line.lstrip())
        max_depth = max(max_depth, depth // 4)
    if max_depth >= max_nesting:
        issues.append(f"nesting depth {max_depth} >= {max_nesting}")

    for block in re.split(r"(?m)^(?=(?:\s*async\s+)?def\s)", source):
        if not re.match(r"\s*(async\s+)?def\s", block):
            continue
        non_blank = [l for l in block.splitlines() if l.strip()]
        if len(non_blank) >= max_function_lines:
            issues.append(
                f"function spans {len(non_blank)} non-blank lines >= {max_function_lines}"
            )

    if not issues:
        return RuleCheck(
            rule_id="complexity", passed=True, message="Complexity acceptable.", file=file
        )
    return RuleCheck(
        rule_id="complexity",
        passed=False,
        message="Complexity concerns: " + "; ".join(issues),
        severity=Severity.LOW,
        file=file,
        kind=FindingKind.QUALITY,
        evidence=issues,
    )


def check_bare_exceptions(source: str, *, file: str | None = None) -> RuleCheck:
    """Flag bare ``except:`` blocks (deterministic)."""
    line_no = next(
        (i for i, l in enumerate(source.splitlines(), start=1) if re.match(r"^\s*except\s*:", l)),
        None,
    )
    if line_no is None:
        return RuleCheck(
            rule_id="bare_except", passed=True, message="No bare except found.", file=file
        )
    return RuleCheck(
        rule_id="bare_except",
        passed=False,
        message="Bare except: suppresses errors.",
        severity=Severity.MEDIUM,
        file=file,
        line=line_no,
        kind=FindingKind.DEFECT,
        evidence=["bare except without exception type"],
    )


# ── Test / build evidence ───────────────────────────────────────────────────


def check_test_results(test_results: object) -> RuleCheck:
    """Determine test pass/fail from captured test evidence."""
    if test_results is None:
        return RuleCheck(
            rule_id="test_results", passed=True,
            message="No test evidence provided.", severity=Severity.INFO,
        )
    failed = test_results.failed_tests + test_results.error_tests
    if failed > 0:
        return RuleCheck(
            rule_id="test_results",
            passed=False,
            message=(
                f"{test_results.failed_tests} failures, {test_results.error_tests} errors "
                f"of {test_results.total_tests} tests."
            ),
            severity=Severity.HIGH,
            kind=FindingKind.DEFECT,
            evidence=list(test_results.failure_details)[:10],
        )
    return RuleCheck(
        rule_id="test_results",
        passed=True,
        message=f"All {test_results.total_tests} tests passed.",
    )


def check_build_success(build_exit_code: int | None) -> RuleCheck:
    """Deterministic: non-zero build exit code is failure."""
    if build_exit_code is None:
        return RuleCheck(
            rule_id="build", passed=True,
            message="No build evidence.", severity=Severity.INFO,
        )
    if build_exit_code != 0:
        return RuleCheck(
            rule_id="build",
            passed=False,
            message=f"Build failed with exit code {build_exit_code}.",
            severity=Severity.CRITICAL,
            kind=FindingKind.DEFECT,
        )
    return RuleCheck(rule_id="build", passed=True, message="Build succeeded.")
# ── Performance thresholds ──────────────────────────────────────────────────


def check_execution_time(metrics: dict[str, float], *, budget_ms: float = 5000.0) -> RuleCheck:
    """Deterministic: measured execution time above a regression budget."""
    if not metrics:
        return RuleCheck(
            rule_id="perf_time", passed=True,
            message="No timing evidence.", severity=Severity.INFO,
        )
    total = sum(metrics.values())
    if total > budget_ms:
        return RuleCheck(
            rule_id="perf_time",
            passed=False,
            message=f"Observed execution time {total:.0f}ms exceeds budget {budget_ms:.0f}ms.",
            severity=Severity.MEDIUM,
            kind=FindingKind.PERFORMANCE_REGRESSION,
            evidence=[f"{k}: {v:.0f}ms" for k, v in metrics.items()],
        )
    return RuleCheck(
        rule_id="perf_time", passed=True,
        message=f"Execution time {total:.0f}ms within budget.",
    )


def check_timeout(command_results: list[object]) -> RuleCheck:
    """Deterministic: any timed-out command is a performance/robustness finding."""
    timed = [c for c in command_results if getattr(c, "timed_out", False)]
    if not timed:
        return RuleCheck(rule_id="perf_timeout", passed=True, message="No timeouts observed.")
    return RuleCheck(
        rule_id="perf_timeout",
        passed=False,
        message=f"{len(timed)} command(s) timed out.",
        severity=Severity.HIGH,
        kind=FindingKind.PERFORMANCE_REGRESSION,
        evidence=[f"timed out: {c.command[-1]}" for c in timed[:10]],
    )


# ── Documentation requirements ──────────────────────────────────────────────


def check_required_files(source_files: dict[str, str], required: list[str]) -> RuleCheck:
    """Deterministic: required documentation/files must exist."""
    missing = [f for f in required if f not in source_files]
    if missing:
        return RuleCheck(
            rule_id="required_files",
            passed=False,
            message=f"Missing required file(s): {', '.join(missing)}",
            severity=Severity.HIGH,
            kind=FindingKind.DOCUMENTATION_GAP,
            evidence=missing,
        )
    return RuleCheck(
        rule_id="required_files", passed=True, message="All required files present."
    )


def check_readme_sections(
    source_files: dict[str, str],
    required: list[str],
    *,
    readme: str = "README.md",
) -> RuleCheck:
    """Deterministic: required markdown sections must exist in the README."""
    if readme not in source_files:
        return check_required_files(source_files, [readme])
    content = source_files[readme]
    headings = [h.strip() for h in re.findall(r"^(?:#+)\s+(.*)$", content, re.MULTILINE)]
    missing = [s for s in required if not any(h.lower() == s.lower() for h in headings)]
    if missing:
        return RuleCheck(
            rule_id="readme_sections",
            passed=False,
            message=f"README missing section(s): {', '.join(missing)}",
            severity=Severity.MEDIUM,
            kind=FindingKind.DOCUMENTATION_GAP,
            evidence=missing,
        )
    return RuleCheck(
        rule_id="readme_sections", passed=True, message="README sections complete."
    )


__all__ = [
    "RuleCheck",
    "FORBIDDEN_FRAMEWORKS",
    "AUTOFORGE_PACKAGES",
    "check_forbidden_imports",
    "check_architecture_import",
    "check_dangerous_execution",
    "check_secret_leak",
    "check_path_traversal",
    "check_complexity",
    "check_bare_exceptions",
    "check_test_results",
    "check_build_success",
    "check_execution_time",
    "check_timeout",
    "check_required_files",
        "check_readme_sections",
]