"""Tests for Phase 18-G Project-Scale Autonomous Transformation Engine.

Verifies:
1. Generalized workload selection via topological dependency closure without hard-coded filenames
2. Project-scale semantic extraction across real CardDemo subsystem (COBOL, JCL, Copybooks)
3. Technology-neutral system semantic graph with CALLS, EXECUTES, and INCLUDES relationships
4. Target system architecture derivation (component graph, shared domain models, orchestrators)
5. Coordinated target generation with ZERO CardDemo hardcoded filenames
6. Real OpenJDK javac toolchain compilation of all generated artifacts into bytecode
7. Real JVM runtime execution of multi-step batch orchestrations (READACCT, READCARD, INTCALC, POSTTRAN)
8. Real JVM execution of inter-module CALLs (Cotrn02c -> Csutldtc, Corpt00c -> Csutldtc)
9. Source-derived behavioral verification matrix (date validation rules, file status return codes)
10. Controlled defect injection -> compilation failure -> autonomous repair -> re-verification -> runtime execution
11. Explicit tracking of unresolved external dependencies (CEEDAYS, CEE3ABD, COBDATFT, IEFBR14)
12. Complete end-to-end modernization provenance chain
"""

from __future__ import annotations

import inspect
from pathlib import Path
import subprocess
from typing import Any

import pytest

from autoforge_modernization.composition.generator import (
    GeneratedArtifact,
    GenericTargetArtifactGenerator,
)
from autoforge_modernization.composition.planner import (
    ArtifactRole,
    GenericTransformationPlanner,
)
from autoforge_modernization.composition.repair import AutonomousTargetRepairCycle
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.composition.workload_selector import (
    TransformationWorkloadSelector,
    WorkloadConstraints,
)
from autoforge_modernization.provenance import (
    ModernizationProvenanceChain,
    ProvenanceLink,
    ProvenanceStage,
)
from autoforge_modernization.repair_cycle import RepairStatus
from autoforge_modernization.semantic.extractors import ProjectSemanticExtractor
from autoforge_modernization.target.specification import TargetSpecification


@pytest.fixture(scope="module")
def carddemo_path() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    p = repo_root / ".autoforge" / "carddemo" / "app"
    if not p.exists():
        pytest.skip(f"CardDemo not present at {p}")
    return p


@pytest.fixture(scope="module")
def selected_workload(carddemo_path: Path):
    selector = TransformationWorkloadSelector()
    constraints = WorkloadConstraints(
        seed_identifiers=["READACCT", "READCARD", "INTCALC", "POSTTRAN", "COTRN02C", "CORPT00C"],
        max_files=20,
    )
    return selector.select_workload(carddemo_path, constraints)


@pytest.fixture(scope="module")
def semantic_model(carddemo_path: Path, selected_workload):
    extractor = ProjectSemanticExtractor()
    return extractor.extract_project(
        carddemo_path, file_paths=[Path(f) for f in selected_workload.selected_files]
    )


@pytest.fixture(scope="module")
def transformation_plan(semantic_model):
    planner = GenericTransformationPlanner()
    target_spec = TargetSpecification.java_spring_boot()
    return planner.plan(semantic_model, target_spec)


@pytest.fixture(scope="module")
def generated_artifacts(semantic_model, transformation_plan):
    generator = GenericTargetArtifactGenerator()
    target_spec = TargetSpecification.java_spring_boot()
    return generator.generate(semantic_model, transformation_plan, target_spec)


@pytest.fixture(scope="module")
def compilation_result(generated_artifacts):
    verifier = TargetToolchainVerifier()
    target_spec = TargetSpecification.java_spring_boot()
    return verifier.verify(generated_artifacts, target_spec)


