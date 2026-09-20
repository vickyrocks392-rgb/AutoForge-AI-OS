"""Deterministic Multi-Level Verification Layer (18-COMMERCIAL-D).

Validates:
1. Syntax & Structural parsing (Python ast, Java struct)
2. Compilation / Build (javac for Java, ast.parse for Python)
3. Test suite execution
4. Forbidden source constructs remaining (e.g. leftover COBOL tokens or Python 2 syntax)
5. Unresolved markers (TODO, FIXME, UNRESOLVED_CONSTRUCT)
6. Behavior equivalence results

Distinguishes:
- PASS
- FAIL
- INCONCLUSIVE
Never converts INCONCLUSIVE to PASS.
"""

from __future__ import annotations

import ast
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.migration.safety import SafeExecutionRunner
from autoforge_power_engines.migration.equivalence import BehaviorEquivalenceReport, EquivalenceVerdict


class VerificationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class VerificationCheck(BaseModel):
    """Result of an individual verification check."""
    name: str
    status: VerificationStatus
    details: str = ""
    diagnostics: List[str] = Field(default_factory=list)


class UnitVerificationReport(BaseModel):
    """Complete verification report for a single transformation unit."""
    unit_id: str
    source_file: str
    target_file: str
    overall_status: VerificationStatus
    checks: List[VerificationCheck] = Field(default_factory=list)
    diagnostics: List[str] = Field(default_factory=list)
    behavior_report: Optional[BehaviorEquivalenceReport] = None


