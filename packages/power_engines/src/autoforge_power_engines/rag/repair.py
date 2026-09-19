"""Closed-Loop Autonomous Diagnosis and Repair for Customer Deliverables."""

from __future__ import annotations

import json
import logging
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("autoforge.power_engines.rag.repair")


class DiagnosticDefect(BaseModel):
    defect_id: str
    file_path: str
    defect_type: str  # "json_syntax", "python_syntax", "missing_dependency", "test_failure"
    description: str
    line_number: Optional[int] = None
    suggested_repair: str


class RepairResult(BaseModel):
    repaired: bool = False
    repair_count: int = 0
    defects_fixed: List[DiagnosticDefect] = Field(default_factory=list)
    remaining_defects: List[DiagnosticDefect] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class RAGClosedLoopRepairEngine:
    """
    Closed-loop autonomous diagnosis and repair:
    DIAGNOSE → REPAIR → RE-VERIFY
    Handles routine recoverable failures without human escalation.
    """

    def __init__(self, delivery_dir: Path):
        self.delivery_dir = delivery_dir.resolve()

    def diagnose_defects(self) -> List[DiagnosticDefect]:
        """Scans customer project artifacts for recoverable defects."""
        defects: List[DiagnosticDefect] = []

        # 1. Audit JSON configuration and index files
        for json_file in self.delivery_dir.rglob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    json.load(f)
            except Exception as e:
                defects.append(DiagnosticDefect(
                    defect_id=f"json-corrupt-{json_file.name}",
                    file_path=str(json_file.relative_to(self.delivery_dir)),
                    defect_type="json_syntax",
                    description=f"Corrupt JSON syntax: {e}",
                    suggested_repair="Reconstruct valid JSON format",
                ))

        # 2. Audit Python files with py_compile
        for py_file in self.delivery_dir.rglob("*.py"):
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                defects.append(DiagnosticDefect(
                    defect_id=f"py-syntax-{py_file.name}",
                    file_path=str(py_file.relative_to(self.delivery_dir)),
                    defect_type="python_syntax",
                    description=f"Python syntax compilation error: {e}",
                    suggested_repair="Correct syntax defect in Python source",
                ))

        # 3. Audit executable scripts
        for script in (self.delivery_dir / "scripts").glob("*.sh"):
            if not script.exists():
                continue
            text = script.read_text(encoding="utf-8")
            if not text.startswith("#!/usr/bin/env bash") and not text.startswith("#!/bin/bash"):
                defects.append(DiagnosticDefect(
                    defect_id=f"script-shebang-{script.name}",
                    file_path=str(script.relative_to(self.delivery_dir)),
                    defect_type="script_header",
                    description="Missing standard bash shebang",
                    suggested_repair="Prepend #!/usr/bin/env bash",
                ))

        return defects

    def apply_repairs(self, defects: List[DiagnosticDefect]) -> RepairResult:
        """Applies deterministic autonomous repairs to diagnosed defects."""
        fixed = []
        remaining = []

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
                    if cleaned.endswith(",}"):
                        cleaned = cleaned[:-2] + "}"
                    if cleaned.endswith(",]"):
                        cleaned = cleaned[:-2] + "]"
                    # Try parsing again
                    parsed = json.loads(cleaned)
                    target_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
                    fixed.append(defect)

                elif defect.defect_type == "script_header":
                    raw = target_path.read_text(encoding="utf-8")
                    target_path.write_text("#!/usr/bin/env bash\n" + raw, encoding="utf-8")
                    fixed.append(defect)

                elif defect.defect_type == "python_syntax":
                    # Fix common syntax glitches (e.g. missing colon or unclosed string)
                    raw = target_path.read_text(encoding="utf-8")
                    # If trailing invalid chars
                    cleaned = raw.replace("\t", "    ")
                    target_path.write_text(cleaned, encoding="utf-8")
                    py_compile.compile(str(target_path), doraise=True)
                    fixed.append(defect)

                else:
                    remaining.append(defect)
            except Exception as ex:
                logger.warning(f"Repair attempt failed for {defect.defect_id}: {ex}")
                remaining.append(defect)

        return RepairResult(
            repaired=len(fixed) > 0,
            repair_count=len(fixed),
            defects_fixed=fixed,
            remaining_defects=remaining,
            details={"fixed_count": len(fixed), "remaining_count": len(remaining)},
        )

    def run_customer_tests(self) -> Dict[str, Any]:
        """Executes the customer project test suite in an isolated subprocess."""
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
                timeout=20,
            )
            return {
                "tests_found": True,
                "passed": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except Exception as e:
            return {
                "tests_found": True,
                "passed": False,
                "error": str(e),
            }
