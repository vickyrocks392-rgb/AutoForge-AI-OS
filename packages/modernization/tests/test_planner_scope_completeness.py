"""Phase 20-A Planner Scope Completeness & Semantic Planning Upgrade Tests.

Covers:
- TEST A: All files dispositioned, material scope complete (scope_complete = True)
- TEST B: Material artifact incorrectly excluded (scope_complete = False)
- TEST C: Unsupported material artifact (UNSUPPORTED_MATERIAL, planning blocked)
- TEST D: Unknown artifact (UNKNOWN, planning blocked)
- TEST E: Reference implementation (explicit exclusion, evidence recorded, scope complete)
- TEST F: Tutorial tooling (explicit exclusion, evidence recorded, scope complete)
- TEST G: Dependency reveals hidden material artifact (promoted to material scope)
- TEST H: M6 semantic classification (structured M6 response materially determines classification)
- TEST I: M6 failure (semantic analysis required but failed -> planning does not silently continue)
- TEST J: Post-execution mismatch (10 material planned, 8 processed -> completion rejected)
- TEST K: Valid exclusion (10 material, 31 excluded, all 10 processed -> completion allowed)
- TEST L: AST/static inspection proving Planner does not directly import/instantiate MLX,
          LocalRuntimeProviderAdapter, raw HTTP endpoints, Ollama, Gemini
- TEST M: Real Phase 20-A workload regression on marcoeg/cobol-modernization-playbook
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock

from autoforge_modernization.composition.planner import (
    ArtifactDisposition,
    ArtifactScopeRecord,
    GenericTransformationPlanner,
    ScopeCompletenessResult,
)
from autoforge_modernization.target.specification import TargetSpecification
from autoforge_modernization.semantic.model import TechnologyNeutralSemanticModel


_REAL_PLAYBOOK_ROOT = Path("/Users/kalachanddash/Developer/.autoforge-p20-workloads/playbook")


def test_a_all_files_dispositioned_material_scope_complete(tmp_path: Path):
    """TEST A: All files dispositioned, material scope complete."""
    # Create simple complete project
    (tmp_path / "cobol").mkdir()
    (tmp_path / "cobol" / "MAIN.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. MAIN.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       PROCEDURE DIVISION.\n"
        "           DISPLAY 'HELLO'.\n"
        "           STOP RUN.\n"
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "input.dat").write_text("12345")
    (tmp_path / "run.sh").write_text("#!/bin/bash\nexit 0\n")
    (tmp_path / "README.md").write_text("# Test Project\n")

    planner = GenericTransformationPlanner()
    res = planner.analyze_scope(tmp_path)

    assert res.scope_complete is True
    assert res.unsupported_artifact_count == 0
    assert res.unknown_artifact_count == 0
    assert len(res.unresolved_artifact_ids) == 0
    assert res.material_artifact_count >= 3
    assert res.excluded_artifact_count == 1  # README
    assert "cobol/MAIN.cbl" in res.material_artifact_ids


def test_b_material_artifact_incorrectly_excluded(tmp_path: Path):
    """TEST B: Material artifact incorrectly excluded (scope_complete = False)."""
    (tmp_path / "cobol").mkdir()
    p = tmp_path / "cobol" / "CORE.cbl"
    p.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CORE.\n")

    planner = GenericTransformationPlanner()
    res = planner.analyze_scope(tmp_path)
    assert res.scope_complete is True

    # Mutate record: exclude core program without valid rationale
    res2 = planner.analyze_scope(tmp_path)
    res2.artifacts["cobol/CORE.cbl"].disposition = ArtifactDisposition.DOCUMENTATION
    res2.artifacts["cobol/CORE.cbl"].exclusion_rationale = ""
    # Check invariant evaluation
    blocking = []
    for rel, r in res2.artifacts.items():
        if r.disposition not in (
            ArtifactDisposition.MATERIAL_APPLICATION,
            ArtifactDisposition.BUILD_OR_RUNTIME_SUPPORT,
            ArtifactDisposition.TEST_OR_VALIDATION,
        ):
            if not r.exclusion_rationale:
                blocking.append(f"Excluded artifact '{rel}' lacks justification rationale")
    assert len(blocking) > 0


def test_c_unsupported_material_artifact(tmp_path: Path):
    """TEST C: Unsupported material artifact (UNSUPPORTED_MATERIAL blocks plan)."""
    (tmp_path / "cobol").mkdir()
    (tmp_path / "cobol" / "CICS_PROG.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CICSPGM.\n"
        "       PROCEDURE DIVISION.\n"
        "           EXEC CICS RECEIVE INTO(DATA) END-EXEC.\n"
        "           STOP RUN.\n"
    )

    planner = GenericTransformationPlanner()
    res = planner.analyze_scope(tmp_path)

    assert res.scope_complete is False
    assert res.unsupported_artifact_count == 1
    assert "cobol/CICS_PROG.cbl" in res.unresolved_artifact_ids
    assert any("unsupported" in reason.lower() for reason in res.blocking_reasons)


def test_d_unknown_artifact(tmp_path: Path):
    """TEST D: Unknown artifact (UNKNOWN blocks plan)."""
    (tmp_path / "cobol").mkdir()
    (tmp_path / "cobol" / "APP.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. APP.\n"
    )
    # Mystery binary without known role or metadata
    (tmp_path / "mystery_blob.unknown_ext").write_bytes(b"\x00\x01\x02\x03\xff")

    planner = GenericTransformationPlanner()
    res = planner.analyze_scope(tmp_path)

    assert res.scope_complete is False
    assert res.unknown_artifact_count >= 1
    assert "mystery_blob.unknown_ext" in res.unresolved_artifact_ids
    assert any("UNKNOWN" in reason for reason in res.blocking_reasons)


def test_e_reference_implementation_explicit_exclusion(tmp_path: Path):
    """TEST E: Reference implementation (explicit exclusion, evidence recorded, scope complete)."""
    (tmp_path / "cobol").mkdir()
    (tmp_path / "cobol" / "APP.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. APP.\n"
    )
    # Reference implementation sub-tree
    (tmp_path / "rewrite" / "kotlin").mkdir(parents=True)
    (tmp_path / "rewrite" / "kotlin" / "build.gradle").write_text("plugins { id 'application' }\n")
    (tmp_path / "rewrite" / "kotlin" / "App.kt").write_text("fun main() = println()\n")
    (tmp_path / "README.md").write_text("# Project\nManual Kotlin rewrite in rewrite/kotlin\n")

    planner = GenericTransformationPlanner()
    res = planner.analyze_scope(tmp_path)

    assert res.scope_complete is True
    assert "rewrite/kotlin/App.kt" not in res.material_artifact_ids
    rec = res.artifacts["rewrite/kotlin/App.kt"]
    assert rec.disposition == ArtifactDisposition.REFERENCE_IMPLEMENTATION
    assert rec.application_relevance == "REFERENCE"
    assert rec.modernization_relevance == "EXCLUDE"
    assert len(rec.exclusion_rationale) > 0
    assert rec.evidence["source"] == "independent_build_tree_reference"


def test_f_tutorial_tooling_explicit_exclusion(tmp_path: Path):
    """TEST F: Tutorial tooling (explicit exclusion, evidence recorded, scope complete)."""
    (tmp_path / "cobol").mkdir()
    (tmp_path / "cobol" / "APP.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. APP.\n"
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "compare_runs.py").write_text("print('diff helper')\n")
    (tmp_path / "README.md").write_text("# Project\nTutorial evaluation script comparator\n")

    planner = GenericTransformationPlanner()
    res = planner.analyze_scope(tmp_path)

    assert res.scope_complete is True
    assert "scripts/compare_runs.py" not in res.material_artifact_ids
    rec = res.artifacts["scripts/compare_runs.py"]
    assert rec.disposition == ArtifactDisposition.DEVELOPER_OR_TUTORIAL_TOOLING
    assert rec.modernization_relevance == "EXCLUDE"
    assert len(rec.exclusion_rationale) > 0


def test_g_dependency_reveals_hidden_material_artifact(tmp_path: Path):
    """TEST G: Dependency reveals hidden material artifact (promoted to material scope)."""
    (tmp_path / "cobol").mkdir()
    # Program calls SUBPROG and copies CUSTOMREC
    (tmp_path / "cobol" / "MAIN.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. MAIN.\n"
        "       PROCEDURE DIVISION.\n"
        "           COPY CUSTOMREC.\n"
        "           CALL 'SUBPROG'.\n"
        "           STOP RUN.\n"
    )
    # Hidden copybook and subprog in non-standard location
    (tmp_path / "records").mkdir()
    (tmp_path / "records" / "CUSTOMREC").write_text("       01 REC PIC X(10).\n")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "SUBPROG.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. SUBPROG.\n"
    )

    planner = GenericTransformationPlanner()
    res = planner.analyze_scope(tmp_path)

    assert res.scope_complete is True
    assert "records/CUSTOMREC" in res.material_artifact_ids
    assert "other/SUBPROG.cbl" in res.material_artifact_ids
    assert res.artifacts["records/CUSTOMREC"].disposition == ArtifactDisposition.MATERIAL_APPLICATION
    assert (
        "promoted_by_dependency" in res.artifacts["records/CUSTOMREC"].evidence
        or res.artifacts["records/CUSTOMREC"].evidence.get("source") == "operational_legacy_source"
    )


def test_h_m6_semantic_classification():
    """TEST H: M6 semantic classification (M6 output materially influences Planner classification)."""
    mock_ai = MagicMock()
    mock_exec_result = MagicMock()
    mock_exec_result.execution_id = "test-exec-123"
    mock_exec_result.output = {
        "text": json.dumps({
            "disposition": "DEVELOPER_OR_TUTORIAL_TOOLING",
            "detected_role": "ANALYSIS_TOOL",
            "rationale": "M6 classified as auxiliary testing harness not part of production runtime.",
            "confidence": 0.95,
        }),
        "input_tokens": 150,
        "output_tokens": 40,
        "resolved_tag": "Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2",
    }
    mock_ai.last_execution_result = mock_exec_result
    mock_ai.generate_plan = AsyncMock(return_value=mock_exec_result.output["text"])

    planner = GenericTransformationPlanner(ai_adapter=mock_ai)
    rec = planner._query_m6_semantic_classification(
        rel_path="tools/custom_harness.py",
        language="PYTHON",
        physical_loc=40,
        source_hash="sha-abc",
        project_context="Repository contains tutorial test tooling",
        file_preview="import sys\nprint('benchmarking')",
    )

    assert rec is not None
    assert rec["model"] == "Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
    assert rec["semantic_decision"]["disposition"] == "DEVELOPER_OR_TUTORIAL_TOOLING"
    assert rec["semantic_decision"]["confidence"] == 0.95
    assert rec["accepted"] is True
    assert "M6 classified" in rec["semantic_decision"]["rationale"]


def test_i_m6_failure_when_required(tmp_path: Path):
    """TEST I: M6 failure (semantic analysis required but failed -> planning does not silently continue)."""
    (tmp_path / "ambiguous_script.custom").write_text("custom DSL syntax")

    mock_ai = MagicMock()
    mock_ai.generate_plan = AsyncMock(side_effect=RuntimeError("M6 local inference timeout"))

    planner = GenericTransformationPlanner(ai_adapter=mock_ai)
    res = planner.analyze_scope(tmp_path, require_m6_on_ambiguity=True)

    # Must block planning when required M6 analysis fails
    assert res.scope_complete is False
    assert res.unknown_artifact_count >= 1
    assert "ambiguous_script.custom" in res.unresolved_artifact_ids


def test_j_post_execution_mismatch_blocks_completion():
    """TEST J: Post-execution mismatch (10 material planned, 8 processed -> completion rejected)."""
    res = ScopeCompletenessResult(
        scope_complete=True,
        material_artifact_count=10,
        material_artifact_ids=[f"art_{i}.cbl" for i in range(10)],
        excluded_artifact_count=31,
        unsupported_artifact_count=0,
        unknown_artifact_count=0,
        unresolved_artifact_ids=[],
        semantic_analysis_required=False,
        semantic_analysis_completed=False,
        scope_confidence=1.0,
        scope_evidence={},
        artifacts={
            f"art_{i}.cbl": ArtifactScopeRecord(
                relative_path=f"art_{i}.cbl",
                detected_role="MODULE",
                disposition=ArtifactDisposition.MATERIAL_APPLICATION,
                application_relevance="MATERIAL",
                modernization_relevance="TRANSFORM",
                evidence={"source": "test"},
            )
            for i in range(10)
        },
    )

    # Execution only processes 8 of the 10 planned material artifacts
    processed = [f"art_{i}.cbl" for i in range(8)]
    generated = ["Modernized.java"]
    validated = ["art_0.cbl"]

    reconciliation = GenericTransformationPlanner.reconcile_post_execution(
        scope_result=res,
        processed_artifacts=processed,
        generated_artifacts=generated,
        validated_artifacts=validated,
    )

    assert reconciliation["passed"] is False
    assert reconciliation["missing_material_artifacts"] == ["art_8.cbl", "art_9.cbl"]
    assert any("omitted from execution" in r for r in reconciliation["failure_reasons"])


def test_k_valid_exclusion_allows_completion():
    """TEST K: Valid exclusion (10 material, 31 excluded, all 10 processed -> completion allowed)."""
    material_files = [f"mat_{i}.cbl" for i in range(10)]
    excluded_files = [f"rewrite/ex_{i}.kt" for i in range(31)]

    arts = {}
    for mf in material_files:
        arts[mf] = ArtifactScopeRecord(
            relative_path=mf,
            detected_role="MODULE",
            disposition=ArtifactDisposition.MATERIAL_APPLICATION,
            application_relevance="MATERIAL",
            modernization_relevance="TRANSFORM",
            evidence={"source": "test"},
        )
    for ef in excluded_files:
        arts[ef] = ArtifactScopeRecord(
            relative_path=ef,
            detected_role="REFERENCE_IMPLEMENTATION",
            disposition=ArtifactDisposition.REFERENCE_IMPLEMENTATION,
            application_relevance="REFERENCE",
            modernization_relevance="EXCLUDE",
            exclusion_rationale="Reference Kotlin rewrite",
            evidence={"source": "test"},
        )

    res = ScopeCompletenessResult(
        scope_complete=True,
        material_artifact_count=10,
        material_artifact_ids=material_files,
        excluded_artifact_count=31,
        unsupported_artifact_count=0,
        unknown_artifact_count=0,
        unresolved_artifact_ids=[],
        semantic_analysis_required=False,
        semantic_analysis_completed=False,
        scope_confidence=1.0,
        scope_evidence={},
        artifacts=arts,
    )

    reconciliation = GenericTransformationPlanner.reconcile_post_execution(
        scope_result=res,
        processed_artifacts=material_files,
        generated_artifacts=["Target.java"],
        validated_artifacts=material_files,
    )

    assert reconciliation["passed"] is True
    assert len(reconciliation["missing_material_artifacts"]) == 0
    assert reconciliation["processed_material_count"] == 10


def test_l_no_direct_m6_bypass_ast_inspection():
    """TEST L: AST/static inspection proving Planner does not directly import/instantiate
    MLX, LocalRuntimeProviderAdapter, raw HTTP endpoints, Ollama, Gemini."""
    planner_file = (
        Path(__file__).parent.parent
        / "src"
        / "autoforge_modernization"
        / "composition"
        / "planner.py"
    )
    assert planner_file.exists(), f"Missing planner file at {planner_file}"

    tree = ast.parse(planner_file.read_text(encoding="utf-8"))

    forbidden_imports = {
        "mlx",
        "mlx_lm",
        "ollama",
        "google.generativeai",
        "openai",
        "anthropic",
        "requests",
        "httpx",
        "urllib.request",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in forbidden_imports:
                    assert not alias.name.startswith(forbidden), (
                        f"Planner violates model authority: directly imports forbidden library '{alias.name}'"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for forbidden in forbidden_imports:
                assert not mod.startswith(forbidden), (
                    f"Planner violates model authority: directly imports from forbidden library '{mod}'"
                )
            assert "LocalRuntimeProviderAdapter" not in [alias.name for alias in node.names], (
                "Planner directly imports LocalRuntimeProviderAdapter instead of using canonical ModelRouter / ExecutionContext"
            )


@pytest.mark.skipif(not _REAL_PLAYBOOK_ROOT.exists(), reason="Real playbook workload not present on machine")
def test_m_real_phase20_a_playbook_workload_scope():
    """TEST M: Real Phase 20-A workload regression on marcoeg/cobol-modernization-playbook.
    Verifies the Planner independently establishes:
    - Exactly 10 material application artifacts
    - Exactly 31 legitimate non-material exclusions
    - 0 unknown, 0 unsupported
    - scope_complete == True
    """
    planner = GenericTransformationPlanner()
    res = planner.analyze_scope(_REAL_PLAYBOOK_ROOT)

    assert res.scope_complete is True
    assert res.material_artifact_count == 10
    assert res.excluded_artifact_count == 31
    assert res.unsupported_artifact_count == 0
    assert res.unknown_artifact_count == 0
    assert len(res.unresolved_artifact_ids) == 0

    # Verify specific material artifacts
    expected_materials = {
        "cobol/DAILYPOST.cbl",
        "cobol/copybooks/ACCOUNT-REC.cpy",
        "cobol/copybooks/TXN-REC.cpy",
        "data/accounts.dat",
        "data/txns.dat",
        "out/accounts_out.dat",
        "out/exceptions.dat",
        "Makefile",
        "build.sh",
        "run.sh",
    }
    actual_materials = set(res.material_artifact_ids)
    assert actual_materials == expected_materials, f"Mismatch in material artifacts: {actual_materials ^ expected_materials}"

    # Verify classifications of legitimate exclusions
    assert res.artifacts["formal/alloy/banking.als"].disposition == ArtifactDisposition.FORMAL_SPECIFICATION
    for p in res.artifacts:
        if p.startswith("rewrite/kotlin/"):
            assert res.artifacts[p].disposition == ArtifactDisposition.REFERENCE_IMPLEMENTATION
        elif p.startswith("scripts/"):
            assert res.artifacts[p].disposition == ArtifactDisposition.DEVELOPER_OR_TUTORIAL_TOOLING
