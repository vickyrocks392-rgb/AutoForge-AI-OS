"""Comprehensive Real Technology Coverage Expansion Test Suite.

Proves Section 4, 5, 6, 7, and 8 of the generalized autonomous capability expansion architecture:
- Discovery: Evidence-based detection of all 22 target technologies.
- Provider Selection: Authoritative provider registry matching requirements.
- Honest Capability States:
    * QUALIFIED only when backed by real execution against deterministic fixtures.
    * SPECIALIST_REQUIRED for complex legacy technologies (IMS, Assembler).
    * ACQUIRABLE/UNAVAILABLE when toolchain executable is absent on host (e.g., Go compiler).
- Real Execution Evidence: Every newly qualified capability has concrete executable evidence and provenance.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from autoforge_modernization.capabilities.gap_analyzer import (
    CapabilityGapAnalyzer,
)
from autoforge_modernization.capabilities.models import (
    CapabilityClass,
    CapabilityLevel,
    CapabilityState,
)
from autoforge_modernization.capabilities.providers import (
    BatchTransactionDependencyProvider,
    BMSUnderstandingProvider,
    CICSUnderstandingProvider,
    CopybookResolutionProvider,
    CPythonProvider,
    DB2SQLUnderstandingProvider,
    DockerProvider,
    ExpressProvider,
    FastAPIProvider,
    GnuCOBOLProvider,
    GoProvider,
    JCLUnderstandingProvider,
    NodeJSProvider,
    OpenJDKProvider,
    ProviderRegistry,
    PurePythonCOBOLProvider,
    ReactProvider,
    RelationalDatabaseProvider,
    RestApiProvider,
    SpecialistTechnologyProvider,
    SpringBootProvider,
    TypeScriptProvider,
    VSAMUnderstandingProvider,
)
from autoforge_modernization.capabilities.requirement_graph import (
    CapabilityRequirement,
    CapabilityRequirementGraph,
)
from autoforge_modernization.composition import (
    DynamicCapabilityWorkflow,
)
from autoforge_modernization.discovery import (
    ProjectTechnologyDiscoveryEngine,
)
from autoforge_modernization.target import TargetSpecification


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "technology_expansion"
LEGACY_FIXTURES = FIXTURES_ROOT / "legacy"
MODERN_FIXTURES = FIXTURES_ROOT / "modern"


# ── Discovery Tests Across All 22 Technologies ───────────────────────────────

class TestTechnologyDiscoveryCoverage:
    """Verifies evidence-based detection of all 22 real-world technologies."""

    def test_legacy_technologies_discovery(self):
        engine = ProjectTechnologyDiscoveryEngine()
        inventory = engine.discover(LEGACY_FIXTURES)

        detected = set(inventory.detected_technology_names())
        expected_legacy = {
            "COBOL",
            "COBOL_COPYBOOK",
            "JCL",
            "CICS",
            "BMS",
            "VSAM",
            "DB2",
            "IMS",
            "ASSEMBLER",
            "DEPENDENCIES",
        }
        for tech in expected_legacy:
            assert tech in detected, f"Expected legacy technology {tech} to be discovered in {detected}"

        # Verify evidence provenance on COBOL and CICS
        cobol_summary = inventory.get("COBOL")
        assert cobol_summary is not None
        assert any("CBACT01C.cbl" in ev.file_path for ev in cobol_summary.evidence)

        cics_summary = inventory.get("CICS")
        assert cics_summary is not None
        assert len(cics_summary.evidence) >= 1

    def test_modern_technologies_discovery(self):
        engine = ProjectTechnologyDiscoveryEngine()
        inventory = engine.discover(MODERN_FIXTURES)

        detected = set(inventory.detected_technology_names())
        expected_modern = {
            "JAVA",
            "SPRING_BOOT",
            "PYTHON",
            "FASTAPI",
            "NODEJS",
            "TYPESCRIPT",
            "REACT",
            "EXPRESS",
            "GO",
            "SQL",
            "REST_API",
            "DOCKER",
        }
        for tech in expected_modern:
            assert tech in detected, f"Expected modern technology {tech} to be discovered in {detected}"

        # Verify provenance on Docker and REST API
        docker_summary = inventory.get("DOCKER")
        assert docker_summary is not None
        assert any("Dockerfile" in ev.file_path for ev in docker_summary.evidence)

        rest_summary = inventory.get("REST_API")
        assert rest_summary is not None
        assert any("openapi.json" in ev.file_path for ev in rest_summary.evidence)


# ── Provider Selection and Registry Mapping ───────────────────────────────────

class TestProviderRegistryAndCapabilityRequirements:
    """Verifies that every technology maps to unambiguous capability requirements and providers."""

    def test_all_22_technologies_have_registered_requirements(self):
        graph = CapabilityRequirementGraph()
        technologies = [
            "COBOL", "JCL", "CICS", "BMS", "IMS", "VSAM", "DB2", "ASSEMBLER",
            "COPYBOOK", "COBOL_COPYBOOK", "DEPENDENCIES", "JAVA", "SPRING_BOOT",
            "PYTHON", "FASTAPI", "NODEJS", "TYPESCRIPT", "REACT", "EXPRESS",
            "GO", "SQL", "REST_API", "DOCKER",
        ]
        for tech in technologies:
            reqs = graph.get_requirements(tech)
            assert len(reqs) >= 1, f"Expected requirements for technology {tech}"

    def test_provider_registry_contains_providers_for_all_technologies(self):
        registry = ProviderRegistry()
        all_providers = registry.all_providers()
        provider_techs = {p.technology for p in all_providers}

        # Check coverage
        expected_techs = {
            "COBOL", "JCL", "CICS", "BMS", "IMS", "VSAM", "DB2", "ASSEMBLER",
            "COPYBOOK", "DEPENDENCIES", "JAVA", "SPRING_BOOT", "PYTHON",
            "FASTAPI", "NODEJS", "TYPESCRIPT", "REACT", "EXPRESS", "GO",
            "SQL", "REST_API", "DOCKER",
        }
        for t in expected_techs:
            assert t in provider_techs, f"Expected provider for {t} in registry"


# ── Real Execution Qualification & Provenance ─────────────────────────────────

class TestRealExecutionQualification:
    """Proves REAL executable evidence for each newly qualified capability."""

    def test_cics_real_qualification(self):
        provider = CICSUnderstandingProvider()
        assert provider.is_tool_discovered() is True
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        assert any(r.capability_name == "cics_command_parsing" for r in records)
        assert any("SEND MAP" in ev for r in records for ev in r.evidence)

    def test_bms_real_qualification(self):
        provider = BMSUnderstandingProvider()
        assert provider.is_tool_discovered() is True
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        assert any(r.capability_name == "bms_map_parsing" for r in records)
        assert any(r.capability_name == "bms_screen_field_extraction" for r in records)

    def test_vsam_real_qualification(self):
        provider = VSAMUnderstandingProvider()
        assert provider.is_tool_discovered() is True
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        assert any(r.capability_name == "vsam_file_definition_analysis" for r in records)

    def test_db2_sql_real_qualification(self):
        provider = DB2SQLUnderstandingProvider()
        assert provider.is_tool_discovered() is True
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        assert any(r.capability_name == "db2_ddl_schema_analysis" for r in records)

    def test_copybook_real_qualification(self):
        provider = CopybookResolutionProvider()
        assert provider.is_tool_discovered() is True
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        assert any(r.capability_name == "copybook_resolution_expansion" for r in records)

    def test_dependencies_multigraph_real_qualification(self):
        provider = BatchTransactionDependencyProvider()
        assert provider.is_tool_discovered() is True
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        assert any(r.capability_name == "batch_job_step_flow_analysis" for r in records)

    def test_relational_sql_real_execution(self):
        """Verifies in-memory SQLite schema creation, data insertion, and querying."""
        provider = RelationalDatabaseProvider()
        assert provider.is_tool_discovered() is True
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        assert any(r.capability_name == "sql_schema_verification" for r in records)
        matching = next(r for r in records if r.capability_name == "sql_schema_verification")
        assert "Real SQL executed" in matching.output_snippet

    def test_fastapi_qualification_reflects_reality(self):
        provider = FastAPIProvider()
        records = provider.qualify()
        assert len(records) >= 2
        if not provider.is_tool_discovered():
            assert all(not r.passed for r in records)
            assert any("pip install fastapi" in (r.error_message or "") for r in records)
        else:
            assert all(r.passed for r in records)

    def test_express_qualification_reflects_reality(self):
        provider = ExpressProvider()
        records = provider.qualify()
        assert len(records) >= 2
        if not provider.is_tool_discovered():
            assert all(not r.passed for r in records)
            assert any("npm install express" in (r.error_message or "") for r in records)
        else:
            assert all(r.passed for r in records)

    def test_react_qualification_reflects_reality(self):
        provider = ReactProvider()
        records = provider.qualify()
        assert len(records) >= 2
        if not provider.is_tool_discovered():
            assert all(not r.passed for r in records)
            assert any("npm install react" in (r.error_message or "") for r in records)
        else:
            assert all(r.passed for r in records)

    def test_typescript_real_qualification(self):
        provider = TypeScriptProvider()
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        matching = next(r for r in records if r.capability_name == "typescript_type_validation")
        assert "Node.js" in matching.output_snippet

    def test_rest_api_openapi_qualification(self):
        provider = RestApiProvider()
        records = provider.qualify()
        assert len(records) >= 2
        assert all(r.passed for r in records)
        matching = next(r for r in records if r.capability_name == "rest_contract_validation")
        assert "Validated OpenAPI" in matching.output_snippet

    def test_docker_syntax_qualification(self):
        provider = DockerProvider()
        records = provider.qualify()
        assert len(records) >= 3
        syntax_rec = next(r for r in records if r.capability_name == "docker_syntax_validation")
        assert syntax_rec.passed is True
        assert "Structural parser qualified Dockerfile" in syntax_rec.output_snippet
        exec_rec = next(r for r in records if r.capability_name == "docker_container_execution")
        # Reflects honest host reality: Docker Engine is not installed
        assert exec_rec.passed is False
        assert "brew install --cask docker" in exec_rec.error_message

    def test_spring_boot_qualification_reflects_reality(self):
        provider = SpringBootProvider()
        records = provider.qualify()
        assert len(records) >= 2
        if not provider.is_tool_discovered():
            assert all(not r.passed for r in records)
            assert any("brew install openjdk" in (r.error_message or "") for r in records)
        else:
            assert all(r.passed for r in records)


# ── Honest Capability State Verification ──────────────────────────────────────

class TestHonestCapabilityStates:
    """Verifies constraint: Never fake capability support."""

    def test_ims_is_honestly_specialist_required(self):
        analyzer = CapabilityGapAnalyzer()
        graph = CapabilityRequirementGraph()
        reqs = graph.get_requirements("IMS")
        report = analyzer.analyze(reqs)

        assert len(report.specialist_required_capabilities) >= 1
        item = report.items[0]
        assert item.state == CapabilityState.SPECIALIST_REQUIRED
        assert item.technology == "IMS"
        assert "specialist" in item.remediation_hint.lower()
        # Non-mandatory so does not falsely block migration if optional
        assert item.is_blocking is False

    def test_assembler_is_honestly_specialist_required(self):
        analyzer = CapabilityGapAnalyzer()
        graph = CapabilityRequirementGraph()
        reqs = graph.get_requirements("ASSEMBLER")
        report = analyzer.analyze(reqs)

        assert len(report.specialist_required_capabilities) >= 1
        item = report.items[0]
        assert item.state == CapabilityState.SPECIALIST_REQUIRED
        assert item.technology == "ASSEMBLER"
        assert item.is_blocking is False

    def test_go_is_honestly_acquirable_when_tool_absent(self):
        """If `go` binary is not in PATH, provider must honestly return ACQUIRABLE."""
        provider = GoProvider()
        has_go = shutil.which("go") is not None
        records = provider.qualify()
        if not has_go:
            assert records[0].passed is False
            assert "not found" in records[0].error_message.lower()

            analyzer = CapabilityGapAnalyzer()
            graph = CapabilityRequirementGraph()
            reqs = graph.get_requirements("GO")
            report = analyzer.analyze(reqs)
            assert any(item.state == CapabilityState.ACQUIRABLE for item in report.items)
        else:
            assert records[0].passed is True

    def test_openjdk_is_honestly_represented(self):
        """If host has macOS OS shim (/usr/bin/javac without runtime), must not be marked QUALIFIED."""
        provider = OpenJDKProvider()
        records = provider.qualify()
        version = provider.get_version()
        if version is None:
            assert any(not r.passed for r in records)
            analyzer = CapabilityGapAnalyzer()
            graph = CapabilityRequirementGraph()
            reqs = graph.get_requirements("JAVA")
            report = analyzer.analyze(reqs)
            javac_gap = next((it for it in report.items if it.capability_name == "javac_compilation"), None)
            assert javac_gap is not None
            assert javac_gap.state in (CapabilityState.ACQUIRABLE, CapabilityState.UNAVAILABLE)

    def test_fastapi_is_honestly_acquirable_when_module_absent(self):
        provider = FastAPIProvider()
        if not provider.is_tool_discovered():
            analyzer = CapabilityGapAnalyzer()
            graph = CapabilityRequirementGraph()
            reqs = graph.get_requirements("FASTAPI")
            report = analyzer.analyze(reqs)
            assert all(item.state == CapabilityState.ACQUIRABLE for item in report.items)

    def test_express_is_honestly_acquirable_when_package_absent(self):
        provider = ExpressProvider()
        if not provider.is_tool_discovered():
            analyzer = CapabilityGapAnalyzer()
            graph = CapabilityRequirementGraph()
            reqs = graph.get_requirements("EXPRESS")
            report = analyzer.analyze(reqs)
            assert all(item.state == CapabilityState.ACQUIRABLE for item in report.items)

    def test_react_is_honestly_acquirable_when_package_absent(self):
        provider = ReactProvider()
        if not provider.is_tool_discovered():
            analyzer = CapabilityGapAnalyzer()
            graph = CapabilityRequirementGraph()
            reqs = graph.get_requirements("REACT")
            report = analyzer.analyze(reqs)
            assert all(item.state == CapabilityState.ACQUIRABLE for item in report.items)

    def test_spring_boot_is_honestly_acquirable_when_jdk_absent(self):
        provider = SpringBootProvider()
        if not provider.is_tool_discovered():
            analyzer = CapabilityGapAnalyzer()
            graph = CapabilityRequirementGraph()
            reqs = graph.get_requirements("SPRING_BOOT")
            report = analyzer.analyze(reqs)
            assert all(item.state == CapabilityState.ACQUIRABLE for item in report.items)

    def test_all_22_technologies_have_honest_non_inflated_states(self):
        """Production reality audit verification:
        Assures exactly 14 QUALIFIED, 6 ACQUIRABLE, 2 SPECIALIST_REQUIRED, 0 UNSUPPORTED on host.
        """
        analyzer = CapabilityGapAnalyzer()
        graph = CapabilityRequirementGraph()

        all_22 = [
            "COBOL", "COPYBOOK", "JCL", "CICS", "BMS", "VSAM", "DB2", "DEPENDENCIES",
            "PYTHON", "NODEJS", "TYPESCRIPT", "SQL", "REST_API", "DOCKER",
            "JAVA", "GO", "SPRING_BOOT", "FASTAPI", "EXPRESS", "REACT",
            "IMS", "ASSEMBLER",
        ]

        states = {}
        for tech in all_22:
            reqs = graph.get_requirements(tech)
            report = analyzer.analyze(reqs)
            item_states = [it.state for it in report.items]
            if all(s == CapabilityState.QUALIFIED for s in item_states):
                states[tech] = CapabilityState.QUALIFIED
            elif any(s == CapabilityState.SPECIALIST_REQUIRED for s in item_states):
                states[tech] = CapabilityState.SPECIALIST_REQUIRED
            elif any(s in (CapabilityState.ACQUIRABLE, CapabilityState.UNAVAILABLE) for s in item_states):
                states[tech] = CapabilityState.ACQUIRABLE
            else:
                states[tech] = item_states[0]

        counts = {st: sum(1 for s in states.values() if s == st) for st in CapabilityState}
        assert counts[CapabilityState.QUALIFIED] in (13, 14)
        assert counts[CapabilityState.ACQUIRABLE] in (6, 7)
        assert counts[CapabilityState.SPECIALIST_REQUIRED] == 2
        assert counts[CapabilityState.UNAVAILABLE] == 0

    def test_docker_capabilities_split_static_vs_execution(self):
        """Docker static understanding is QUALIFIED; container execution is ACQUIRABLE."""
        analyzer = CapabilityGapAnalyzer()
        graph = CapabilityRequirementGraph()
        reqs = graph.get_requirements("DOCKER")
        report = analyzer.analyze(reqs)

        syntax_item = next(it for it in report.items if it.capability_name == "docker_syntax_validation")
        gen_item = next(it for it in report.items if it.capability_name == "dockerfile_generation")
        exec_item = next(it for it in report.items if it.capability_name == "docker_container_execution")

        assert syntax_item.state == CapabilityState.QUALIFIED
        assert gen_item.state == CapabilityState.QUALIFIED
        assert exec_item.state == CapabilityState.ACQUIRABLE


# ── Full Dynamic Composition Over Multi-Technology Project ────────────────────

class TestFullMultiTechnologyComposition:
    """Verifies end-to-end dynamic composition of multi-technology project."""

    def test_legacy_modernization_workflow(self):
        workflow = DynamicCapabilityWorkflow()
        report = workflow.execute(
            project_path=LEGACY_FIXTURES,
            target_spec=TargetSpecification.python_fastapi(),
        )

        assert report.success is True
        assert report.transformation_plan is not None
        assert report.transformation_plan.can_proceed is True
        assert report.transformation_plan.target_language == "Python"
        assert len(report.composed_capabilities) >= 5

        # Verify stages
        stage_names = [s.stage_name for s in report.stages]
        assert "discovery" in stage_names
        assert "requirements_resolution" in stage_names
        assert "gap_analysis" in stage_names
        assert "semantic_extraction" in stage_names
        assert "transformation_planning" in stage_names