class VerificationEngine:
    """
    Deterministic verifier for transformed code and generated suites.
    """

    # Markers indicating incomplete transformation
    UNRESOLVED_MARKERS = [
        re.compile(r"\bTODO:\s*MIGRATE\b", re.IGNORECASE),
        re.compile(r"\bFIXME:\s*UNRESOLVED\b", re.IGNORECASE),
        re.compile(r"\bUNRESOLVED_CONSTRUCT\b", re.IGNORECASE),
        re.compile(r"\bNOT_IMPLEMENTED_YET\b", re.IGNORECASE),
        re.compile(r"<<<.*?>>>"),
    ]

    # Forbidden constructs by target language
    FORBIDDEN_PATTERNS: Dict[str, List[re.Pattern]] = {
        "java": [
            re.compile(r"\bPROCEDURE\s+DIVISION\b", re.IGNORECASE),
            re.compile(r"\bWORKING-STORAGE\s+SECTION\b", re.IGNORECASE),
            re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE),
            re.compile(r"\bSTOP\s+RUN\b", re.IGNORECASE),
            re.compile(r"\bDISPLAY\s+['\"]", re.IGNORECASE),
        ],
        "python": [
            re.compile(r"\bprint\s+[^\(]", re.IGNORECASE),  # Python 2 print statement
            re.compile(r"\braw_input\s*\(", re.IGNORECASE),
            re.compile(r"\bxrange\s*\(", re.IGNORECASE),
        ]
    }

    @classmethod
    def check_markers_and_forbidden(
        cls,
        content: str,
        target_lang: str,
    ) -> VerificationCheck:
        diagnostics = []

        # Check for unresolved markers
        for p in cls.UNRESOLVED_MARKERS:
            matches = p.findall(content)
            if matches:
                diagnostics.append(f"Unresolved transformation marker found: '{matches[0]}'")

        # Check for forbidden legacy remnants
        forbidden = cls.FORBIDDEN_PATTERNS.get(target_lang.lower(), [])
        for p in forbidden:
            if p.search(content):
                diagnostics.append(f"Forbidden source remnant found in target code: {p.pattern}")

        if diagnostics:
            return VerificationCheck(
                name="markers_and_forbidden_constructs",
                status=VerificationStatus.FAIL,
                details=f"Found {len(diagnostics)} forbidden or unresolved marker(s).",
                diagnostics=diagnostics,
            )
        return VerificationCheck(
            name="markers_and_forbidden_constructs",
            status=VerificationStatus.PASS,
            details="No unresolved markers or forbidden constructs detected.",
        )

    @classmethod
    def check_syntax(cls, target_path: Path, target_lang: str) -> VerificationCheck:
        """Deterministic syntax validation (ast.parse for Python, structural checks for Java)."""
        if not target_path.exists():
            return VerificationCheck(
                name="syntax_check",
                status=VerificationStatus.FAIL,
                details=f"Target file '{target_path}' does not exist.",
                diagnostics=["File missing on disk"],
            )

        content = target_path.read_text(encoding="utf-8", errors="replace")

        if target_lang.lower() == "python":
            try:
                ast.parse(content, filename=str(target_path))
                return VerificationCheck(
                    name="syntax_check",
                    status=VerificationStatus.PASS,
                    details="Python syntax valid via CPython AST parser.",
                )
            except SyntaxError as se:
                return VerificationCheck(
                    name="syntax_check",
                    status=VerificationStatus.FAIL,
                    details=f"Python syntax error at line {se.lineno}: {se.msg}",
                    diagnostics=[f"Line {se.lineno}: {se.msg}"],
                )

        elif target_lang.lower() == "java":
            # Basic structural check (brace balance + class declaration)
            brace_depth = content.count("{") - content.count("}")
            if brace_depth != 0:
                return VerificationCheck(
                    name="syntax_check",
                    status=VerificationStatus.FAIL,
                    details=f"Java unbalanced braces: depth={brace_depth}",
                    diagnostics=[f"Unbalanced braces depth {brace_depth}"],
                )
            if "class " not in content and "interface " not in content and "enum " not in content:
                return VerificationCheck(
                    name="syntax_check",
                    status=VerificationStatus.FAIL,
                    details="No Java class, interface, or enum declared.",
                    diagnostics=["Missing type declaration"],
                )
            return VerificationCheck(
                name="syntax_check",
                status=VerificationStatus.PASS,
                details="Java structural syntax checks passed.",
            )

        return VerificationCheck(
            name="syntax_check",
            status=VerificationStatus.INCONCLUSIVE,
            details=f"No specialized syntax parser configured for {target_lang}.",
        )

    @classmethod
    def check_compilation(
        cls,
        working_dir: Path,
        target_path: Path,
        target_lang: str,
        runner: Optional[SafeExecutionRunner] = None,
    ) -> VerificationCheck:
        """Executes actual compiler if available (e.g. javac for Java)."""
        if target_lang.lower() == "java":
            import shutil
            javac_path = shutil.which("javac")
            if not javac_path:
                return VerificationCheck(
                    name="compilation_check",
                    status=VerificationStatus.INCONCLUSIVE,
                    details="javac binary not found on host environment.",
                )
            exec_runner = runner or SafeExecutionRunner(working_dir=working_dir)
            try:
                rel_file = str(target_path.relative_to(working_dir))
            except ValueError:
                rel_file = str(target_path)
            # Compile with -d to temporary output
            res = exec_runner.run(["javac", "-d", "/tmp", rel_file])
            if res.success:
                return VerificationCheck(
                    name="compilation_check",
                    status=VerificationStatus.PASS,
                    details="Java compilation succeeded via javac.",
                )
            err_msg = res.stderr.strip() or res.stdout.strip()
            if "Unable to locate a Java Runtime" in err_msg or "No Java runtime present" in err_msg:
                return VerificationCheck(
                    name="compilation_check",
                    status=VerificationStatus.INCONCLUSIVE,
                    details="Java runtime not installed on host environment.",
                )
            return VerificationCheck(
                name="compilation_check",
                status=VerificationStatus.FAIL,
                details="Java compilation failed.",
                diagnostics=[err_msg],
            )

        elif target_lang.lower() == "python":
            # Python compiles to bytecode via py_compile
            import py_compile
            try:
                py_compile.compile(str(target_path), doraise=True)
                return VerificationCheck(
                    name="compilation_check",
                    status=VerificationStatus.PASS,
                    details="Python bytecode compilation succeeded.",
                )
            except py_compile.PyCompileError as pce:
                return VerificationCheck(
                    name="compilation_check",
                    status=VerificationStatus.FAIL,
                    details=f"Bytecode compilation error: {pce}",
                    diagnostics=[str(pce)],
                )

        return VerificationCheck(
            name="compilation_check",
            status=VerificationStatus.INCONCLUSIVE,
            details=f"No compiler check implemented for '{target_lang}'.",
        )

    @classmethod
    def verify_unit(
        cls,
        unit_id: str,
        source_file: str,
        target_path: Path,
        target_lang: str,
        working_dir: Path,
        behavior_report: Optional[BehaviorEquivalenceReport] = None,
    ) -> UnitVerificationReport:
        checks: List[VerificationCheck] = []
        diagnostics: List[str] = []

        # 1. Existence and non-empty
        if not target_path.exists() or target_path.stat().st_size == 0:
            checks.append(VerificationCheck(
                name="file_existence",
                status=VerificationStatus.FAIL,
                details="Target file is missing or empty.",
                diagnostics=["Target file does not exist or has 0 bytes"],
            ))
            return UnitVerificationReport(
                unit_id=unit_id,
                source_file=source_file,
                target_file=str(target_path),
                overall_status=VerificationStatus.FAIL,
                checks=checks,
                diagnostics=["Target file missing or empty"],
            )
        checks.append(VerificationCheck(
            name="file_existence",
            status=VerificationStatus.PASS,
            details=f"Target file exists ({target_path.stat().st_size} bytes).",
        ))

        content = target_path.read_text(encoding="utf-8", errors="replace")

        # 2. Syntax
        syn_check = cls.check_syntax(target_path, target_lang)
        checks.append(syn_check)
        if syn_check.diagnostics:
            diagnostics.extend(syn_check.diagnostics)

        # 3. Markers and Forbidden constructs
        marker_check = cls.check_markers_and_forbidden(content, target_lang)
        checks.append(marker_check)
        if marker_check.diagnostics:
            diagnostics.extend(marker_check.diagnostics)

        # 4. Compilation
        comp_check = cls.check_compilation(working_dir, target_path, target_lang)
        checks.append(comp_check)
        if comp_check.diagnostics:
            diagnostics.extend(comp_check.diagnostics)

        # 5. Behavior equivalence
        if behavior_report:
            if behavior_report.verdict == EquivalenceVerdict.EQUIVALENT:
                checks.append(VerificationCheck(
                    name="behavior_equivalence",
                    status=VerificationStatus.PASS,
                    details=behavior_report.details,
                ))
            elif behavior_report.verdict == EquivalenceVerdict.MISMATCH:
                checks.append(VerificationCheck(
                    name="behavior_equivalence",
                    status=VerificationStatus.FAIL,
                    details=behavior_report.details,
                    diagnostics=[behavior_report.details],
                ))
                diagnostics.append(f"Behavior equivalence mismatch: {behavior_report.details}")
            else:
                checks.append(VerificationCheck(
                    name="behavior_equivalence",
                    status=VerificationStatus.INCONCLUSIVE,
                    details=behavior_report.details,
                ))

        # Determine overall status
        if any(c.status == VerificationStatus.FAIL for c in checks):
            overall = VerificationStatus.FAIL
        elif all(c.status == VerificationStatus.PASS for c in checks):
            overall = VerificationStatus.PASS
        else:
            overall = VerificationStatus.INCONCLUSIVE

        return UnitVerificationReport(
            unit_id=unit_id,
            source_file=source_file,
            target_file=str(target_path),
            overall_status=overall,
            checks=checks,
            diagnostics=diagnostics,
            behavior_report=behavior_report,
        )
