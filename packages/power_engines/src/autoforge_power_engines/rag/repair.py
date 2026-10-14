"""Closed-Loop Autonomous Diagnosis and Repair for Customer Deliverables."""

from __future__ import annotations

import ast
import json
import logging
import py_compile
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

logger = logging.getLogger("autoforge.power_engines.rag.repair")


class DiagnosticDefect(BaseModel):
    defect_id: str
    file_path: str
    defect_type: str  # "unterminated_string_literal", "python_syntax", "indentation_error", "json_syntax", "script_header", "test_failure"
    description: str
    line_number: Optional[int] = None
    offset: Optional[int] = None
    error_signature: Optional[str] = None
    suggested_repair: str
    attempt_count: int = 0


class RepairResult(BaseModel):
    repaired: bool = False
    repair_count: int = 0
    defects_fixed: List[DiagnosticDefect] = Field(default_factory=list)
    remaining_defects: List[DiagnosticDefect] = Field(default_factory=list)
    budget_exhausted: bool = False
    ineffective_repairs_detected: bool = False
    attempts_history: List[Dict[str, Any]] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class RAGClosedLoopRepairEngine:
    """
    Closed-loop autonomous diagnosis and targeted evidence-driven remediation:
    DIAGNOSE → CLASSIFY → REPAIR → RE-VERIFY → SIGNATURE CHECK
    Detects repeated ineffective repairs and respects remediation budgets.
    """

    def __init__(self, delivery_dir: Path | str, max_budget: int = 3):
        self.delivery_dir = Path(delivery_dir).resolve()
        self.max_budget = max_budget
        self._history_signatures: List[str] = []
        self._attempts_count: int = 0

    def diagnose_defects(self) -> List[DiagnosticDefect]:
        """Scans customer project artifacts for recoverable defects with precise AST/compiler diagnostics."""
        defects: List[DiagnosticDefect] = []

        # 1. Audit JSON configuration and index files
        for json_file in self.delivery_dir.rglob("*.json"):
            if not json_file.is_file():
                continue
            rel_path = str(json_file.relative_to(self.delivery_dir))
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    json.load(f)
            except json.JSONDecodeError as jde:
                sig = f"{rel_path}:json_syntax:{jde.lineno}:{jde.msg}"
                defects.append(DiagnosticDefect(
                    defect_id=f"json-corrupt-{json_file.name}",
                    file_path=rel_path,
                    defect_type="json_syntax",
                    description=f"Corrupt JSON syntax: {jde.msg} (line {jde.lineno}, col {jde.colno})",
                    line_number=jde.lineno,
                    offset=jde.colno,
                    error_signature=sig,
                    suggested_repair="Reconstruct valid JSON format and purge invalid trailing commas or delimiters",
                ))
            except Exception as e:
                sig = f"{rel_path}:json_syntax:0:{e}"
                defects.append(DiagnosticDefect(
                    defect_id=f"json-corrupt-{json_file.name}",
                    file_path=rel_path,
                    defect_type="json_syntax",
                    description=f"JSON parsing error: {e}",
                    error_signature=sig,
                    suggested_repair="Reconstruct valid JSON format",
                ))

        # 2. Audit Python files with ast.parse and py_compile
        for py_file in self.delivery_dir.rglob("*.py"):
            if not py_file.is_file():
                continue
            rel_path = str(py_file.relative_to(self.delivery_dir))
            content = ""
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception as read_err:
                defects.append(DiagnosticDefect(
                    defect_id=f"py-encoding-{py_file.name}",
                    file_path=rel_path,
                    defect_type="python_syntax",
                    description=f"Encoding read error: {read_err}",
                    suggested_repair="Normalize file encoding to UTF-8",
                ))
                continue

            try:
                ast.parse(content, filename=str(py_file))
                py_compile.compile(str(py_file), doraise=True)
            except (SyntaxError, IndentationError, py_compile.PyCompileError) as syn_err:
                msg = getattr(syn_err, "msg", str(syn_err))
                lineno = getattr(syn_err, "lineno", None)
                offset = getattr(syn_err, "offset", None)

                # Classify defect type
                if isinstance(syn_err, IndentationError) or "unindent does not match" in str(msg).lower():
                    d_type = "indentation_error"
                    repair_hint = "Normalize indentation to consistent 4 spaces"
                elif "unterminated string literal" in str(msg).lower() or "eol while scanning string literal" in str(msg).lower():
                    d_type = "unterminated_string_literal"
                    repair_hint = "Enclose unclosed multi-line literal with triple-quotes or escape newlines"
                else:
                    d_type = "python_syntax"
                    repair_hint = "Correct Python syntax defect"

                sig = f"{rel_path}:{d_type}:{lineno}:{msg}"
                defects.append(DiagnosticDefect(
                    defect_id=f"py-syntax-{py_file.name}",
                    file_path=rel_path,
                    defect_type=d_type,
                    description=f"Python syntax compilation error: {msg}",
                    line_number=lineno,
                    offset=offset,
                    error_signature=sig,
                    suggested_repair=repair_hint,
                ))

        # 3. Audit executable scripts
        scripts_dir = self.delivery_dir / "scripts"
        if scripts_dir.exists():
            for script in scripts_dir.glob("*.sh"):
                if not script.is_file():
                    continue
                text = script.read_text(encoding="utf-8")
                if not text.startswith("#!/usr/bin/env bash") and not text.startswith("#!/bin/bash"):
                    rel_path = str(script.relative_to(self.delivery_dir))
                    defects.append(DiagnosticDefect(
                        defect_id=f"script-shebang-{script.name}",
                        file_path=rel_path,
                        defect_type="script_header",
                        description="Missing standard bash shebang",
                        error_signature=f"{rel_path}:script_header:1:missing_shebang",
                        suggested_repair="Prepend #!/usr/bin/env bash",
                    ))

        return defects

    def apply_repairs(self, defects: List[DiagnosticDefect]) -> RepairResult:
        """Applies deterministic, diagnosis-linked repairs with ineffective attempt detection."""
        self._attempts_count += 1
        history_record: Dict[str, Any] = {
            "attempt": self._attempts_count,
            "defects_in": [d.error_signature for d in defects if d.error_signature],
        }

        # Check remediation budget
        if self._attempts_count > self.max_budget:
            logger.warning(f"Remediation budget exhausted ({self._attempts_count} > {self.max_budget})")
            return RepairResult(
                repaired=False,
                repair_count=0,
                defects_fixed=[],
                remaining_defects=defects,
                budget_exhausted=True,
                ineffective_repairs_detected=False,
                attempts_history=[{"error": "Budget exhausted"}],
                details={"status": "BUDGET_EXHAUSTED", "attempts": self._attempts_count},
            )

        # Detect consecutive identical failure signatures
        current_signatures = sorted([d.error_signature for d in defects if d.error_signature])
        sig_key = "|".join(current_signatures)
        ineffective_detected = False

        if current_signatures and len(self._history_signatures) > 0:
            if self._history_signatures[-1] == sig_key:
                ineffective_detected = True
                logger.warning(f"Consecutive identical failure signature detected: {sig_key}. Ineffective repair halted.")

        self._history_signatures.append(sig_key)

        if ineffective_detected:
            return RepairResult(
                repaired=False,
                repair_count=0,
                defects_fixed=[],
                remaining_defects=defects,
                budget_exhausted=False,
                ineffective_repairs_detected=True,
                attempts_history=[{"error": "Consecutive identical failure signature detected"}],
                details={"status": "INEFFECTIVE_REPAIR_HALTED", "signature": sig_key},
            )

        fixed: List[DiagnosticDefect] = []
        remaining: List[DiagnosticDefect] = []

        for defect in defects:
            target_path = self.delivery_dir / defect.file_path
            if not target_path.exists():
                remaining.append(defect)
                continue

            try:
                if defect.defect_type == "json_syntax":
                    # Attempt to recover JSON
                    raw = target_path.read_text(encoding="utf-8")
                    cleaned = raw.strip()
                    # Remove trailing commas
                    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
                    parsed = json.loads(cleaned)
                    target_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
                    fixed.append(defect)

                elif defect.defect_type == "script_header":
                    raw = target_path.read_text(encoding="utf-8")
                    target_path.write_text("#!/usr/bin/env bash\n" + raw, encoding="utf-8")
                    fixed.append(defect)

                elif defect.defect_type == "unterminated_string_literal":
                    # Targeted repair for unterminated string literal:
                    # Look at target file lines around line_number
                    raw = target_path.read_text(encoding="utf-8")
                    lines = raw.splitlines(keepends=True)
                    line_idx = (defect.line_number - 1) if defect.line_number and defect.line_number <= len(lines) else 0

                    repaired = False
                    # Pattern 1: unclosed multiline assignment like: description="line1\nline2"
                    target_line = lines[line_idx]
                    if 'description="' in target_line or "description='" in target_line or '="' in target_line:
                        # Convert to triple-quoted string
                        lines[line_idx] = re.sub(r'description="([^"]*)', r'description="""\1', target_line)
                        # Check where the string closes or close it
                        for next_idx in range(line_idx + 1, min(len(lines), line_idx + 30)):
                            if '",' in lines[next_idx] or '")' in lines[next_idx]:
                                lines[next_idx] = lines[next_idx].replace('",', '""",').replace('")', '""")')
                                repaired = True
                                break
                            elif '",\n' in lines[next_idx]:
                                lines[next_idx] = lines[next_idx].replace('",', '""",')
                                repaired = True
                                break

                    if not repaired:
                        # Fallback: if there are unescaped newlines inside strings, replace literal newlines with \\n
                        # or standardize quotes
                        fixed_content = raw.replace("\r\n", "\n")
                        target_path.write_text(fixed_content, encoding="utf-8")
                    else:
                        target_path.write_text("".join(lines), encoding="utf-8")

                    # Verify immediately with compile
                    ast.parse(target_path.read_text(encoding="utf-8"))
                    py_compile.compile(str(target_path), doraise=True)
                    fixed.append(defect)

                elif defect.defect_type in ("python_syntax", "indentation_error"):
                    raw = target_path.read_text(encoding="utf-8")
                    # Standardize tabs to spaces
                    cleaned = raw.replace("\t", "    ")
                    target_path.write_text(cleaned, encoding="utf-8")
                    ast.parse(cleaned)
                    py_compile.compile(str(target_path), doraise=True)
                    fixed.append(defect)

                else:
                    remaining.append(defect)

            except Exception as ex:
                logger.warning(f"Repair attempt failed for {defect.defect_id}: {ex}")
                remaining.append(defect)

        # Immediate post-repair re-verification
        post_defects = self.diagnose_defects()
        repaired_clean = (len(post_defects) == 0) and (len(fixed) > 0)

        return RepairResult(
            repaired=repaired_clean,
            repair_count=len(fixed),
            defects_fixed=fixed,
            remaining_defects=post_defects if post_defects else remaining,
            budget_exhausted=False,
            ineffective_repairs_detected=False,
            attempts_history=[history_record],
            details={
                "fixed_count": len(fixed),
                "remaining_count": len(post_defects),
                "attempts": self._attempts_count,
            },
        )

    def run_customer_tests(self) -> Dict[str, Any]:
        """Executes the customer project test suite in an isolated subprocess using sys.executable."""
        test_dir = self.delivery_dir / "tests"
        if not test_dir.exists():
            return {"tests_found": False, "passed": True, "count": 0}

        cmd = [sys.executable, "-m", "unittest", "discover", "-s", str(test_dir), "-p", "test_*.py"]
        try:
            res = subprocess.run(
                cmd,
                cwd=str(self.delivery_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            passed = (res.returncode == 0)
            return {
                "tests_found": True,
                "passed": passed,
                "returncode": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except Exception as e:
            return {
                "tests_found": True,
                "passed": False,
                "error": str(e),
            }
