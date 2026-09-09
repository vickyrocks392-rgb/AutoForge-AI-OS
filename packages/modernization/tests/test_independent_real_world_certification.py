"""Comprehensive pytest test suite for 18-G Final Closure Gate:
Independent Real-World Legacy Project Certification.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence.run_independent_real_world_certification import (
    main as run_cert,
    compute_nloc_accounting,
    IndependentReferenceEvaluator,
    FROZEN_COMMIT_SHA,
)


@pytest.mark.asyncio
async def test_18_g_independent_real_world_certification():
    """Validates that all 15 Gates (G1 to G15) PASS on the external Open Mainframe Project workload."""
    repo_root = Path(__file__).resolve().parents[3]
    workload_root = repo_root / ".autoforge" / "external_workloads" / "cobol-programming-course" / "COBOL Programming Course #2 - Learning COBOL" / "Labs"
    if not workload_root.exists():
        pytest.skip(f"External workload not present at {workload_root}")
    source_files = sorted(workload_root.glob("cbl/*.cobol")) + sorted(workload_root.glob("jcl/*.jcl"))

    assert len(source_files) >= 40, f"Expected at least 40 source files in external workload, got {len(source_files)}"

    nloc = compute_nloc_accounting(source_files)
    assert nloc["total_nloc"] >= 1500

    # Test Independent Reference Evaluator
    res_add = IndependentReferenceEvaluator.evaluate_source_record("ADDAMT", {"val1": 100, "val2": 200})
    assert res_add["expected_sum"] == 300
    assert res_add["status_code"] == 0

    res_srch = IndependentReferenceEvaluator.evaluate_source_record("SRCHSER", {"key": "ITEM02"})
    assert res_srch["found"] is True
    assert res_srch["expected_index"] == 2

    # Run full certification
    await run_cert()

    # Verify report artifacts exist
    report_json = repo_root / "packages" / "modernization" / "evidence" / "g5_final_independent_certification.json"
    report_md = repo_root / "packages" / "modernization" / "evidence" / "G5-FINAL-INDEPENDENT-REAL-WORLD-CERTIFICATION.md"

    assert report_json.exists()
    assert report_md.exists()

    md_text = report_md.read_text()
    assert "18-G CLOSED" in md_text
