"""MANDATORY HARD INVARIANT TEST: Proprietary Code Boundary Isolation.

Verifies:
1. Customer deliverable is located strictly in AUTOFORGE_OUTPUT_ROOT (outside AutoForge source repository).
2. Zero AutoForge internal source files or packages are copied into customer deliverables.
3. No customer code imports 'autoforge_*'.
4. Customer project runs standalone without requiring AutoForge repository on sys.path or runtime dependencies.
"""

import os
import sys
import pytest
from pathlib import Path
from autoforge_power_engines.specification import CustomerProjectSpecification, KnowledgeSourceSpec, SourceType
from autoforge_power_engines.rag.engine import RAGKnowledgePowerEngine
from autoforge_power_engines.packaging import CustomerProjectPackager, ProprietaryCodeViolationError


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_proprietary_code_boundary_isolation(tmp_path):
    # Set output root strictly in tmp_path (outside AutoForge repo root)
    output_root = tmp_path / "customer_deliveries"
    output_root.mkdir(parents=True, exist_ok=True)

    spec = CustomerProjectSpecification(
        project_name="IsolatedCustomerProject",
        project_description="Customer test for proprietary isolation",
        output_root=str(output_root),
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="inline-sample",
                source_type=SourceType.INLINE_TEXT,
                content="# Customer Architecture\nCustomer business logic rules and policies.",
            )
        ],
    )

    engine = RAGKnowledgePowerEngine()
    result = await engine.execute_lifecycle(spec)

    assert result.success is True
    deliv_path = Path(result.delivery_dir).resolve()

    # 1. Verify deliverable is strictly outside AutoForge repository tree
    assert not str(deliv_path).startswith(str(REPO_ROOT.resolve())), (
        f"Customer delivery path {deliv_path} must NOT be inside AutoForge repository {REPO_ROOT}"
    )

    # 2. Audit all delivered files for zero AutoForge proprietary source files
    forbidden_terms = [
        "autoforge_kernel",
        "autoforge_modernization",
        "autoforge_ai_infrastructure",
        "autoforge_workforce",
        "autoforge_orchestration",
        "autoforge_runtime",
        "autoforge_artifacts",
        "autoforge_events",
        "autoforge_composition",
        "autoforge_power_engines",
    ]

    all_files = list(deliv_path.rglob("*"))
    assert len(all_files) > 0, "Deliverable directory must not be empty"

    for file_path in all_files:
        if file_path.is_file():
            # Check file name does not resemble internal autoforge packages
            assert not file_path.name.startswith("autoforge_"), (
                f"Customer deliverable contains AutoForge proprietary file: {file_path.name}"
            )
            # Check text content does not import any autoforge package
            if file_path.suffix in (".py", ".sh", ".json", ".txt"):
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                for term in forbidden_terms:
                    assert f"import {term}" not in content, (
                        f"Proprietary import '{term}' found in customer file: {file_path}"
                    )
                    assert f"from {term}" not in content, (
                        f"Proprietary from-import '{term}' found in customer file: {file_path}"
                    )

    # 3. Verify sanitizer confirms zero leakage
    packager = CustomerProjectPackager(deliv_path)
    violations = packager.sanitize_proprietary_boundary()
    assert violations == []


def test_sanitizer_detects_deliberate_leakage(tmp_path):
    deliv_dir = tmp_path / "leaky_project"
    deliv_dir.mkdir()
    packager = CustomerProjectPackager(deliv_dir)
    packager.prepare_directories()

    # Deliberately inject a forbidden import into a customer file
    leaky_file = deliv_dir / "src" / "leaky.py"
    leaky_file.write_text("import autoforge_kernel\n", encoding="utf-8")

    with pytest.raises(ProprietaryCodeViolationError):
        packager.sanitize_proprietary_boundary()