class TestProjectScaleTransformationEngine:
    """Acceptance test suite for Phase 18-G Project-Scale Autonomous Transformation Engine."""

    def test_1_generalized_workload_selection(self, selected_workload):
        """Verify workload selection operates dynamically without hardcoded file lists."""
        assert selected_workload.total_files >= 15
        assert selected_workload.physical_loc >= 3000
        assert selected_workload.non_comment_loc >= 2000
        assert "COBOL" in selected_workload.technologies_involved
        assert "JCL" in selected_workload.technologies_involved
        assert "COPYBOOK" in selected_workload.technologies_involved
        assert selected_workload.dependencies_count > 20
        assert selected_workload.selection_rationale != ""

    def test_2_project_scale_semantic_extraction(self, semantic_model):
        """Verify technology-neutral semantic model captures modules, procedures, and rules across the workload."""
        assert len(semantic_model.modules) >= 10
        assert len(semantic_model.entities) >= 5
        assert semantic_model.total_procedures >= 15
        assert semantic_model.total_operations >= 50
        assert semantic_model.total_business_rules >= 10
        assert len(semantic_model.io_operations) >= 5

    def test_3_system_semantic_graph_relationships(self, semantic_model):
        """Verify unified semantic graph includes EXECUTES, CALLS, and INCLUDES relationships."""
        graph = semantic_model.semantic_graph
        edge_kinds = {e.kind for e in graph.edges}
        assert "EXECUTES" in edge_kinds
        assert "CALLS" in edge_kinds
        assert "INCLUDES" in edge_kinds
        assert len(graph.nodes) >= 200
        assert len(graph.edges) >= 300

    def test_4_target_architecture_derivation(self, transformation_plan):
        """Verify multi-component target system architecture derives components, interfaces, and shared data."""
        arch = transformation_plan.target_system_architecture
        assert arch is not None
        assert arch.architecture_style == "LAYERED_SERVICE"
        assert len(transformation_plan.target_components) >= 15

        roles = {c.role for c in transformation_plan.target_components}
        assert ArtifactRole.DOMAIN_MODEL in roles
        assert ArtifactRole.SERVICE in roles
        assert ArtifactRole.ENTRY_POINT in roles

        # Verify component graph
        cg = arch.component_graph
        assert len(cg.nodes) >= 15
        assert len(cg.edges) >= 5

        # Verify cross-module dependencies
        assert len(transformation_plan.cross_module_dependencies) >= 5
        assert len(transformation_plan.shared_data_decisions) >= 5
        assert len(transformation_plan.execution_orchestration) >= 3

    def test_5_generator_no_hardcoded_filenames(self):
        """Verify generator implementation contains zero hardcoded CardDemo filenames."""
        from autoforge_modernization.composition import generator

        src = inspect.getsource(generator)
        prohibited_names = ["CSUTLDTC", "CBACT01C", "COTRN02C", "CVACT01Y", "READACCT"]
        for name in prohibited_names:
            # Should not appear in executable statements
            matches = [ln for ln in src.splitlines() if name in ln and not ln.strip().startswith("#")]
            assert len(matches) == 0, f"Found hardcoded '{name}' in generator source: {matches}"

    def test_6_real_openjdk_compilation(self, compilation_result, generated_artifacts):
        """Verify real OpenJDK javac compiles all generated artifacts together into bytecode."""
        assert compilation_result.passed is True
        assert len(compilation_result.class_files_generated) >= len(generated_artifacts)
        assert compilation_result.duration_ms > 0
        assert "javac" in compilation_result.toolchain_used

    def test_7_real_jvm_batch_orchestration(self, compilation_result):
        """Verify real JVM execution of multi-step batch orchestrations."""
        repo_root = Path(__file__).resolve().parents[3]
        java_bin = repo_root / ".autoforge" / "tools" / "java" / "bin" / "java"
        if not java_bin.exists():
            java_bin = Path("/opt/homebrew/bin/java")
        class_bin_dir = Path(compilation_result.build_directory) / "bin"

        orchestrations = [
            "com.autoforge.generated.ReadacctOrchestration",
            "com.autoforge.generated.ReadcardOrchestration",
            "com.autoforge.generated.IntcalcOrchestration",
            "com.autoforge.generated.PosttranOrchestration",
        ]

        for fqcn in orchestrations:
            cmd = [str(java_bin), "-cp", str(class_bin_dir), fqcn]
            p = subprocess.run(cmd, capture_output=True, text=True)
            assert p.returncode == 0, f"{fqcn} failed with code {p.returncode}: {p.stderr}"
            assert "JOB_RESULT=0" in p.stdout

    def test_8_real_jvm_inter_module_calls(self, compilation_result):
        """Verify real JVM execution of inter-module CALL interactions."""
        repo_root = Path(__file__).resolve().parents[3]
        java_bin = repo_root / ".autoforge" / "tools" / "java" / "bin" / "java"
        if not java_bin.exists():
            java_bin = Path("/opt/homebrew/bin/java")
        class_bin_dir = Path(compilation_result.build_directory) / "bin"

        # Cotrn02c and Corpt00c both invoke Csutldtc
        for cls_name in ["com.autoforge.generated.Cotrn02c", "com.autoforge.generated.Corpt00c"]:
            cmd = [str(java_bin), "-cp", str(class_bin_dir), cls_name]
            p = subprocess.run(cmd, capture_output=True, text=True)
            assert p.returncode == 0
            assert "Return code: 0" in p.stdout

    def test_9_source_derived_behavioral_verification(self, compilation_result):
        """Verify preserved date and file status return-code semantics derived from source."""
        repo_root = Path(__file__).resolve().parents[3]
        java_bin = repo_root / ".autoforge" / "tools" / "java" / "bin" / "java"
        if not java_bin.exists():
            java_bin = Path("/opt/homebrew/bin/java")
        class_bin_dir = Path(compilation_result.build_directory) / "bin"

        # Date validations on Csutldtc
        valid_res = subprocess.run(
            [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Csutldtc", "2026-09-06"],
            capture_output=True,
            text=True,
        )
        assert "DATE_RESULT=0" in valid_res.stdout

        invalid_res = subprocess.run(
            [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Csutldtc", "BAD_DATE"],
            capture_output=True,
            text=True,
        )
        assert "DATE_RESULT=4" in invalid_res.stdout

        # File status evaluations on Cbact01c
        st_00 = subprocess.run(
            [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Cbact01c", "00"],
            capture_output=True,
            text=True,
        )
        assert "STATUS_RESULT=0" in st_00.stdout

        st_10 = subprocess.run(
            [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Cbact01c", "10"],
            capture_output=True,
            text=True,
        )
        assert "STATUS_RESULT=16" in st_10.stdout

        st_99 = subprocess.run(
            [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Cbact01c", "99"],
            capture_output=True,
            text=True,
        )
        assert "STATUS_RESULT=12" in st_99.stdout

    def test_10_autonomous_repair_cycle(self, generated_artifacts):
        """Verify controlled defect leads to real compiler failure, diagnosis, mutation, and re-compilation."""
        verifier = TargetToolchainVerifier()
        target_spec = TargetSpecification.java_spring_boot()
        repair_cycle = AutonomousTargetRepairCycle(verifier=verifier, max_attempts=3)

        corrupted = [
            GeneratedArtifact(
                artifact_id=a.artifact_id,
                component_name=a.component_name,
                target_language=a.target_language,
                relative_path=a.relative_path,
                code=a.code,
                source_module_names=a.source_module_names,
            )
            for a in generated_artifacts
        ]
        corrupted[0].code = corrupted[0].code.replace(
            "private static final long serialVersionUID = 1L;",
            "private static final long serialVersionUID = 1L;\n    DEFECT_INJECTED_BAD_TOKEN;",
        )

        fail_res = verifier.verify(corrupted, target_spec)
        assert fail_res.passed is False
        assert len(fail_res.diagnostics) >= 1

        repaired, outcome, re_res = repair_cycle.repair_cycle(corrupted, fail_res, target_spec)
        assert outcome.final_status == RepairStatus.SUCCESS
        assert outcome.total_attempts == 1
        assert re_res.passed is True

    def test_11_explicit_unresolved_dependencies(self, transformation_plan):
        """Verify unresolved external routines are cataloged explicitly without fabricated implementations."""
        ext_deps = transformation_plan.external_dependencies
        assert len(ext_deps) >= 4

        targets = {ed.unresolved_target_name for ed in ext_deps}
        assert "CEEDAYS" in targets
        assert "CEE3ABD" in targets
        assert "COBDATFT" in targets
        assert any(ed.dependency_kind == "SYSTEM_UTILITY" or "IEFBR14" in ed.unresolved_target_name for ed in ext_deps)

        for ed in ext_deps:
            assert ed.confidence == 0.0
            assert ed.recommended_resolution_path != ""

    def test_12_provenance_chain_integrity(self, selected_workload, transformation_plan, generated_artifacts):
        """Verify provenance chain binds source files, analysis, plan, generation, and verification."""
        chain = ModernizationProvenanceChain(project_id="test-proj", job_id="test-job")

        chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.ANALYSIS,
                actor="TransformationWorkloadSelector",
                input_artifact_ids=selected_workload.selected_files,
                output_evidence_ids=["evidence-1"],
            )
        )
        chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.PLAN,
                actor="GenericTransformationPlanner",
                input_artifact_ids=["evidence-1"],
                output_evidence_ids=[c.artifact_id for c in transformation_plan.target_components],
            )
        )
        chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.TRANSFORMATION,
                actor="GenericTargetArtifactGenerator",
                input_artifact_ids=[c.artifact_id for c in transformation_plan.target_components],
                output_evidence_ids=[a.sha256 for a in generated_artifacts],
            )
        )
        chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.VERIFICATION,
                actor="TargetToolchainVerifier",
                input_artifact_ids=[a.sha256 for a in generated_artifacts],
                output_evidence_ids=["verify-1"],
            )
        )

        assert len(chain.links) == 4
        stages = [l.stage.value for l in chain.links]
        assert stages == ["analysis", "plan", "transformation", "verification"]
