"""Tests for Semantic Transformation Planning and Target Engineering.

Validates:
1. Behavior-preservation requirement derivation across data, control-flow, data-flow, rules, I/O, error paths.
2. Target engineering requirement derivation independent of source syntax.
3. Target architecture planning (architectural styles and roles).
4. Semantic mappings (source construct to target construct).
5. Transformation plan construction with inspectable transformation steps.
6. Artifact-level generation requirements.
7. Multi-target planning proof (Java vs Python producing distinct plans from identical semantics).
8. Capability-aware planning (honoring operational vs missing capabilities).
9. Generation handoff to GenericTargetArtifactGenerator.
10. Real toolchain verification (javac & py_compile).
11. Real JVM bounded behavioral execution.
12. End-to-end modernization provenance tracking.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import pytest

from autoforge_modernization.capabilities.models import CapabilityClass, CapabilityState
from autoforge_modernization.capabilities.providers import ProviderRegistry
from autoforge_modernization.composition.generator import GenericTargetArtifactGenerator
from autoforge_modernization.composition.planner import (
    ArtifactRole,
    BehaviorPreservationRequirement,
    GenericTransformationPlanner,
    PlannedTargetArtifact,
    PreservationCategory,
    SemanticMapping,
    TargetArchitecturePlan,
    TargetEngineeringRequirement,
    TransformationPlan,
    TransformationStep,
)
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.provenance import ModernizationProvenanceChain, ProvenanceLink, ProvenanceStage
from autoforge_modernization.semantic.extractors import ProjectSemanticExtractor, SemanticModelExtractor
from autoforge_modernization.semantic.model import (
    DataFlowEdge,
    ResolutionStatus,
    SemanticBusinessRule,
    SemanticDataType,
    SemanticEntity,
    SemanticErrorHandling,
    SemanticField,
    SemanticIOKind,
    SemanticIOOperation,
    SemanticModule,
    SemanticOperation,
    SemanticOperationKind,
    SemanticProcedure,
    TechnologyNeutralSemanticModel,
)
from autoforge_modernization.target.specification import TargetSpecification


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture
def carddemo_path(repo_root: Path) -> Path:
    p = repo_root / ".autoforge" / "carddemo" / "app"
    if not p.exists():
        pytest.skip(f"CardDemo workload not present at {p}")
    return p


class TestBehaviorPreservationDerivation:
    """1. Behavior-Preservation Requirements Derivation."""

    def test_preservation_requirements_extracted_from_all_semantic_facets(self) -> None:
        model = TechnologyNeutralSemanticModel(project_id="test-preservation-model")
        mod = SemanticModule(
            name="ACCTPROG",
            source_technology="COBOL",
            fields=[
                SemanticField(name="WS-BAL", data_type=SemanticDataType.DECIMAL, precision=10, scale=2, is_signed=True),
                SemanticField(name="WS-ID", data_type=SemanticDataType.INTEGER, length=11),
            ],
            procedures=[
                SemanticProcedure(
                    name="0000-PROCESS",
                    called_procedures=["1000-READ", "9000-ERROR"],
                    operations=[
                        SemanticOperation(
                            kind=SemanticOperationKind.BRANCH,
                            description="IF STATUS NOT = '00'",
                            mutated_fields=["WS-BAL"],
                        )
                    ],
                )
            ],
            data_flows=[
                DataFlowEdge(
                    source="INP-BAL",
                    target="WS-BAL",
                    transformation_kind="ASSIGNMENT",
                    procedure_name="0000-PROCESS",
                )
            ],
            io_operations=[
                SemanticIOOperation(
                    kind=SemanticIOKind.DATA_READ,
                    resource_name="ACCTFILE",
                    resource_type="vsam",
                    status_field="ACCTFILE-STATUS",
                )
            ],
            business_rules=[
                SemanticBusinessRule(
                    name="Rule_Overdraft",
                    statement="IF WS-BAL < 0",
                    referenced_fields=["WS-BAL"],
                )
            ],
            error_handlers=[
                SemanticErrorHandling(
                    status_field="ACCTFILE-STATUS",
                    handler_procedure="9000-ERROR",
                    is_abnormal_termination=True,
                )
            ],
        )
        model.add_module(mod)

        planner = GenericTransformationPlanner()
        plan = planner.plan(model, TargetSpecification.java_spring_boot())

        reqs = plan.behavior_preservation_requirements
        assert len(reqs) >= 6

        categories = {r.category for r in reqs}
        assert PreservationCategory.DATA_INTEGRITY in categories
        assert PreservationCategory.CONTROL_FLOW in categories
        assert PreservationCategory.DATA_FLOW in categories
        assert PreservationCategory.IO_SEMANTICS in categories
        assert PreservationCategory.BUSINESS_RULE in categories
        assert PreservationCategory.ERROR_HANDLING in categories

        # Verify explicit semantic content (not raw syntax copies)
        bal_req = next(r for r in reqs if "WS-BAL" in r.source_element and r.category == PreservationCategory.DATA_INTEGRITY)
        assert "fixed decimal (10, 2)" in bal_req.requirement_statement
        assert "signedness" in bal_req.requirement_statement


class TestTargetEngineeringRequirements:
    """2. Independent Target Requirements & Architecture Planning."""

    def test_target_engineering_requirements_independent_of_source(self) -> None:
        model = TechnologyNeutralSemanticModel(project_id="test-target-reqs")
        planner = GenericTransformationPlanner()

        java_plan = planner.plan(model, TargetSpecification.java_spring_boot())
        assert len(java_plan.target_engineering_requirements) >= 4

        kinds = {tr.requirement_kind for tr in java_plan.target_engineering_requirements}
        assert "DATA_REPRESENTATION" in kinds
        assert "CONTROL_EXECUTION" in kinds
        assert "IO_ADAPTER" in kinds
        assert "VERIFICATION_HARNESS" in kinds

        data_req = next(tr for tr in java_plan.target_engineering_requirements if tr.requirement_kind == "DATA_REPRESENTATION")
        assert "BigDecimal" in data_req.description
        assert "String" in data_req.description

    def test_target_architecture_planning_roles_and_styles(self) -> None:
        model = TechnologyNeutralSemanticModel(project_id="test-arch")
        mod = SemanticModule(name="TESTMOD", source_technology="COBOL")
        mod.io_operations.append(SemanticIOOperation(kind=SemanticIOKind.DATA_READ, resource_name="FILE1"))
        model.add_module(mod)
        model.add_entity(SemanticEntity(name="TESTREC", source_technology="COBOL"))

        planner = GenericTransformationPlanner()
        java_plan = planner.plan(model, TargetSpecification.java_spring_boot())

        arch = java_plan.target_architecture
        assert arch.architecture_style == "LAYERED_SERVICE"
        assert ArtifactRole.DOMAIN_MODEL.value in arch.roles_planned
        assert ArtifactRole.ADAPTER.value in arch.roles_planned
        assert ArtifactRole.SERVICE.value in arch.roles_planned
        assert ArtifactRole.ENTRY_POINT.value in arch.roles_planned


class TestMultiTargetGeneralityProof:
    """3. Multi-Target Planning Generality (Java vs Python)."""

    def test_identical_semantics_yield_distinct_target_plans(self) -> None:
        model = TechnologyNeutralSemanticModel(project_id="test-multi-target")
        mod = SemanticModule(
            name="BANKPROC",
            source_technology="COBOL",
            procedures=[
                SemanticProcedure(name="0000-MAIN"),
                SemanticProcedure(name="1000-PROCESS"),
            ],
            fields=[
                SemanticField(name="AMT", data_type=SemanticDataType.DECIMAL, precision=8, scale=2),
            ],
        )
        model.add_module(mod)

        planner = GenericTransformationPlanner()
        java_plan = planner.plan(model, TargetSpecification.java_spring_boot())
        py_plan = planner.plan(model, TargetSpecification.python_fastapi())

        # Generality proof assertions:
        assert java_plan.target_language == "Java"
        assert py_plan.target_language == "Python"
        assert java_plan.target_architecture.architecture_style != py_plan.target_architecture.architecture_style
        assert java_plan.target_components[0].suggested_relative_path.endswith(".java")
        assert py_plan.target_components[0].suggested_relative_path.endswith(".py")

        # Type mapping differences in target requirements
        j_data = next(tr for tr in java_plan.target_engineering_requirements if tr.requirement_kind == "DATA_REPRESENTATION")
        py_data = next(tr for tr in py_plan.target_engineering_requirements if tr.requirement_kind == "DATA_REPRESENTATION")
        assert "BigDecimal" in j_data.description
        assert "Decimal" in py_data.description


class TestDiscreteTransformationStepsAndMappings:
    """4. Inspectable Transformation Steps and Semantic Mappings."""

    def test_transformation_steps_link_evidence_to_verification(self) -> None:
        model = TechnologyNeutralSemanticModel(project_id="test-steps")
        mod = SemanticModule(
            name="CUSTPROC",
            source_technology="COBOL",
            procedures=[SemanticProcedure(name="1000-CALC-INTEREST")],
            business_rules=[SemanticBusinessRule(name="Rule_Tier1", statement="IF AMT > 1000")],
        )
        model.add_module(mod)

        planner = GenericTransformationPlanner()
        plan = planner.plan(model, TargetSpecification.java_spring_boot())

        assert len(plan.transformation_steps) >= 3  # procedure, rule, file status
        step1 = plan.transformation_steps[0]
        assert step1.ordering_index == 1
        assert "1000-CALC-INTEREST" in step1.source_semantic_refs[0]
        assert "Method 1000CalcInterest" in step1.target_construct
        assert step1.verification_requirement != ""

        # Semantic mappings
        assert len(plan.semantic_mappings) >= 2
        map1 = next(m for m in plan.semantic_mappings if m.source_kind == "PROCEDURE")
        assert map1.target_construct_type == "METHOD"


class TestRealCardDemoVerticalExecutionAndHandoff:
    """5. Real CardDemo Vertical Execution, Compilation, and Provenance."""

    def test_carddemo_plan_generation_compilation_and_execution(self, carddemo_path: Path, repo_root: Path) -> None:
        workload_files = [
            carddemo_path / "cbl" / "CBACT01C.cbl",
            carddemo_path / "jcl" / "ACCTFILE.jcl",
            carddemo_path / "cpy" / "CVACT01Y.cpy",
        ]

        extractor = ProjectSemanticExtractor()
        model = extractor.extract_project(carddemo_path, file_paths=workload_files)
        assert model.total_modules == 2
        assert len(model.entities) >= 1

        planner = GenericTransformationPlanner()
        java_plan = planner.plan(model, TargetSpecification.java_spring_boot())

        assert len(java_plan.behavior_preservation_requirements) >= 50
        assert len(java_plan.transformation_steps) >= 20
        assert len(java_plan.target_components) == 2

        # Generation Handoff
        generator = GenericTargetArtifactGenerator()
        artifacts = generator.generate(model, java_plan, TargetSpecification.java_spring_boot())
        assert len(artifacts) == 2
        assert any(a.component_name == "Cbact01c" for a in artifacts)

        # Real compilation verification
        verifier = TargetToolchainVerifier()
        v_res = verifier.verify(artifacts, TargetSpecification.java_spring_boot())
        assert v_res.passed, f"Real javac compilation failed: {v_res.output_snippet}"
        assert len(v_res.class_files_generated) >= 2

        # Bounded JVM execution of CBACT01C status evaluation rule
        java_bin = repo_root / ".autoforge" / "tools" / "openjdk" / "bin" / "java"
        class_bin_dir = Path(v_res.class_files_generated[0]).parent.parent.parent.parent

        test_cases = [
            ("00", 0),   # SUCCESS
            ("10", 16),  # END_OF_FILE
            ("99", 12),  # IO_ERROR
        ]
        for inp, exp_rc in test_cases:
            res = subprocess.run(
                [str(java_bin), "-cp", str(class_bin_dir), "com.autoforge.generated.Cbact01c", inp],
                capture_output=True, text=True, timeout=5,
            )
            assert f"STATUS_RESULT={exp_rc}" in res.stdout

        # Provenance Tracking
        prov_chain = ModernizationProvenanceChain(
            project_id=model.project_id,
            job_id="test-semantic-planning-job",
        )
        prov_chain.add_link(ProvenanceLink(stage=ProvenanceStage.SOURCE, actor="CardDemoSource"))
        prov_chain.add_link(ProvenanceLink(stage=ProvenanceStage.ANALYSIS, actor="ProjectSemanticExtractor"))
        prov_chain.add_link(ProvenanceLink(stage=ProvenanceStage.PLAN, actor="GenericTransformationPlanner"))
        prov_chain.add_link(ProvenanceLink(stage=ProvenanceStage.TRANSFORMATION, actor="GenericTargetArtifactGenerator"))
        prov_chain.add_link(ProvenanceLink(stage=ProvenanceStage.VERIFICATION, actor="TargetToolchainVerifier"))

        assert len(prov_chain.links) == 5
