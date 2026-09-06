"""Tests for Cross-Technology Autonomous Engineering Execution.

Validates:
1. Real source parsing and technology-neutral semantic model extraction.
2. Target capability requirement resolution and autonomous acquisition.
3. Generalized target code generation without technology-pair engines.
4. Real toolchain verification (real javac compilation producing .class files).
5. Autonomous failure handling (defect -> compiler failure -> diagnosis -> repair -> re-verification).
6. End-to-end modernization provenance binding.
7. Multi-target cross-technology support (Java & Python).
"""

from __future__ import annotations

from pathlib import Path
import pytest

from autoforge_modernization.capabilities.acquisition import (
    AcquisitionStatus,
    AutonomousAcquisitionEngine,
)
from autoforge_modernization.capabilities.gap_analyzer import (
    CapabilityGapAnalyzer,
    CapabilityGapItem,
)
from autoforge_modernization.capabilities.models import CapabilityClass, CapabilityState
from autoforge_modernization.capabilities.providers import OpenJDKProvider, ProviderRegistry
from autoforge_modernization.composition.generator import (
    GeneratedArtifact,
    GenericTargetArtifactGenerator,
)
from autoforge_modernization.composition.planner import GenericTransformationPlanner
from autoforge_modernization.composition.repair import AutonomousTargetRepairCycle
from autoforge_modernization.composition.verifier import (
    TargetToolchainVerifier,
    TargetVerificationResult,
)
from autoforge_modernization.composition.workflow import (
    DynamicCapabilityWorkflow,
)
from autoforge_modernization.provenance import ProvenanceStage
from autoforge_modernization.repair_cycle import RepairStatus
from autoforge_modernization.semantic.extractors import SemanticModelExtractor
from autoforge_modernization.semantic.model import (
    SemanticDataType,
    SemanticField,
    SemanticModule,
    TechnologyNeutralSemanticModel,
)
from autoforge_modernization.target.specification import (
    TargetCapabilityDeriver,
    TargetSpecification,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture
def carddemo_path(repo_root: Path) -> Path:
    return repo_root / ".autoforge" / "carddemo" / "app"


class TestCrossTechnologyExecution:
    """Test suite verifying generalized cross-technology autonomous engineering."""

    def test_source_understanding_real_cobol_and_copybooks(self, carddemo_path: Path) -> None:
        """Test real parsing of CardDemo COBOL program and copybook dependency extraction."""
        cbl_file = carddemo_path / "cbl" / "CBACT01C.cbl"
        assert cbl_file.exists(), "CBACT01C.cbl must exist in CardDemo benchmark"

        extractor = SemanticModelExtractor()
        content = cbl_file.read_text(encoding="utf-8", errors="replace")
        mod = extractor.extract_from_cobol(content, file_path="cbl/CBACT01C.cbl")

        assert mod.name == "CBACT01C"
        assert mod.source_technology == "COBOL"
        assert mod.module_type == "program"
        assert len(mod.procedures) > 5
        # Verify procedure names and operations extracted
        proc_names = [p.name for p in mod.procedures]
        assert any("0000-ACCTFILE-OPEN" in name for name in proc_names)
        assert any("1000-ACCTFILE-GET-NEXT" in name for name in proc_names)

        # Verify copybook references captured
        assert any("COPYBOOK:CVACT01Y" in dep for dep in mod.external_dependencies)

    def test_source_understanding_real_jcl_job(self, carddemo_path: Path) -> None:
        """Test real parsing of CardDemo JCL batch job."""
        jcl_file = carddemo_path / "jcl" / "ACCTFILE.jcl"
        assert jcl_file.exists(), "ACCTFILE.jcl must exist in CardDemo benchmark"

        extractor = SemanticModelExtractor()
        content = jcl_file.read_text(encoding="utf-8", errors="replace")
        mod = extractor.extract_from_jcl(content, file_path="jcl/ACCTFILE.jcl")

        assert mod.source_technology == "JCL"
        assert mod.module_type == "job"
        assert len(mod.procedures) >= 3  # STEP05, STEP10, STEP15
        assert any("IDCAMS" in dep for dep in mod.external_dependencies)

    def test_target_requirement_derivation_java_and_python(self) -> None:
        """Test target requirement resolution without pair-specific rules."""
        deriver = TargetCapabilityDeriver()

        # Java Spring Boot target
        java_spec = TargetSpecification.java_spring_boot()
        java_reqs = deriver.derive_requirements(java_spec)
        req_names = [r.capability_name for r in java_reqs]
        assert "java_source_generation" in req_names
        assert "javac_compilation" in req_names
        assert "java_syntax_check" in req_names

        # Python FastAPI target
        py_spec = TargetSpecification.python_fastapi()
        py_reqs = deriver.derive_requirements(py_spec)
        py_req_names = [r.capability_name for r in py_reqs]
        assert "python_source_generation" in py_req_names
        assert "python_byte_compile" in py_req_names

    def test_autonomous_capability_acquisition_openjdk(self) -> None:
        """Test that AutonomousAcquisitionEngine safely acquires and qualifies OpenJDK."""
        registry = ProviderRegistry()
        engine = AutonomousAcquisitionEngine(provider_registry=registry, allow_external_install=False)

        # OpenJDK provider
        openjdk = registry.get("provider-openjdk")
        assert openjdk is not None

        # Simulate gap item for javac_compilation
        from autoforge_modernization.capabilities.gap_analyzer import CapabilityGapItem
        gap_item = CapabilityGapItem(
            technology="JAVA",
            capability_class=CapabilityClass.TARGET_VERIFICATION,
            capability_name="javac_compilation",
            description="Java compiler verification",
            state=CapabilityState.ACQUIRABLE,
            provider_id=openjdk.provider_id,
        )

        record = engine.process_gap_item(gap_item)
        assert record.status in (AcquisitionStatus.SUCCESS, AcquisitionStatus.ALREADY_QUALIFIED)
        assert len(record.qualification_records) > 0
        assert record.qualification_records[0].passed is True

    def test_generic_target_generation_no_pair_engines(self) -> None:
        """Test that GenericTargetArtifactGenerator creates idiomatic code without pair classes."""
        semantic_model = TechnologyNeutralSemanticModel(project_id="test-proj")
        mod = SemanticModule(
            name="TESTPROG",
            module_type="program",
            source_technology="COBOL",
            source_file_path="cbl/TESTPROG.cbl",
            source_sha256="abc123hash",
            fields=[
                SemanticField(name="ACCOUNT-ID", data_type=SemanticDataType.INTEGER),
                SemanticField(name="BALANCE", data_type=SemanticDataType.DECIMAL),
                SemanticField(name="ACTIVE-FLAG", data_type=SemanticDataType.BOOLEAN),
                SemanticField(name="OWNER-NAME", data_type=SemanticDataType.STRING),
            ],
        )
        semantic_model.add_module(mod)

        planner = GenericTransformationPlanner()
        generator = GenericTargetArtifactGenerator()

        # Generate Java
        java_spec = TargetSpecification.java_spring_boot()
        java_plan = planner.plan(semantic_model, java_spec)
        java_artifacts = generator.generate(semantic_model, java_plan, java_spec)
        assert len(java_artifacts) == 1
        java_code = java_artifacts[0].code
        assert "package com.autoforge.generated;" in java_code
        assert "private long accountId" in java_code
        assert "private BigDecimal balance" in java_code
        assert "public long getAccountId()" in java_code

        # Generate Python using SAME neutral model
        py_spec = TargetSpecification.python_fastapi()
        py_plan = planner.plan(semantic_model, py_spec)
        py_artifacts = generator.generate(semantic_model, py_plan, py_spec)
        assert len(py_artifacts) == 1
        py_code = py_artifacts[0].code
        assert "class Testprog:" in py_code
        assert "def execute(self)" in py_code

    def test_real_target_verification_javac_compiles_bytecode(self, tmp_path: Path) -> None:
        """Test that TargetToolchainVerifier executes real javac and generates .class files."""
        verifier = TargetToolchainVerifier()
        artifact = GeneratedArtifact(
            component_name="SimpleService",
            target_language="Java",
            relative_path="src/main/java/com/autoforge/generated/SimpleService.java",
            code=(
                "package com.autoforge.generated;\n"
                "public class SimpleService {\n"
                "    public int add(int a, int b) { return a + b; }\n"
                "}\n"
            ),
        )

        res = verifier.verify([artifact], TargetSpecification.java_spring_boot(), build_directory=tmp_path)
        assert res.passed is True
        assert "javac" in res.toolchain_used.lower()
        assert len(res.class_files_generated) == 1
        class_file = Path(res.class_files_generated[0])
        assert class_file.exists()
        assert class_file.stat().st_size > 0

    def test_autonomous_failure_handling_defect_and_repair(self, tmp_path: Path) -> None:
        """Test the complete failure -> diagnosis -> repair -> re-verification cycle."""
        verifier = TargetToolchainVerifier()
        repair_cycle = AutonomousTargetRepairCycle(verifier=verifier)

        # Artifact with intentional syntax defect
        failing_artifact = GeneratedArtifact(
            component_name="DefectiveService",
            target_language="Java",
            relative_path="src/main/java/com/autoforge/generated/DefectiveService.java",
            code="DEFECT_INJECTED_BAD_TOKEN;\npackage com.autoforge.generated;\npublic class DefectiveService {}\n",
        )

        initial_res = verifier.verify([failing_artifact], TargetSpecification.java_spring_boot(), build_directory=tmp_path / "fail_build")
        assert initial_res.passed is False
        assert len(initial_res.diagnostics) > 0

        # Run autonomous repair cycle
        repaired_arts, outcome, final_res = repair_cycle.repair_cycle(
            artifacts=[failing_artifact],
            initial_result=initial_res,
            target_spec=TargetSpecification.java_spring_boot(),
        )

        assert outcome.final_status == RepairStatus.SUCCESS
        assert outcome.total_attempts == 1
        assert final_res.passed is True
        assert len(final_res.class_files_generated) == 1
        assert "DEFECT_INJECTED" not in repaired_arts[0].code

    def test_full_workflow_clean_execution_carddemo(self, carddemo_path: Path) -> None:
        """Integration test: Full lifecycle on real CardDemo COBOL + JCL."""
        wf = DynamicCapabilityWorkflow()
        report = wf.execute(
            project_path=carddemo_path,
            target_spec=TargetSpecification.java_spring_boot(),
            workload_files=["cbl/CBACT01C.cbl", "cbl/CBACT02C.cbl", "jcl/ACCTFILE.jcl"],
            inject_defect_for_repair_proof=False,
        )

        assert report.success is True
        assert len(report.generated_artifacts) == 3
        assert len(report.class_files_generated) == 3
        assert report.verification_result is not None
        assert report.verification_result.passed is True

        # Check provenance chain completeness
        prov = report.provenance_chain
        assert prov is not None
        assert prov.is_complete is True
        stages = set(prov.get_stages_completed())
        assert ProvenanceStage.SOURCE in stages
        assert ProvenanceStage.TRANSFORMATION in stages
        assert ProvenanceStage.VERIFICATION in stages
        assert ProvenanceStage.ARTIFACT in stages

    def test_bounded_behavioral_verification_cbact01c(self, carddemo_path: Path, repo_root: Path) -> None:
        """Test bounded behavioral equivalence between CardDemo COBOL rule and target runtimes."""
        import subprocess

        wf = DynamicCapabilityWorkflow()

        # 1. Java execution
        java_run = wf.execute(
            project_path=carddemo_path,
            target_spec=TargetSpecification.java_spring_boot(),
            workload_files=["cbl/CBACT01C.cbl"],
            inject_defect_for_repair_proof=False,
        )
        assert java_run.success is True
        assert len(java_run.class_files_generated) == 1

        java_bin = repo_root / ".autoforge" / "tools" / "openjdk" / "bin" / "java"
        bin_dir = Path(java_run.class_files_generated[0]).parent.parent.parent.parent

        test_cases = [("00", 0), ("10", 16), ("99", 12)]
        for inp, expected_rc in test_cases:
            cmd = [str(java_bin), "-cp", str(bin_dir), "com.autoforge.generated.Cbact01c", inp]
            p = subprocess.run(cmd, capture_output=True, text=True)
            assert f"STATUS_RESULT={expected_rc}" in p.stdout.strip(), f"JVM output mismatch for {inp}: {p.stdout}"

        # 2. Python execution
        py_run = wf.execute(
            project_path=carddemo_path,
            target_spec=TargetSpecification.python_fastapi(),
            workload_files=["cbl/CBACT01C.cbl"],
            inject_defect_for_repair_proof=False,
        )
        assert py_run.success is True
        py_art = py_run.generated_artifacts[0]
        py_ns: dict[str, Any] = {}
        exec(py_art.code, py_ns)
        py_inst = py_ns["Cbact01c"]()

        for inp, expected_rc in test_cases:
            assert py_inst.evaluate_file_status(inp) == expected_rc
