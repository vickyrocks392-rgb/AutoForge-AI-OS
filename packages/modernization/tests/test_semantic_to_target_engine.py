"""Comprehensive Unit & Integration Test Suite for Semantic-to-Target Engineering Engine.

Tests all 14 mandatory dimensions:
1. System-level architecture derivation
2. Cross-module dependency mapping
3. CALL / interface mapping
4. Unresolved external dependency handling (anti-fabrication)
5. Shared data ownership & domain model mapping
6. DataStore / I/O architecture mapping
7. JCL execution & orchestration mapping
8. Business rule preservation across modules
9. Error semantics & status branch preservation
10. Target component graph querying & edges
11. Coordinated target artifact generation
12. Multi-target architectural divergence (Java vs Python)
13. End-to-end modernization provenance binding
14. Real CardDemo multi-module compilation & JVM behavioral execution
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import pytest

from autoforge_modernization.composition.generator import GenericTargetArtifactGenerator
from autoforge_modernization.composition.planner import (
    ArtifactRole,
    GenericTransformationPlanner,
    TargetSystemArchitecture,
)
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.provenance import (
    ModernizationProvenanceChain,
    ProvenanceLink,
    ProvenanceStage,
)
from autoforge_modernization.semantic.extractors import ProjectSemanticExtractor
from autoforge_modernization.target.specification import TargetSpecification


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture
def carddemo_app(repo_root: Path) -> Path:
    app_dir = repo_root / ".autoforge" / "carddemo" / "app"
    if not app_dir.exists():
        pytest.skip(f"CardDemo not found at {app_dir}")
    return app_dir


@pytest.fixture
def carddemo_multi_module(carddemo_app: Path):
    workload = [
        carddemo_app / "cbl" / "CBACT01C.cbl",
        carddemo_app / "cbl" / "COTRN02C.cbl",
        carddemo_app / "cbl" / "CSUTLDTC.cbl",
        carddemo_app / "cpy" / "CVACT01Y.cpy",
        carddemo_app / "jcl" / "READACCT.jcl",
    ]
    extractor = ProjectSemanticExtractor()
    model = extractor.extract_project(carddemo_app, file_paths=workload)
    planner = GenericTransformationPlanner()
    java_spec = TargetSpecification.java_spring_boot()
    plan = planner.plan(model, java_spec)
    return model, plan, java_spec


class TestSemanticToTargetEngineeringEngine:
    """Rigorous tests proving system-level transformation without pair-specific engines."""

    def test_system_level_architecture_derivation(self, carddemo_multi_module):
        """1. Verify system-level target architecture is derived with components and graph."""
        model, plan, _ = carddemo_multi_module

        assert plan.target_system_architecture is not None
        arch: TargetSystemArchitecture = plan.target_system_architecture
        assert arch.architecture_style in ("MODULAR_SERVICE", "LAYERED_SERVICE", "HEXAGONAL")
        assert len(plan.target_components) >= 5

        comp_names = {c.name for c in plan.target_components}
        assert {"Cvact01y", "Cbact01c", "Cotrn02c", "Csutldtc", "ReadacctOrchestration"}.issubset(comp_names)

    def test_cross_module_dependency_mapping(self, carddemo_multi_module):
        """2. Verify cross-module dependencies are explicitly mapped."""
        model, plan, _ = carddemo_multi_module

        deps = plan.cross_module_dependencies
        assert len(deps) >= 2

        # Check COTRN02C -> CSUTLDTC call mapping
        cotrn_call = next((d for d in deps if d.source_caller_module == "COTRN02C" and d.source_callee_module == "CSUTLDTC"), None)
        assert cotrn_call is not None
        assert cotrn_call.source_relationship_kind == "CALLS"
        assert cotrn_call.target_caller_component == "Cotrn02c"
        assert cotrn_call.target_callee_component == "Csutldtc"
        assert cotrn_call.target_relationship_kind == "INVOKES"
        assert cotrn_call.interaction_pattern in ("SERVICE_INJECTION", "SYNCHRONOUS_METHOD_CALL")

    def test_call_and_interface_mapping(self, carddemo_multi_module):
        """3. Verify CALL relationships produce explicit target interfaces/contracts."""
        model, plan, _ = carddemo_multi_module

        # Target component graph contains edges representing cross-module calls
        comp_graph = plan.target_system_architecture.component_graph
        call_edges = [e for e in comp_graph.edges if e.kind in ("INVOKES", "ORCHESTRATES")]
        assert len(call_edges) >= 1
        assert any(e.kind == "INVOKES" for e in call_edges)

    def test_unresolved_external_dependency_handling(self, carddemo_multi_module):
        """4. Verify unresolved external calls (CEEDAYS, IEFBR14, CEE3ABD) remain explicitly tracked."""
        model, plan, _ = carddemo_multi_module

        ext_deps = plan.external_dependencies
        assert len(ext_deps) >= 3

        ext_names = {ed.unresolved_target_name for ed in ext_deps}
        assert "CEEDAYS" in ext_names
        assert "IEFBR14" in ext_names
        assert "CEE3ABD" in ext_names

        # Verify anti-fabrication properties
        ceedays = next(ed for ed in ext_deps if ed.unresolved_target_name == "CEEDAYS")
        assert ceedays.source_module == "CSUTLDTC"
        assert ceedays.affected_component == "Csutldtc"
        assert not ceedays.is_blocking
        assert ceedays.confidence == 0.0
        assert "CEEDAYS" in ceedays.recommended_resolution_path

    def test_shared_data_ownership_and_mapping(self, carddemo_multi_module):
        """5. Verify copybook-derived shared schema CVACT01Y receives explicit target ownership."""
        model, plan, _ = carddemo_multi_module

        shared = plan.shared_data_decisions
        assert len(shared) >= 1

        cvact = next((s for s in shared if s.entity_name == "CVACT01Y"), None)
        assert cvact is not None
        assert cvact.target_model_name == "Cvact01y"
        assert cvact.ownership_strategy == "SHARED_DOMAIN_MODEL"
        assert cvact.target_role == ArtifactRole.DOMAIN_MODEL
        assert "COTRN02C" in cvact.sharing_modules
        assert "CBACT01C" in cvact.sharing_modules

    def test_datastore_io_mapping(self, carddemo_multi_module):
        """6. Verify file and dataset I/O are mapped to target data access boundaries."""
        model, plan, _ = carddemo_multi_module

        stores = plan.datastore_mappings
        assert len(stores) >= 3

        store_names = {ds.dataset_name for ds in stores}
        assert "ACCTFILE" in store_names

        acct_store = next(ds for ds in stores if ds.dataset_name == "ACCTFILE")
        assert acct_store.resource_type == "vsam"
        assert acct_store.status_semantics_preserved
        assert "sequential" in acct_store.access_modes or "indexed" in acct_store.access_modes

    def test_jcl_execution_orchestration_mapping(self, carddemo_multi_module):
        """7. Verify JCL job READACCT is mapped to target execution pipeline."""
        model, plan, _ = carddemo_multi_module

        flows = plan.execution_orchestration
        assert len(flows) >= 1

        readacct_flow = next(f for f in flows if f.job_name == "READACCT")
        assert readacct_flow.target_orchestrator_name == "ReadacctOrchestration"
        assert len(readacct_flow.steps) >= 2

        step_names = [s["step_name"] for s in readacct_flow.steps]
        assert "PREDEL" in step_names
        assert "STEP05" in step_names

        # PREDEL executes IEFBR14 utility; STEP05 executes CBACT01C
        step05 = next(s for s in readacct_flow.steps if s["step_name"] == "STEP05")
        assert step05["target_component"] == "Cbact01c"

    def test_business_rule_preservation_across_modules(self, carddemo_multi_module):
        """8. Verify business rules are preserved across modules with requirement links."""
        model, plan, _ = carddemo_multi_module

        rules = model.total_business_rules
        assert rules >= 10

        preservations = plan.behavior_preservation_requirements
        assert len(preservations) >= 50

        rule_reqs = [p for p in preservations if p.category == "BUSINESS_RULE"]
        assert len(rule_reqs) >= 10

    def test_error_semantics_preservation(self, carddemo_multi_module):
        """9. Verify status fields and error branches are preserved in requirements."""
        model, plan, _ = carddemo_multi_module

        control_reqs = [p for p in plan.behavior_preservation_requirements if p.category == "CONTROL_FLOW"]
        assert len(control_reqs) >= 10

        # Status field semantics preserved
        assert any("ACCTFILE-STATUS" in p.requirement_statement or "status" in p.requirement_statement.lower() for p in control_reqs)

    def test_target_component_graph_querying(self, carddemo_multi_module):
        """10. Verify TargetComponentGraph supports node and edge queries."""
        model, plan, _ = carddemo_multi_module

        graph = plan.target_system_architecture.component_graph
        assert len(graph.components) >= 4
        assert len(graph.nodes) >= 4

        # Query existing component
        cbact = graph.get_component("Cbact01c")
        assert cbact is not None
        assert cbact.name == "Cbact01c"
        assert cbact.role == ArtifactRole.SERVICE

        # Query incoming/outgoing edges
        edges = graph.edges
        assert len(edges) >= 1

    def test_coordinated_target_artifact_generation(self, carddemo_multi_module):
        """11. Verify generator consumes plan and produces coordinated target artifacts."""
        model, plan, java_spec = carddemo_multi_module

        generator = GenericTargetArtifactGenerator()
        artifacts = generator.generate(model, plan, java_spec)

        assert len(artifacts) >= 5
        art_map = {a.component_name: a for a in artifacts}

        # Inter-artifact coordination assertions
        assert "Csutldtc csutldtc" in art_map["Cotrn02c"].code
        assert "Cvact01y cvact01y" in art_map["Cotrn02c"].code
        assert "Cvact01y cvact01y" in art_map["Cbact01c"].code
        assert "Cbact01c cbact01c" in art_map["ReadacctOrchestration"].code

        # Unresolved dependency documented in Csutldtc Javadoc
        assert "CEEDAYS" in art_map["Csutldtc"].code

    def test_multi_target_architectural_divergence(self, carddemo_multi_module):
        """12. Verify same semantic model produces distinct architectures for Java and Python."""
        model, _, _ = carddemo_multi_module
        planner = GenericTransformationPlanner()

        java_plan = planner.plan(model, TargetSpecification.java_spring_boot())
        py_plan = planner.plan(model, TargetSpecification.python_fastapi())

        assert java_plan.target_language == "Java"
        assert py_plan.target_language == "Python"
        assert java_plan.target_architecture.architecture_style != py_plan.target_architecture.architecture_style

        # File paths differ idiomatic to language
        assert all(c.suggested_relative_path.endswith(".java") for c in java_plan.target_components)
        assert all(c.suggested_relative_path.endswith(".py") for c in py_plan.target_components)

    def test_end_to_end_modernization_provenance(self, carddemo_multi_module):
        """13. Verify complete provenance chain connects source to target."""
        model, plan, java_spec = carddemo_multi_module

        prov_chain = ModernizationProvenanceChain(
            project_id="test-system-provenance",
            job_id="test-system-job",
        )
        prov_chain.add_link(ProvenanceLink(
            stage=ProvenanceStage.ANALYSIS,
            actor="ProjectSemanticExtractor",
            output_evidence_ids=[m.source_sha256 for m in model.modules.values()],
        ))
        prov_chain.add_link(ProvenanceLink(
            stage=ProvenanceStage.PLAN,
            actor="GenericTransformationPlanner",
            input_evidence_ids=[m.source_sha256 for m in model.modules.values()],
            output_artifact_ids=[c.component_id for c in plan.target_components],
        ))

        assert len(prov_chain.links) == 2
        assert prov_chain.links[0].stage == ProvenanceStage.ANALYSIS
        assert prov_chain.links[1].stage == ProvenanceStage.PLAN

    def test_real_carddemo_multi_module_compilation_and_execution(self, carddemo_multi_module, repo_root: Path):
        """14. Real OpenJDK javac compilation and JVM behavioral execution of coordinated system."""
        model, plan, java_spec = carddemo_multi_module

        generator = GenericTargetArtifactGenerator()
        artifacts = generator.generate(model, plan, java_spec)

        verifier = TargetToolchainVerifier()
        v_res = verifier.verify(artifacts, java_spec)
        assert v_res.passed, f"Real javac compilation failed: {v_res.output_snippet}"
        assert len(v_res.class_files_generated) >= 5

        java_bin = repo_root / ".autoforge" / "tools" / "openjdk" / "bin" / "java"
        class_bin_dir = Path(v_res.class_files_generated[0]).parent.parent.parent.parent

        # 1. Orchestrated Job Execution (ReadacctOrchestration -> Cbact01c)
        cmd_orch = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.ReadacctOrchestration"]
        res_orch = subprocess.run(cmd_orch, capture_output=True, text=True, check=True)
        assert "JOB_RESULT=0" in res_orch.stdout

        # 2. Inter-Module Call (Cotrn02c -> Csutldtc)
        cmd_cotrn = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Cotrn02c"]
        res_cotrn = subprocess.run(cmd_cotrn, capture_output=True, text=True, check=True)
        assert "Return code: 0" in res_cotrn.stdout

        # 3. Preserved Date Validation Semantics (Csutldtc)
        cmd_dt_val = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Csutldtc", "2026-09-06", "YYYY-MM-DD"]
        res_dt_val = subprocess.run(cmd_dt_val, capture_output=True, text=True, check=True)
        assert "DATE_RESULT=0" in res_dt_val.stdout

        cmd_dt_err = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Csutldtc", "BAD_DATE", "YYYY-MM-DD"]
        res_dt_err = subprocess.run(cmd_dt_err, capture_output=True, text=True, check=True)
        assert "DATE_RESULT=3" in res_dt_err.stdout or "DATE_RESULT=4" in res_dt_err.stdout

        # 4. Preserved File Status Evaluation Rules (Cbact01c)
        cases = [("00", "STATUS_RESULT=0"), ("10", "STATUS_RESULT=16"), ("99", "STATUS_RESULT=12")]
        for inp, exp in cases:
            cmd_st = [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Cbact01c", inp]
            res_st = subprocess.run(cmd_st, capture_output=True, text=True, check=True)
            assert exp in res_st.stdout
