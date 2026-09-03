"""Tests for Phase 18-G.2 Reconnaissance module."""
from __future__ import annotations
import pytest
from autoforge_modernization.reconnaissance import (
    FileCategory, FactConfidence, TechnologyKind, TechnologyCategory,
    ComparisonOutcome, ScannedFile, DetectedTechnology,
    ProjectCapabilityComparison, LegacyInventory, ProjectSizing,
    scan_repository, TechnologyDetector,
    ReconnaissanceEngine, run_reconnaissance,
)


class TestEnums:
    def test_file_category_values(self):
        assert FileCategory.SOURCE.value == "source"
        assert FileCategory.BUILD.value == "build"
        assert FileCategory.DEPLOY.value == "deploy"
        assert FileCategory.CONFIG.value == "config"
        assert FileCategory.DATA.value == "data"
        assert FileCategory.TEST.value == "test"
        assert FileCategory.DOC.value == "doc"
        assert FileCategory.GENERATED.value == "generated"
        assert FileCategory.BINARY.value == "binary"
        assert FileCategory.UNKNOWN.value == "unknown"

    def test_fact_confidence_values(self):
        assert FactConfidence.PROVEN.value == "proven"
        assert FactConfidence.HIGH.value == "high"
        assert FactConfidence.MEDIUM.value == "medium"
        assert FactConfidence.LOW.value == "low"
        assert FactConfidence.INFERRED.value == "inferred"
        assert FactConfidence.UNKNOWN.value == "unknown"

    def test_technology_kind_values(self):
        assert TechnologyKind.LANGUAGE.value == "language"
        assert TechnologyKind.FRAMEWORK.value == "framework"
        assert TechnologyKind.RUNTIME.value == "runtime"
        assert TechnologyKind.DATABASE.value == "database"
        assert TechnologyKind.TOOL.value == "tool"
        assert TechnologyKind.CONTAINER.value == "container"
        assert TechnologyKind.CI_CD.value == "ci_cd"
        assert TechnologyKind.INFRASTRUCTURE.value == "infrastructure"
        assert TechnologyKind.ORCHESTRATION.value == "orchestration"


class TestModels:
    def test_scanned_file_basic(self):
        sf = ScannedFile(path="/a/b/main.cbl", relative_path="main.cbl",
                          category=FileCategory.SOURCE, size_bytes=1024)
        assert sf.file_id is not None
        assert sf.path == "/a/b/main.cbl"
        assert sf.category == FileCategory.SOURCE
        assert sf.size_bytes == 1024
        assert sf.is_generated is False
        assert sf.is_test is False
        assert sf.confidence == FactConfidence.UNKNOWN

    def test_detected_technology_basic(self):
        tech = DetectedTechnology(name="cobol", kind=TechnologyKind.LANGUAGE,
                                category=TechnologyCategory.MAINFRAME,
                                confidence=FactConfidence.HIGH)
        assert tech.name == "cobol"
        assert tech.kind == TechnologyKind.LANGUAGE
        assert tech.category == TechnologyCategory.MAINFRAME
        assert tech.is_primary is False
        assert tech.version is None

    def test_capability_comparison_supported(self):
        c = ProjectCapabilityComparison(technology="java", outcome=ComparisonOutcome.SUPPORTED)
        assert c.outcome == ComparisonOutcome.SUPPORTED
        assert c.blocks_modernization is False

    def test_capability_comparison_tool_required_blocks(self):
        c = ProjectCapabilityComparison(technology="pl_i", outcome=ComparisonOutcome.TOOL_REQUIRED)
        assert c.blocks_modernization is True

    def test_capability_comparison_unsupported_blocks(self):
        # UNSUPPORTED technologies block modernization — model cannot handle them
        c = ProjectCapabilityComparison(technology="pl_i", outcome=ComparisonOutcome.UNSUPPORTED)
        assert c.blocks_modernization is True

