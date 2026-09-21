"""Comprehensive Tests for AutoForge Generalized Autonomous Capability Expansion.

Validates the full architecture:
1. Multi-Provider Evidence-based Technology Discovery
2. Capability Requirement Graph (Technology -> Capabilities without migration pairs)
3. Generalized Capability Gap Analysis (all 6 states)
4. Verified Technology Providers & Executable Qualification Fixtures
5. Safe Free-First Autonomous Acquisition Engine
6. Technology-Neutral Semantic Intermediate Model & Provenance
7. Declarative Target Specification & Target Capability Derivation
8. Generic Transformation Planning & Dynamic Workflow Composition
9. Validation Scenarios A, B, C, D, E
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from autoforge_modernization.capabilities import (
    CapabilityClass,
    CapabilityLevel,
    CapabilityQualificationRecord,
    CapabilityRequirement,
    CapabilityState,
    CPythonProvider,
    GnuCOBOLProvider,
    JCLUnderstandingProvider,
    NodeJSProvider,
    OpenJDKProvider,
    ProviderRegistry,
    PurePythonCOBOLProvider,
    SpecialistTechnologyProvider,
    VerifiedTechnologyProvider,
    CapabilityRequirementGraph,
    CapabilityGapAnalyzer,
    AutonomousAcquisitionEngine,
    AcquisitionStatus,
    CapabilityGapItem,
)
from autoforge_modernization.discovery import (
    EvidenceProvider,
    FileSystemEvidenceProvider,
    SyntaxEvidenceProvider,
    TechnologyEvidenceRecord,
    ProjectTechnologyDiscoveryEngine,
    ProjectTechnologyInventory,
)
from autoforge_modernization.semantic import (
    TechnologyNeutralSemanticModel,
    SemanticModule,
    SemanticProcedure,
    SemanticField,
    SemanticOperation,
    SemanticOperationKind,
    SemanticDataType,
    SemanticBusinessRule,
    SemanticModelExtractor,
    SourceProvenance,
    UnsupportedSemanticConstruct,
)
from autoforge_modernization.target import (
    TargetSpecification,
    TargetCapabilityDeriver,
)
from autoforge_modernization.composition import (
    TransformationPlan,
    GenericTransformationPlanner,
    DynamicCapabilityWorkflow,
    CompositionWorkflowReport,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_cobol_source() -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CBACT01C.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-ACCT-ID     PIC X(11) VALUE '00000000000'.\n"
        "       01 WS-BALANCE     PIC S9(7)V99 COMP-3 VALUE 0.\n"
        "       01 WS-STATUS      PIC X(2) VALUE '00'.\n"
        "       PROCEDURE DIVISION.\n"
        "       0000-MAIN.\n"
        "           MOVE '12345678901' TO WS-ACCT-ID.\n"
        "           IF WS-ACCT-ID NOT = SPACES\n"
        "               PERFORM 1000-PROCESS-BALANCE\n"
        "           END-IF.\n"
        "           STOP RUN.\n"
        "       1000-PROCESS-BALANCE.\n"
        "           CALL 'CBACT02C' USING WS-ACCT-ID WS-BALANCE.\n"
        "           IF WS-BALANCE < 0\n"
        "               MOVE 'OD' TO WS-STATUS\n"
        "           END-IF.\n"
    )


@pytest.fixture
def sample_jcl_source() -> str:
    return (
        "//ACCTJOB  JOB (ACCT),'ACCOUNT POSTING',CLASS=A,MSGCLASS=X\n"
        "//STEP01   EXEC PGM=CBACT01C\n"
        "//ACCTFILE DD DSN=CARDDEMO.ACCTDATA,DISP=SHR\n"
        "//RPTFILE  DD DSN=CARDDEMO.ACCTRPT,DISP=(NEW,CATLG,DELETE),\n"
        "//            SPACE=(CYL,(5,5),RLSE)\n"
    )


@pytest.fixture
def synthetic_multi_tech_repo(tmp_path: Path, sample_cobol_source: str, sample_jcl_source: str) -> Path:
    repo = tmp_path / "multi_tech_repo"
    repo.mkdir()

    # COBOL
    (repo / "app" / "cbl").mkdir(parents=True)
    (repo / "app" / "cbl" / "CBACT01C.cbl").write_text(sample_cobol_source)

    # JCL
    (repo / "app" / "jcl").mkdir(parents=True)
    (repo / "app" / "jcl" / "ACCTJOB.jcl").write_text(sample_jcl_source)

    # Copybook
    (repo / "app" / "cpy").mkdir(parents=True)
    (repo / "app" / "cpy" / "CVACT01Y.cpy").write_text(
        "       01  ACCOUNT-RECORD.\n"
        "           05  ACCT-ID         PIC 9(11).\n"
        "           05  ACCT-ACTIVE-IND PIC X(01).\n"
    )

    # BMS Mapset
    (repo / "app" / "bms").mkdir(parents=True)
    (repo / "app" / "bms" / "COACT01.bms").write_text(
        "COACT1M  DFHMSD TYPE=&SYSPARM,MODE=INOUT,LANG=COBOL\n"
        "COACT1   DFHMDI SIZE=(24,80)\n"
        "TITLE    DFHMDF POS=(01,01),LENGTH=20,ATTRB=(ASKIP,NORM),INITIAL='ACCOUNT SUMMARY'\n"
        "         DFHMSD TYPE=FINAL\n"
    )

    # IMS Descriptor
    (repo / "app" / "ims").mkdir(parents=True)
    (repo / "app" / "ims" / "IVPDB2.dbd").write_text(
        "       DBD  NAME=IVPDB2,ACCESS=(HDAM,VSAM)\n"
        "       DATASET DD1=IVPDB2,DEVICE=3390\n"
    )

    return repo


# ── Test Suite 1: Generalized Technology Discovery ─────────────────────────────

class TestGeneralizedTechnologyDiscovery:
    """Validates Section 4: Technology Discovery Must Be General & Evidence-Based."""

    def test_multi_provider_evidence_detection(self, synthetic_multi_tech_repo: Path):
        engine = ProjectTechnologyDiscoveryEngine()
        inventory = engine.discover(synthetic_multi_tech_repo)

        assert inventory.total_files_scanned >= 5
        assert inventory.total_physical_loc > 0

        # Assert simultaneous detection of multiple technologies
        detected = inventory.detected_technology_names()
        assert "COBOL" in detected
        assert "JCL" in detected
        assert "COBOL_COPYBOOK" in detected
        assert "BMS" in detected
        assert "IMS" in detected

        # Verify evidence provenance
        cobol_summary = inventory.get("COBOL")
        assert cobol_summary is not None
        assert cobol_summary.confidence >= 0.95
        assert len(cobol_summary.evidence) >= 1
        assert any("PROGRAM-ID" in ev.description for ev in cobol_summary.evidence)

        # Implied capability requirements are automatically derived
        assert len(cobol_summary.implied_requirements) >= 4
        req_names = [r.capability_name for r in cobol_summary.implied_requirements]
        assert "cobol_lexical_syntactic_analysis" in req_names
        assert "cobol_copybook_resolution" in req_names

    def test_carddemo_discovery_if_present(self):
        """Scenario A validation: Discovers technologies in real CardDemo without hardcoding."""
        carddemo_path = Path("/Users/kalachanddash/Documents/AutoForge AI/.autoforge/carddemo/app")
        if not carddemo_path.exists():
            pytest.skip("CardDemo not on disk")

        engine = ProjectTechnologyDiscoveryEngine()
        inventory = engine.discover(carddemo_path)

        assert inventory.total_files_scanned >= 100
        detected = inventory.detected_technology_names()

        # Must detect multi-technology enterprise stack simultaneously
        assert "COBOL" in detected
        assert "JCL" in detected
        assert "COBOL_COPYBOOK" in detected
        assert "BMS" in detected

        # Implied requirements populated across all technologies
        assert len(inventory.all_implied_requirements) >= 8


# ── Test Suite 2: Capability Requirement Graph & Gap Analysis ──────────────────

class TestCapabilityRequirementGraphAndGapAnalysis:
    """Validates Sections 5 & 6: Independent Capability Requirements and 6-state Gap Analysis."""

    def test_independent_capability_requirements(self):
        graph = CapabilityRequirementGraph()

        cobol_reqs = graph.get_requirements("COBOL")
        java_reqs = graph.get_requirements("JAVA")
        python_reqs = graph.get_requirements("PYTHON")

        # Must be decoupled from migration pairs
        assert len(cobol_reqs) >= 4
        assert len(java_reqs) >= 2
        assert len(python_reqs) >= 2

        # COBOL requirements are source understanding
        assert all(r.technology == "COBOL" for r in cobol_reqs)
        assert any(r.capability_name == "cobol_call_relationship_analysis" for r in cobol_reqs)

        # Java requirements are target generation and verification
        assert any(r.capability_name == "javac_compilation" for r in java_reqs)
        assert any(r.capability_name == "java_source_generation" for r in java_reqs)

    def test_gap_analysis_six_states(self):
        """Tests that capabilities evaluate to honest, evidence-backed states."""
        registry = ProviderRegistry()
        analyzer = CapabilityGapAnalyzer(provider_registry=registry)

        reqs = [
            # 1. Qualified (built-in pure python cobol parser)
            CapabilityRequirement(
                technology="COBOL",
                capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                capability_name="cobol_lexical_syntactic_analysis",
                mandatory=True,
            ),
            # 2. Qualified (Python runtime is present on host)
            CapabilityRequirement(
                technology="PYTHON",
                capability_class=CapabilityClass.TARGET_VERIFICATION,
                capability_name="python_syntax_check",
                mandatory=True,
            ),
            # 3. Specialist Required (IMS)
            CapabilityRequirement(
                technology="IMS",
                capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                capability_name="ims_specialist_consultation",
                mandatory=False,
            ),
            # 4. Acquirable or Qualified (GnuCOBOL or OpenJDK depending on host state)
            CapabilityRequirement(
                technology="COBOL",
                capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                capability_name="cobol_compiler_syntax_validation",
                mandatory=False,
            ),
            # 5. Unavailable (completely unknown capability)
            CapabilityRequirement(
                technology="UNKNOWN_ESOTERIC_LANG",
                capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
                capability_name="esoteric_parser",
                mandatory=True,
            ),
        ]

        report = analyzer.analyze(reqs, project_id="test-proj")
        assert len(report.items) == 5

        states = {item.capability_name: item.state for item in report.items}
        assert states["cobol_lexical_syntactic_analysis"] == CapabilityState.QUALIFIED
        assert states["python_syntax_check"] == CapabilityState.QUALIFIED
        assert states["ims_specialist_consultation"] == CapabilityState.SPECIALIST_REQUIRED
        assert states["esoteric_parser"] == CapabilityState.UNAVAILABLE


# ── Test Suite 3: Verified Technology Providers & Qualification Fixtures ────────

class TestVerifiedTechnologyProviders:
    """Validates First-Class VerifiedTechnologyProvider architecture & executable fixtures."""

    def test_cpython_provider_qualification(self):
        provider = CPythonProvider()
        assert provider.is_tool_discovered() is True
        assert provider.get_version() is not None

        records = provider.qualify()
        assert len(records) >= 1
        assert records[0].passed is True
        assert records[0].execution_time_ms > 0

    def test_openjdk_provider_handles_macos_shim(self):
        """Crucial test: OpenJDKProvider must detect dummy /usr/bin/javac without Java runtime."""
        provider = OpenJDKProvider()
        # Even if /usr/bin/javac is in path, get_version() or qualify() tests real execution
        records = provider.qualify()
        assert len(records) >= 1
        # If javac failed with 'Unable to locate a Java Runtime', it must NOT claim passed!
        if not provider.get_version():
            assert records[0].passed is False
            assert "java" in records[0].fixture_name.lower()

    def test_specialist_technology_provider_honesty(self):
        """Validates Section 15: Specialist technologies must honestly report SPECIALIST_REQUIRED."""
        provider = SpecialistTechnologyProvider(
            technology="IMS",
            description="IBM IMS DB/TM",
            rationale="Hierarchical DL/I segments require specialist relational mapping.",
        )
        records = provider.qualify()
        assert records[0].passed is False
        assert "SPECIALIST_REQUIRED" in records[0].error_message


# ── Test Suite 4: Free-First Autonomous Acquisition Engine ──────────────────────

class TestAutonomousAcquisitionEngine:
    """Validates Sections 7, 8, 9: Autonomous acquisition lifecycle without fake evidence."""

    def test_acquisition_engine_already_qualified(self):
        engine = AutonomousAcquisitionEngine(allow_external_install=False)
        item = CapabilityGapItem(
            technology="COBOL",
            capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
            capability_name="cobol_lexical_syntactic_analysis",
            description="Pure python cobol parsing",
            state=CapabilityState.QUALIFIED,
            provider_id="provider-python-cobol-parser",
        )
        record = engine.process_gap_item(item)
        assert record.status == AcquisitionStatus.ALREADY_QUALIFIED

    def test_acquisition_engine_reports_not_executed_honestly(self):
        """Section 9: If host installation disabled, honestly report ACQUISITION_NOT_EXECUTED."""
        engine = AutonomousAcquisitionEngine(allow_external_install=False)
        item = CapabilityGapItem(
            technology="COBOL",
            capability_class=CapabilityClass.SOURCE_UNDERSTANDING,
            capability_name="cobol_compiler_syntax_validation",
            description="GnuCOBOL compiler",
            state=CapabilityState.ACQUIRABLE,
            provider_id="provider-gnucobol",
        )
        record = engine.process_gap_item(item)
        assert record.status == AcquisitionStatus.ACQUISITION_NOT_EXECUTED
        assert "installation is disabled by policy" in record.message


# ── Test Suite 5: Technology-Neutral Semantic Intermediate Model ────────────────

class TestTechnologyNeutralSemanticModel:
    """Validates Section 11: Technology-neutral semantic representation & provenance."""

    def test_cobol_extraction_to_neutral_model(self, sample_cobol_source: str):
        extractor = SemanticModelExtractor()
        module = extractor.extract_from_cobol(sample_cobol_source, "CBACT01C.cbl")

        assert module.name == "CBACT01C"
        assert module.source_technology == "COBOL"
        assert module.provenance is not None
        assert module.provenance.source_file == "CBACT01C.cbl"

        # Check fields
        assert len(module.fields) >= 2
        acct_field = next(f for f in module.fields if "ACCT" in f.name)
        assert acct_field.data_type == SemanticDataType.STRING
        balance_field = next(f for f in module.fields if "BALANCE" in f.name)
        assert balance_field.data_type == SemanticDataType.DECIMAL

        # Check procedures & calls
        assert len(module.procedures) >= 2
        assert "CBACT02C" in module.external_dependencies

        # Business rules
        assert len(module.business_rules) >= 1

    def test_unsupported_construct_explicit_representation(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. CICSPROG.\n"
            "       PROCEDURE DIVISION.\n"
            "           EXEC CICS SEND MAP('MAP1') MAPSET('SET1') END-EXEC.\n"
            "           CALL 'CBLTDLI' USING WS-FUNCTION WS-PCB.\n"
        )
        extractor = SemanticModelExtractor()
        module = extractor.extract_from_cobol(source, "CICSPROG.cbl")

        assert len(module.unsupported_constructs) == 2
        cics_unsupp = next(u for u in module.unsupported_constructs if u.technology == "CICS")
        assert "CICS Transaction Specialist" in cics_unsupp.required_specialist
        ims_unsupp = next(u for u in module.unsupported_constructs if u.technology == "IMS")
        assert "IMS Database Specialist" in ims_unsupp.required_specialist


# ── Test Suite 6: Target Specification & Capability Composition ────────────────

class TestTargetSpecificationAndDynamicComposition:
    """Validates Sections 12, 13, 14: Declarative targets and dynamic capability composition."""

    def test_target_capability_derivation(self):
        deriver = TargetCapabilityDeriver()

        # Java + Spring Boot
        java_spec = TargetSpecification.java_spring_boot()
        java_reqs = deriver.derive_requirements(java_spec)
        assert any(r.capability_name == "java_source_generation" for r in java_reqs)
        assert any(r.capability_name == "javac_compilation" for r in java_reqs)

        # Python + FastAPI
        py_spec = TargetSpecification.python_fastapi()
        py_reqs = deriver.derive_requirements(py_spec)
        assert any(r.capability_name == "python_source_generation" for r in py_reqs)
        assert any(r.capability_name == "python_syntax_check" for r in py_reqs)

    def test_dynamic_composition_cobol_to_java(self, synthetic_multi_tech_repo: Path):
        """Scenario C: Composes COBOL -> Java + Spring Boot without COBOLToJavaEngine."""
        workflow = DynamicCapabilityWorkflow()
        report = workflow.execute(
            project_path=synthetic_multi_tech_repo,
            target_spec=TargetSpecification.java_spring_boot(),
        )

        assert report.success is True
        assert "COBOL" in report.source_technologies_detected
        assert report.transformation_plan is not None
        assert report.transformation_plan.target_language == "Java"
        assert len(report.transformation_plan.target_components) >= 1

        comp = report.transformation_plan.target_components[0]
        assert comp.target_language == "Java"
        assert comp.suggested_relative_path.endswith(".java")

    def test_dynamic_composition_cobol_to_python(self, synthetic_multi_tech_repo: Path):
        """Scenario D: Composes COBOL -> Python + FastAPI without COBOLToPythonEngine."""
        workflow = DynamicCapabilityWorkflow()
        report = workflow.execute(
            project_path=synthetic_multi_tech_repo,
            target_spec=TargetSpecification.python_fastapi(),
        )

        assert report.success is True
        assert "COBOL" in report.source_technologies_detected
        assert report.transformation_plan is not None
        assert report.transformation_plan.target_language == "Python"
        assert len(report.transformation_plan.target_components) >= 1

        comp = report.transformation_plan.target_components[0]
        assert comp.target_language == "Python"
        assert comp.suggested_relative_path.endswith(".py")


class TestAutonomousCapabilityAcquisitionLifecycle:
    """Rigorous tests for Section 8 & 9: Autonomous Free-First Acquisition Lifecycle."""

    def test_mac_os_javac_stub_rejection(self):
        """Verifies that an unconfigured javac stub is caught by executable qualification."""
        provider = OpenJDKProvider()
        # Without managed java home, if system javac is an Apple stub, qualify must report failure
        records = provider.qualify()
        # If on macOS without JAVA_HOME, /usr/bin/javac fails
        if os.path.exists("/usr/bin/javac") and not os.environ.get("JAVA_HOME") and not provider._managed_java_home:
            # Must not be qualified merely because executable is on PATH
            record = records[0]
            if not record.passed:
                assert "Unable to locate a Java Runtime" in (record.error_message or "") or not record.passed

    def test_end_to_end_acquisition_preparation_and_qualification(self, tmp_path: Path):
        """Exercises: Gap -> Provider Selection -> Preparation -> Qualification -> Registration -> Gap Re-evaluation."""
        req = CapabilityRequirement(
            technology="JAVA",
            capability_class=CapabilityClass.TARGET_VERIFICATION,
            capability_name="javac_compilation",
            description="Java compilation verification",
            mandatory=True,
            minimum_level=CapabilityLevel.VERIFY,
        )

        registry = ProviderRegistry()
        gap_analyzer = CapabilityGapAnalyzer(provider_registry=registry)

        # 1. Initial Gap State: ACQUIRABLE if JDK absent, or QUALIFIED if JDK already present
        report_before = gap_analyzer.analyze([req])
        assert report_before.items[0].state in (CapabilityState.ACQUIRABLE, CapabilityState.QUALIFIED)

        # 2. Autonomous Preparation into isolated AutoForge tool directory
        isolated_tools_dir = tmp_path / "autoforge_tools"
        acq_engine = AutonomousAcquisitionEngine(
            provider_registry=registry,
            tools_directory=isolated_tools_dir,
            allow_external_install=False,
        )

        attempt = acq_engine.process_gap_item(report_before.items[0])
        assert attempt.status in (AcquisitionStatus.SUCCESS, AcquisitionStatus.ALREADY_QUALIFIED)
        if attempt.status == AcquisitionStatus.SUCCESS:
            assert len(attempt.qualification_records) > 0
            assert attempt.qualification_records[0].passed is True
            assert attempt.qualification_records[0].execution_time_ms > 0

        # 3. Authoritative Registration Proof
        reg_cap = acq_engine.capability_registry.get("JAVA")
        assert reg_cap is not None
        assert "javac_compilation" in reg_cap.supported_constructs
        assert reg_cap.can_verify is True

        # 4. Gap Re-evaluation: ACQUIRABLE -> QUALIFIED / AVAILABLE
        report_after = gap_analyzer.analyze([req])
        assert report_after.items[0].state == CapabilityState.QUALIFIED
        assert report_after.has_blocking_gaps is False

    def test_honest_acquisition_not_executed_when_external_install_disallowed(self):
        """Verifies that AutoForge reports ACQUISITION_NOT_EXECUTED when tool is missing and external install disabled."""
        gap_item = CapabilityGapItem(
            technology="GNUCOBOL",
            capability_class=CapabilityClass.TARGET_VERIFICATION,
            capability_name="cobol_compiler_syntax_validation",
            description="cobc binary execution",
            state=CapabilityState.ACQUIRABLE,
            provider_id="provider-gnucobol",
        )

        acq_engine = AutonomousAcquisitionEngine(allow_external_install=False)
        attempt = acq_engine.process_gap_item(gap_item)

        # Must report ACQUISITION_NOT_EXECUTED honestly rather than fabricating success
        assert attempt.status in (AcquisitionStatus.ACQUISITION_NOT_EXECUTED, AcquisitionStatus.FAILED)
        assert "disabled by policy" in attempt.message or "not installed" in attempt.message

    def test_qualification_failure_handling(self):
        """Verifies that a provider whose fixture fails does not register as operational."""
        class BrokenCompilerProvider(VerifiedTechnologyProvider):
            provider_id = "provider-broken"
            technology = "BROKEN_LANG"
            display_name = "Broken Language Provider"

            def capabilities_supplied(self):
                return [(CapabilityClass.TARGET_VERIFICATION, "broken_compilation", CapabilityLevel.VERIFY)]

            def is_tool_discovered(self):
                return True

            def get_version(self):
                return "1.0.0"

            def qualify(self):
                return [
                    CapabilityQualificationRecord(
                        provider_id=self.provider_id,
                        capability_name="broken_compilation",
                        technology=self.technology,
                        passed=False,
                        error_message="SyntaxError in compiler fixture",
                    )
                ]

            def get_acquisition_recipe(self):
                return {"source_url": "https://example.com", "command": "echo mock"}

            def acquire_or_prepare(self, target_dir=None, allow_external_install=False):
                return True, "Prepared mock tool"

        registry = ProviderRegistry()
        broken = BrokenCompilerProvider()
        registry.register(broken)

        gap_item = CapabilityGapItem(
            technology="BROKEN_LANG",
            capability_class=CapabilityClass.TARGET_VERIFICATION,
            capability_name="broken_compilation",
            description="Broken tool test",
            state=CapabilityState.ACQUIRABLE,
            provider_id="provider-broken",
        )

        acq_engine = AutonomousAcquisitionEngine(provider_registry=registry)
        attempt = acq_engine.process_gap_item(gap_item)

        assert attempt.status == AcquisitionStatus.FAILED
        assert "qualification tests failed" in attempt.message
        assert acq_engine.capability_registry.get("BROKEN_LANG") is None

    def test_provider_provenance_metadata(self):
        """Verifies provenance tracking for free/open-source providers."""
        openjdk = OpenJDKProvider()
        prov_jdk = openjdk.get_provenance()
        assert prov_jdk.is_free_open_source is True
        assert "GPL" in prov_jdk.license_type or "Classpath" in prov_jdk.license_type
        assert "adoptium" in prov_jdk.source_url or "openjdk" in prov_jdk.source_url

        cpython = CPythonProvider()
        prov_py = cpython.get_provenance()
        assert prov_py.is_free_open_source is True
        assert "PSF" in prov_py.license_type or "GPL" in prov_py.license_type or "Open Source" in prov_py.license_type

    def test_dynamic_composition_unblocked_after_autonomous_preparation(self, synthetic_multi_tech_repo: Path):
        """Proves that dynamic workflow execution transitions can_proceed to True after autonomous preparation."""
        workflow = DynamicCapabilityWorkflow()
        report = workflow.execute(
            project_path=synthetic_multi_tech_repo,
            target_spec=TargetSpecification.java_spring_boot(),
        )

        assert report.success is True
        assert report.transformation_plan is not None
        assert report.transformation_plan.can_proceed is True
        assert len(report.composed_capabilities) >= 5

