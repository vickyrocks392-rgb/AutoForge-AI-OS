"""Verification of generated code.

Every LLM-generated or hybrid-generated artifact enters this verification path.
At minimum:

* syntax validation
* compiler/build validation where available
* static analysis where available
* tests where available
* semantic/behavioral verification where available

Failures produce structured diagnostics that are directly consumable by the
repair loop.  When a verification tool is genuinely unavailable (e.g. no Java
runtime on the host) the check is recorded as ``UNDEFINED`` with the real reason
— never silently reported as PASS.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VerificationLevel(str, Enum):
    SYNTAX = "syntax"
    COMPILE = "compile"
    STATIC = "static"
    TESTS = "tests"
    SEMANTIC_BEHAVIORAL = "semantic_behavioral"


class VerificationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNDEFINED = "undefined"
    NOT_APPLICABLE = "not_applicable"


# Stable machine-readable diagnostic code emitted when the required external
# toolchain (compiler / build tool) could not be discovered or executed, so the
# check never ran at all.  This is deliberately distinct from a source-code
# defect so the repair cycle can tell "no compiler" from "broken code".
TOOLCHAIN_UNAVAILABLE_CODE = "TOOLCHAIN_UNAVAILABLE"


class VerificationDiagnostic(BaseModel):
    """One structured diagnostic produced by a verification check."""

    diagnostic_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    level: VerificationLevel
    check: str
    severity: str = "error"  # error | warning | info
    message: str = ""
    location: str = ""       # file:line or n/a
    code: str = ""           # stable machine-readable code
    tool: str = ""


class VerificationCheckResult(BaseModel):
    """Outcome of a single verification check."""

    level: VerificationLevel
    check: str
    status: VerificationStatus
    tool: str = ""
    detail: str = ""
    diagnostics: list[VerificationDiagnostic] = Field(default_factory=list)


class VerificationReport(BaseModel):
    """The complete verification result for one generated artifact."""

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    artifact_id: str = ""
    target_technology: str = ""
    status: VerificationStatus = VerificationStatus.UNDEFINED
    checks: list[VerificationCheckResult] = Field(default_factory=list)
    diagnostics: list[VerificationDiagnostic] = Field(default_factory=list)
    duration_ms: int = 0
    verified_at: datetime = Field(default_factory=_utc_now)

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASS

    def failures(self) -> list[VerificationDiagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    def summary(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "artifact_id": self.artifact_id,
            "status": self.status.value,
            "checks": [
                {"level": c.level.value, "check": c.check, "status": c.status.value}
                for c in self.checks
            ],
            "diagnostics": len(self.diagnostics),
            "failures": len(self.failures()),
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# Deterministic syntax checks
# ---------------------------------------------------------------------------


def _java_structural_check(content: str) -> VerificationCheckResult:
    """Deterministic lightweight structural lint for emitted Java.

    Not a substitute for javac — a real javac PASS is required for compile
    verification.  This only catches clearly-broken output (unbalanced braces,
    invalid identifiers, missing class body).
    """
    diagnostics: list[VerificationDiagnostic] = []
    stripped_lines = [ln for ln in content.splitlines()]
    depth = 0
    for lineno, line in enumerate(stripped_lines, start=1):
        s = line.lstrip()
        if s.startswith("//") or s.startswith("/*") or s.startswith("*"):
            continue
        depth += line.count("{") - line.count("}")
        if depth < 0:
            diagnostics.append(
                VerificationDiagnostic(
                    level=VerificationLevel.SYNTAX,
                    check="brace balance",
                    severity="error",
                    message="Unbalanced closing brace",
                    location=f"<generated>:{lineno}",
                    code="BRACE_UNBALANCED",
                    tool="autoforge-java-struct-lint",
                )
            )
            break
    if depth != 0:
        diagnostics.append(
            VerificationDiagnostic(
                level=VerificationLevel.SYNTAX,
                check="brace balance",
                severity="error",
                message=f"Unbalanced braces (final depth={depth})",
                code="BRACE_UNBALANCED",
                tool="autoforge-java-struct-lint",
            )
        )
    if not any("class " in ln for ln in stripped_lines):
        diagnostics.append(
            VerificationDiagnostic(
                level=VerificationLevel.SYNTAX,
                check="java class declaration",
                severity="error",
                message="No Java class declaration found",
                code="CLASS_MISSING",
                tool="autoforge-java-struct-lint",
            )
        )
    status = VerificationStatus.FAIL if diagnostics else VerificationStatus.PASS
    return VerificationCheckResult(
        level=VerificationLevel.SYNTAX,
        check="java structural syntax",
        status=status,
        tool="autoforge-java-struct-lint",
        detail="ok" if not diagnostics else f"{len(diagnostics)} structural issue(s)",
        diagnostics=diagnostics,
    )


def _python_syntax_check(content: str) -> VerificationCheckResult:
    """Real Python syntax validation via the CPython parser (ast.parse)."""
    diagnostics: list[VerificationDiagnostic] = []
    try:
        ast.parse(content)
        status = VerificationStatus.PASS
    except SyntaxError as exc:
        status = VerificationStatus.FAIL
        diagnostics.append(
            VerificationDiagnostic(
                level=VerificationLevel.SYNTAX,
                check="python syntax",
                severity="error",
                message=f"{exc.msg} (line {exc.lineno}, col {exc.offset})",
                location=f"<generated>:{exc.lineno}",
                code="PY_SYNTAX_ERROR",
                tool="cpython-ast",
            )
        )
    return VerificationCheckResult(
        level=VerificationLevel.SYNTAX,
        check="python syntax",
        status=status,
        tool="cpython-ast",
        detail="ok" if status == VerificationStatus.PASS else "syntax error(s)",
        diagnostics=diagnostics,
    )


def _sql_structural_check(content: str) -> VerificationCheckResult:
    """Deterministic structural validation of generated SQL."""
    diagnostics: list[VerificationDiagnostic] = []
    depth = 0
    for lineno, line in enumerate(content.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("--") or s.startswith("/*"):
            continue
        depth += line.count("(") - line.count(")")
        if depth < 0:
            diagnostics.append(
                VerificationDiagnostic(
                    level=VerificationLevel.SYNTAX,
                    check="paren balance",
                    severity="error",
                    message="Unbalanced closing parenthesis",
                    location=f"<generated>:{lineno}",
                    code="SQL_PAREN_UNBALANCED",
                    tool="autoforge-sql-struct-lint",
                )
            )
            break
    if depth != 0:
        diagnostics.append(
            VerificationDiagnostic(
                level=VerificationLevel.SYNTAX,
                check="paren balance",
                severity="error",
                message=f"Unbalanced parentheses (depth={depth})",
                code="SQL_PAREN_UNBALANCED",
                tool="autoforge-sql-struct-lint",
            )
        )
    upper = content.upper()
    if not any(
        kw in upper
        for kw in ("CREATE", "SELECT", "INSERT", "UPDATE", "DELETE")
    ):
        diagnostics.append(
            VerificationDiagnostic(
                level=VerificationLevel.SYNTAX,
                check="sql statement",
                severity="error",
                message="No SQL statement recognized",
                code="SQL_STATEMENT_MISSING",
                tool="autoforge-sql-struct-lint",
            )
        )
    status = VerificationStatus.FAIL if diagnostics else VerificationStatus.PASS
    return VerificationCheckResult(
        level=VerificationLevel.SYNTAX,
        check="sql structural syntax",
        status=status,
        tool="autoforge-sql-struct-lint",
        detail="ok" if not diagnostics else f"{len(diagnostics)} structural issue(s)",
        diagnostics=diagnostics,
    )


def _js_syntax_check(content: str) -> VerificationCheckResult:
    """Real JavaScript syntax check via node --check when node is available."""
    node = shutil.which("node")
    if not node:
        return VerificationCheckResult(
            level=VerificationLevel.SYNTAX,
            check="js syntax",
            status=VerificationStatus.UNDEFINED,
            tool="node",
            detail="node runtime not available on this host",
        )
    path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as tmp:
            tmp.write(content)
            path = tmp.name
        proc = subprocess.run(
            [node, "--check", path], capture_output=True, text=True, timeout=30
        )
        if proc.returncode == 0:
            return VerificationCheckResult(
                level=VerificationLevel.SYNTAX,
                check="js syntax",
                status=VerificationStatus.PASS,
                tool="node",
                detail="ok",
            )
        return VerificationCheckResult(
            level=VerificationLevel.SYNTAX,
            check="js syntax",
            status=VerificationStatus.FAIL,
            tool="node",
            detail=(proc.stderr or proc.stdout).strip()[:500],
            diagnostics=[
                VerificationDiagnostic(
                    level=VerificationLevel.SYNTAX,
                    check="js syntax",
                    severity="error",
                    message=(proc.stderr or proc.stdout).strip()[:500],
                    code="JS_SYNTAX_ERROR",
                    tool="node",
                )
            ],
        )
    except Exception as exc:  # noqa: BLE001
        return VerificationCheckResult(
            level=VerificationLevel.SYNTAX,
            check="js syntax",
            status=VerificationStatus.UNDEFINED,
            tool="node",
            detail=f"node --check could not run: {exc}",
        )
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _javac_compile_check(content: str) -> VerificationCheckResult:
    """Attempt a real javac compile of generated Java when a JRE exists."""
    javac = shutil.which("javac")
    if not javac:
        return VerificationCheckResult(
            level=VerificationLevel.COMPILE,
            check="javac compile",
            status=VerificationStatus.UNDEFINED,
            tool="javac",
            detail="javac not found on PATH",
        )
    workdir = ""
    try:
        workdir = tempfile.mkdtemp(prefix="autoforge-javac-")
        src_path = os.path.join(workdir, "Generated.java")
        with open(src_path, "w") as fh:
            fh.write(content)
        proc = subprocess.run(
            [javac, "-d", workdir, src_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode == 0:
            return VerificationCheckResult(
                level=VerificationLevel.COMPILE,
                check="javac compile",
                status=VerificationStatus.PASS,
                tool="javac",
                detail="compiled successfully",
            )
        error_text = (proc.stderr or proc.stdout).strip()
        return VerificationCheckResult(
            level=VerificationLevel.COMPILE,
            check="javac compile",
            status=VerificationStatus.FAIL,
            tool="javac",
            detail=error_text[:800],
            diagnostics=[
                VerificationDiagnostic(
                    level=VerificationLevel.COMPILE,
                    check="javac compile",
                    severity="error",
                    message=error_text[:800],
                    code="JAVAC_COMPILE_ERROR",
                    tool="javac",
                )
            ],
        )
    except FileNotFoundError as exc:
        return VerificationCheckResult(
            level=VerificationLevel.COMPILE,
            check="javac compile",
            status=VerificationStatus.UNDEFINED,
            tool="javac",
            detail=f"javac cannot launch: {exc}",
        )
    except Exception as exc:  # noqa: BLE001
        return VerificationCheckResult(
            level=VerificationLevel.COMPILE,
            check="javac compile",
            status=VerificationStatus.UNDEFINED,
            tool="javac",
            detail=f"javac probe error: {exc}",
        )
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def _python_compile_check(content: str) -> VerificationCheckResult:
    """Real byte-compile of generated Python via compile() builtin."""
    try:
        compile(content, "<generated>", "exec")
        return VerificationCheckResult(
            level=VerificationLevel.COMPILE,
            check="python byte-compile",
            status=VerificationStatus.PASS,
            tool="cpython-compile",
            detail="compiled successfully",
        )
    except (SyntaxError, ValueError) as exc:
        return VerificationCheckResult(
            level=VerificationLevel.COMPILE,
            check="python byte-compile",
            status=VerificationStatus.FAIL,
            tool="cpython-compile",
            detail=str(exc),
            diagnostics=[
                VerificationDiagnostic(
                    level=VerificationLevel.COMPILE,
                    check="python byte-compile",
                    severity="error",
                    message=str(exc),
                    code="PY_COMPILE_ERROR",
                    tool="cpython-compile",
                )
            ],
        )


# ---------------------------------------------------------------------------
# Generated code verifier
# ---------------------------------------------------------------------------


class GeneratedCodeVerifier:
    """Runs the verification path for one generated artifact."""

    def __init__(
        self,
        *,
        run_compile_checks: bool = True,
        run_static_checks: bool = True,
    ) -> None:
        self.run_compile_checks = run_compile_checks
        self.run_static_checks = run_static_checks
        self._reports: list[VerificationReport] = []

    def reports(self) -> list[VerificationReport]:
        return list(self._reports)

    def verify(
        self,
        artifact_id: str,
        code: str,
        *,
        target_technology: str,
        provided_checks: list[VerificationCheckResult] | None = None,
    ) -> VerificationReport:
        """Verify a single generated artifact."""
        started = time.perf_counter()
        checks: list[VerificationCheckResult] = list(provided_checks or [])
        language = (target_technology or "").lower()

        if "java" in language:
            checks.append(_java_structural_check(code))
            if self.run_compile_checks:
                checks.append(_javac_compile_check(code))
        elif "python" in language:
            checks.append(_python_syntax_check(code))
            if self.run_compile_checks:
                checks.append(_python_compile_check(code))
        elif "sql" in language or "postgres" in language:
            checks.append(_sql_structural_check(code))
        elif "typescript" in language or "node" in language or "js" in language:
            checks.append(_js_syntax_check(code))
        else:
            checks.append(
                VerificationCheckResult(
                    level=VerificationLevel.SYNTAX,
                    check="target syntax",
                    status=VerificationStatus.NOT_APPLICABLE,
                    tool="",
                    detail=(
                        f"no deterministic syntax check for target "
                        f"'{target_technology}'"
                    ),
                )
            )

        if self.run_static_checks:
            placeholder_marks = [
                m
                for m in ("TODO", "FIXME", "PLACEHOLDER", "NotImplemented")
                if m in code
            ]
            if placeholder_marks:
                checks.append(
                    VerificationCheckResult(
                        level=VerificationLevel.STATIC,
                        check="placeholder scan",
                        status=VerificationStatus.UNDEFINED,
                        tool="autoforge-placeholder-scan",
                        detail=(
                            "placeholder markers present: "
                            + ", ".join(sorted(set(placeholder_marks)))
                        ),
                        diagnostics=[
                            VerificationDiagnostic(
                                level=VerificationLevel.STATIC,
                                check="placeholder scan",
                                severity="warning",
                                message=f"placeholder marker '{m}' found",
                                code="PLACEHOLDER_MARK",
                                tool="autoforge-placeholder-scan",
                            )
                            for m in sorted(set(placeholder_marks))
                        ],
                    )
                )
            else:
                checks.append(
                    VerificationCheckResult(
                        level=VerificationLevel.STATIC,
                        check="placeholder scan",
                        status=VerificationStatus.PASS,
                        tool="autoforge-placeholder-scan",
                        detail="no placeholder markers found",
                    )
                )

        diagnostics = [d for c in checks for d in c.diagnostics]
        failed_checks = [
            c for c in checks if c.status == VerificationStatus.FAIL
        ]
        if failed_checks:
            status = VerificationStatus.FAIL
        elif checks and all(
            c.status in (VerificationStatus.PASS, VerificationStatus.NOT_APPLICABLE)
            for c in checks
        ):
            status = VerificationStatus.PASS
        else:
            status = VerificationStatus.UNDEFINED

        report = VerificationReport(
            artifact_id=artifact_id,
            target_technology=target_technology,
            status=status,
            checks=checks,
            diagnostics=diagnostics,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self._reports.append(report)
        return report


__all__ = [
    "VerificationLevel",
    "VerificationStatus",
    "VerificationDiagnostic",
    "VerificationCheckResult",
    "VerificationReport",
    "GeneratedCodeVerifier",
]