class TestScanner:
    def test_scanner_finds_source_build_deploy(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "Dockerfile").write_text("FROM ubuntu")
        (tmp_path / "main.cbl").write_text("IDENTIFICATION DIVISION.")
        java_dir = tmp_path / "src" / "main" / "java"
        java_dir.mkdir(parents=True)
        (java_dir / "App.java").write_text("class App {}")

        result = scan_repository(str(tmp_path))

        source_files = [sf for sf in result.scanned_files if sf.category == FileCategory.SOURCE]
        assert len(source_files) >= 2
        build_files = [sf for sf in result.scanned_files if sf.category == FileCategory.BUILD]
        assert any("pom.xml" in sf.relative_path for sf in build_files)
        deploy_files = [sf for sf in result.scanned_files if sf.category == FileCategory.DEPLOY]
        assert any("Dockerfile" in sf.relative_path for sf in deploy_files)

    def test_scanner_detects_cobol_language(self, tmp_path):
        (tmp_path / "main.cbl").write_text("IDENTIFICATION DIVISION.")
        result = scan_repository(str(tmp_path))
        cobol_files = [sf for sf in result.scanned_files if sf.detected_language == "cobol"]
        assert len(cobol_files) >= 1

    def test_scanner_detects_technologies(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "Dockerfile").write_text("FROM ubuntu")
        (tmp_path / "application.yml").write_text("server: 8080")
        result = scan_repository(str(tmp_path))
        techs = result.project_metadata.detected_technologies
        assert "maven" in techs
        assert "docker" in techs
        assert "spring" in techs

    def test_scanner_marks_test_files(self, tmp_path):
        (tmp_path / "main.java").write_text("class Main {}")
        test_dir = tmp_path / "src" / "test" / "java"
        test_dir.mkdir(parents=True)
        (test_dir / "MainTest.java").write_text("class MainTest {}")
        result = scan_repository(str(tmp_path))
        test_files = [sf for sf in result.scanned_files if sf.is_test]
        assert len(test_files) >= 1

    def test_scanner_marks_generated_files(self, tmp_path):
        (tmp_path / "main.java").write_text("class Main {}")
        gen_dir = tmp_path / "build" / "generated"
        gen_dir.mkdir(parents=True)
        (gen_dir / "Generated.java").write_text("// auto-generated")
        result = scan_repository(str(tmp_path))
    def test_scan_result_summary(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        result = scan_repository(str(tmp_path))
        summary = result.to_summary()
        assert "scan_id" in summary
        assert summary["files_total"] >= 1


class TestTechnologyDetector:
    def test_detects_from_build_technologies(self):
        files = [ScannedFile(path="/a/pom.xml", relative_path="pom.xml",
                             category=FileCategory.BUILD,
                             detected_technologies=["maven"])]
        detector = TechnologyDetector(scanned_files=files)
        detected = detector.detect_all()
        assert "maven" in {t.name for t in detected}

    def test_detects_language_from_source(self):
        files = [ScannedFile(path="/a/main.cbl", relative_path="main.cbl",
                             category=FileCategory.SOURCE,
                             detected_language="cobol")]
        detector = TechnologyDetector(scanned_files=files)
        detected = detector.detect_all()
        assert "cobol" in {t.name for t in detected}

    def test_primary_language_detection(self):
        files = [
            ScannedFile(path="/a/a.java", relative_path="a.java",
                        category=FileCategory.SOURCE, detected_language="java"),
            ScannedFile(path="/a/b.java", relative_path="b.java",
                        category=FileCategory.SOURCE, detected_language="java"),
            ScannedFile(path="/a/c.cbl", relative_path="c.cbl",
                        category=FileCategory.SOURCE, detected_language="cobol"),
        ]
        detector = TechnologyDetector(scanned_files=files)
        detected = detector.detect_all()
        primary = [t for t in detected if t.is_primary]
        assert len(primary) == 1

    def test_comparison_supported(self):
        detected = [DetectedTechnology(name="java", kind=TechnologyKind.LANGUAGE,
                                       category=TechnologyCategory.JAVA_ENTERPRISE,
                                       confidence=FactConfidence.HIGH)]
        detector = TechnologyDetector()
        comparisons = detector.compare_capabilities(detected, {"java": "full"})
        assert comparisons[0].outcome == ComparisonOutcome.SUPPORTED
        assert comparisons[0].capability_level == "full"

    def test_comparison_partially_supported(self):
        detected = [DetectedTechnology(name="cobol", kind=TechnologyKind.LANGUAGE,
                                       category=TechnologyCategory.MAINFRAME,
                                       confidence=FactConfidence.MEDIUM)]
        detector = TechnologyDetector()
        comparisons = detector.compare_capabilities(detected, {"cobol": "partial"})
        assert comparisons[0].outcome == ComparisonOutcome.PARTIALLY_SUPPORTED

    def test_comparison_tool_required_blocks(self):
        detected = [DetectedTechnology(name="spring", kind=TechnologyKind.FRAMEWORK,
                                       category=TechnologyCategory.JAVA_ENTERPRISE,
                                       confidence=FactConfidence.MEDIUM)]
        detector = TechnologyDetector()
        comparisons = detector.compare_capabilities(detected, {"spring": "tool_required"})
        assert comparisons[0].outcome == ComparisonOutcome.TOOL_REQUIRED
        assert comparisons[0].blocks_modernization is True


class TestReconnaissanceEngine:
    def test_engine_initial_state(self, tmp_path):
        engine = ReconnaissanceEngine(str(tmp_path), job_id="test")
        assert engine.state.is_running is False
        assert engine.state.current_operation == ""

    def test_engine_full_pipeline(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "Dockerfile").write_text("FROM java:8")
        (tmp_path / "main.cbl").write_text("ID DIVISION.")
        java_dir = tmp_path / "src" / "main" / "java"
        java_dir.mkdir(parents=True)
        (java_dir / "App.java").write_text("class App {}")

        inventory = run_reconnaissance(
            str(tmp_path), job_id="test",
            capability_registry={"java": "full", "maven": "full", "docker": "full"},
        )

        assert inventory.inventory_id is not None
        assert inventory.project_path == str(tmp_path)
        assert len(inventory.scanned_files) >= 3
        assert inventory.sizing is not None
        assert inventory.sizing.total_physical_loc >= 1

    def test_engine_operations_completed(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        engine = ReconnaissanceEngine(str(tmp_path))
        engine.run()
        assert len(engine.state.operations_completed) == 5
        assert "scanning_repository" in engine.state.operations_completed
        assert "detecting_technologies" in engine.state.operations_completed
        assert "comparing_capabilities" in engine.state.operations_completed
        assert "sizing" in engine.state.operations_completed
        assert "assembling_inventory" in engine.state.operations_completed

    def test_engine_events_recorded(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        engine = ReconnaissanceEngine(str(tmp_path))
        engine.run()
        assert len(engine.events) >= 3

    def test_engine_state_after_run(self, tmp_path):
        (tmp_path / "Makefile").write_text("all:")
        engine = ReconnaissanceEngine(str(tmp_path), job_id="state-test")
        engine.run()
        assert engine.state.is_running is False
        assert engine.state.files_scanned >= 1

    def test_scanner_empty_directory(self, tmp_path):
        result = scan_repository(str(tmp_path))
        assert len(result.scanned_files) == 0
        assert result.directories_scanned >= 1

    def test_scanner_skips_git(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("git config")
        (tmp_path / "main.java").write_text("class Main {}")
        result = scan_repository(str(tmp_path))
        paths = [sf.relative_path for sf in result.scanned_files]
        assert not any(".git" in p for p in paths)

    def test_scanner_metadata(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        (tmp_path / "Dockerfile").write_text("FROM ubuntu")
        result = scan_repository(str(tmp_path))
        meta = result.project_metadata
        assert meta is not None
        assert meta.project_path == str(tmp_path)
        assert "pom.xml" in meta.manifest_files
        assert "Dockerfile" in meta.manifest_files

    def test_scan_result_summary(self, tmp_path):
        (tmp_path / "pom.xml").write_text("<project/>")
        result = scan_repository(str(tmp_path))
        summary = result.to_summary()
        assert "scan_id" in summary
        assert summary["files_total"] >= 1
    def test_capability_comparison_model_required_blocks(self):
        c = ProjectCapabilityComparison(technology="pl_i", outcome=ComparisonOutcome.MODEL_REQUIRED)
        assert c.blocks_modernization is True

    def test_legacy_inventory_empty(self, tmp_path):
        inv = LegacyInventory(project_path=str(tmp_path))
        assert inv.inventory_id is not None
        assert inv.project_path == str(tmp_path)
        assert len(inv.scanned_files) == 0
        assert inv.overall_confidence == FactConfidence.UNKNOWN

    def test_legacy_inventory_with_sizing(self, tmp_path):
        sizing = ProjectSizing(total_physical_loc=50000, total_files=100,
                              loc_by_language={"cobol": 40000, "jcl": 10000})
        inv = LegacyInventory(project_path=str(tmp_path), sizing=sizing)
        assert inv.sizing is not None
        assert inv.sizing.total_physical_loc == 50000
        assert inv.sizing.loc_by_language["cobol"] == 40000

    def test_project_sizing_defaults(self):
        sizing = ProjectSizing()
        assert sizing.total_physical_loc == 0
        assert sizing.total_files == 0
        assert sizing.confidence == FactConfidence.UNKNOWN
        assert TechnologyKind.DATABASE.value == "database"
        assert TechnologyKind.TOOL.value == "tool"
        assert TechnologyKind.CONTAINER.value == "container"
        assert TechnologyKind.CI_CD.value == "ci_cd"
        assert TechnologyKind.INFRASTRUCTURE.value == "infrastructure"
        assert TechnologyKind.ORCHESTRATION.value == "orchestration"

    def test_comparison_outcome_values(self):
        assert ComparisonOutcome.SUPPORTED.value == "supported"
        assert ComparisonOutcome.PARTIALLY_SUPPORTED.value == "partially_supported"
        assert ComparisonOutcome.TOOL_REQUIRED.value == "tool_required"
        assert ComparisonOutcome.ENVIRONMENT_REQUIRED.value == "environment_required"
        assert ComparisonOutcome.MODEL_REQUIRED.value == "model_required"
        assert ComparisonOutcome.UNSUPPORTED.value == "unsupported"
        assert ComparisonOutcome.UNKNOWN.value == "unknown"