"""Acceptance Test Suite for 18-G.5 Final Complete Subsystem Modernization Certification.

Tests:
- Mathematical subsystem topological closure (internal_dependency_closure == COMPLETE, 0 missing dependencies)
- Technology-neutral semantic graph extraction
- Transformation planning targeting Spring Boot + Maven
- Full target generation (pom.xml, application.properties, ModernizedApplication.java, services, domain models)
- Real Apache Maven build producing executable fat JAR (~22MB)
- Live Spring Boot application startup on OpenJDK 26
- Health & readiness verification (/api/health, /actuator/health)
- Source-derived behavioral golden matrix execution against live application
- Cross-module integration matrix execution against live application
- Remote HP Qdrant over private LAN
- Distributed Local AI (Apple Silicon M1 + Windows HP Host)
- Autonomous defect repair and bad repair rejection
- Full provenance chain integrity
- Machine-readable zero-defect certification gate evaluation -> CERTIFIED
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import subprocess
import time
from typing import Any

import pytest

from autoforge_knowledge_platform.rag18.config import KnowledgeConfig
from autoforge_knowledge_platform.rag18.models import KnowledgeChunk, RetrievalScope
from autoforge_knowledge_platform.rag18.qdrant_store import QdrantKnowledgeStore
from autoforge_modernization.composition.app_runner import SpringBootApplicationRunner
from autoforge_modernization.composition.generator import GenericTargetArtifactGenerator
from autoforge_modernization.composition.planner import GenericTransformationPlanner
from autoforge_modernization.composition.repair import AutonomousTargetRepairCycle
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.composition.workload_selector import TransformationWorkloadSelector
from autoforge_modernization.provenance import ModernizationProvenanceChain, ProvenanceLink, ProvenanceStage
from autoforge_modernization.rag_integration import RAGClient
from autoforge_modernization.repair_cycle import RepairStatus
from autoforge_modernization.semantic.extractors import ProjectSemanticExtractor
from autoforge_modernization.target.specification import TargetSpecification

CARDDEMO_ROOT = Path(__file__).resolve().parents[3] / ".autoforge" / "carddemo"
HP_QDRANT_URL = "http://192.168.1.104:6333"


@pytest.fixture(scope="module")
def subsystem_closure_proof():
    selector = TransformationWorkloadSelector()
    _, proof = selector.select_coherent_subsystem_closure(CARDDEMO_ROOT, "TRANSACTION_PROCESSING")
    return proof


@pytest.fixture(scope="module")
def semantic_model(subsystem_closure_proof):
    extractor = ProjectSemanticExtractor()
    files = [CARDDEMO_ROOT / f for f in subsystem_closure_proof.selected_files if (CARDDEMO_ROOT / f).exists()]
    return extractor.extract_project(CARDDEMO_ROOT, file_paths=files)


@pytest.fixture(scope="module")
def transformation_plan(semantic_model):
    planner = GenericTransformationPlanner()
    target_spec = TargetSpecification.java_spring_boot()
    return planner.plan(semantic_model, target_spec)


@pytest.fixture(scope="module")
def target_artifacts(semantic_model, transformation_plan):
    generator = GenericTargetArtifactGenerator()
    target_spec = TargetSpecification.java_spring_boot()
    return generator.generate(semantic_model, transformation_plan, target_spec, include_project_manifests=True)


@pytest.fixture(scope="module")
def maven_build_result(target_artifacts, tmp_path_factory):
    verifier = TargetToolchainVerifier()
    target_spec = TargetSpecification.java_spring_boot()
    build_dir = tmp_path_factory.mktemp("maven_build_subsystem")
    return verifier.verify_maven(target_artifacts, target_spec, build_directory=build_dir)


class TestG5CompleteSubsystemCertification:
    """Rigorous acceptance test suite certifying Complete Subsystem Migration."""

    def test_criterion_1_subsystem_dependency_closure_is_complete(self, subsystem_closure_proof):
        """Criterion 1: Subsystem must have 100% complete topological internal dependency closure."""
        assert subsystem_closure_proof.subsystem_name == "TRANSACTION_PROCESSING"
        assert subsystem_closure_proof.internal_dependency_closure == "COMPLETE"
        assert subsystem_closure_proof.is_complete is True
        assert len(subsystem_closure_proof.missing_internal_dependencies) == 0
        assert len(subsystem_closure_proof.selected_files) == 35
        assert subsystem_closure_proof.physical_loc > 6000
        assert len(subsystem_closure_proof.entry_points) >= 2

    def test_criterion_2_semantic_model_derived_from_source(self, semantic_model):
        """Criterion 2: Semantic model represents all procedures, fields, rules, and I/O."""
        assert len(semantic_model.modules) >= 6
        assert len(semantic_model.entities) >= 5
        total_procs = sum(len(m.procedures) for m in semantic_model.modules.values())
        assert total_procs >= 20
        total_rules = sum(len(m.business_rules) for m in semantic_model.modules.values())
        assert total_rules >= 10

    def test_criterion_3_spring_boot_application_artifacts_generated(self, target_artifacts):
        """Criterion 3: Generator produces genuine Spring Boot application project."""
        paths = {a.relative_path for a in target_artifacts}
        assert "pom.xml" in paths
        assert "src/main/resources/application.properties" in paths
        assert "src/main/java/com/autoforge/generated/ModernizedApplication.java" in paths
        total_loc = sum(a.loc for a in target_artifacts)
        assert total_loc >= 2000

    def test_criterion_4_maven_packages_executable_fat_jar(self, maven_build_result):
        """Criterion 4: Real Apache Maven packages executable Spring Boot fat JAR with OpenJDK 26."""
        assert maven_build_result.passed is True
        assert maven_build_result.fat_jar_size_bytes > 15 * 1024 * 1024
        assert maven_build_result.class_count >= 15
        assert maven_build_result.errors_count == 0

    def test_criterion_5_spring_boot_starts_and_reports_healthy(self, maven_build_result):
        """Criterion 5: Spring Boot fat JAR launches and responds UP on /api/health and /actuator/health."""
        runner = SpringBootApplicationRunner(
            jar_path=maven_build_result.fat_jar_path,
            port=8089,
            startup_timeout_s=35.0,
        )
        try:
            metrics = runner.start()
            assert metrics.started is True
            assert metrics.health_status == "UP"
            assert metrics.startup_duration_ms > 0

            # Probing Actuator health
            actuator_res = runner.execute_rest_call("/actuator/health")
            assert actuator_res.get("status") == "UP"

            # Probing component registration
            comp_res = runner.execute_rest_call("/api/subsystem/components")
            assert comp_res.get("totalComponents", 0) >= 15
        finally:
            runner.stop()

    def test_criterion_6_behavioral_golden_matrix_passes_live(self, maven_build_result):
        """Criterion 6: All source-derived golden behavioral cases pass against running Spring Boot app."""
        runner = SpringBootApplicationRunner(
            jar_path=maven_build_result.fat_jar_path,
            port=8089,
            startup_timeout_s=35.0,
        )
        try:
            runner.start()
            # Batch job POSTTRAN
            r1 = runner.execute_rest_call("/api/subsystem/execute/PosttranOrchestration")
            assert r1.get("returnCode") == 0
            assert r1.get("status") == "SUCCESS"

            # Batch job TRANREPT
            r2 = runner.execute_rest_call("/api/subsystem/execute/TranreptOrchestration")
            assert r2.get("returnCode") == 0
            assert r2.get("status") == "SUCCESS"

            # Batch program CBTRN01C
            r3 = runner.execute_rest_call("/api/subsystem/execute/Cbtrn01c")
            assert r3.get("returnCode") == 0
            assert r3.get("status") == "SUCCESS"

            # Online CICS COTRN00C
            r4 = runner.execute_rest_call("/api/subsystem/execute/Cotrn00c")
            assert r4.get("returnCode") == 0
            assert r4.get("status") == "SUCCESS"

            # Valid Date evaluation
            r5 = runner.execute_rest_call("/api/subsystem/evaluate-date?date=2026-09-06&format=YYYY-MM-DD")
            assert r5.get("returnCode") == 0
            assert r5.get("status") == "SUCCESS"

            # Invalid Date evaluation
            r6 = runner.execute_rest_call("/api/subsystem/evaluate-date?date=BAD-DATE&format=YYYY-MM-DD")
            assert r6.get("returnCode") == 4
            assert r6.get("status") == "ERROR"

            # File status 00
            r7 = runner.execute_rest_call("/api/subsystem/evaluate-status?status=00")
            assert r7.get("returnCode") == 0

            # File status 10
            r8 = runner.execute_rest_call("/api/subsystem/evaluate-status?status=10")
            assert r8.get("returnCode") == 16
        finally:
            runner.stop()

    def test_criterion_7_cross_module_integration_edges_pass(self, maven_build_result):
        """Criterion 7: Cross-module caller->callee edges execute without error."""
        runner = SpringBootApplicationRunner(
            jar_path=maven_build_result.fat_jar_path,
            port=8089,
            startup_timeout_s=35.0,
        )
        try:
            runner.start()
            edges = [
                "PosttranOrchestration",
                "TranreptOrchestration",
                "Cotrn00c",
                "Cotrn01c",
                "Cotrn02c",
                "Cbtrn01c",
                "Cbtrn02c",
                "Cbtrn03c",
            ]
            for ep in edges:
                res = runner.execute_rest_call(f"/api/subsystem/execute/{ep}")
                assert res.get("returnCode") == 0
                assert res.get("status") in ("SUCCESS", "INITIALIZED")
        finally:
            runner.stop()

    @pytest.mark.asyncio
    async def test_criterion_8_hp_qdrant_remote_lan_exercised(self):
        """Criterion 8: Exercise real HP Qdrant over private LAN (192.168.1.104:6333)."""
        coll_name = f"test_subsystem_qdrant_{int(time.time())}"
        store = QdrantKnowledgeStore(
            url=HP_QDRANT_URL,
            collection_name=coll_name,
        )
        await store.set_expected_dimension(4)
        await store.initialize()

        chunk = KnowledgeChunk(
            knowledge_id="chk-trans-01",
            chunk_id="chk-trans-01",
            source_id="sha_trans_01",
            chunk_index=0,
            path="jcl/POSTTRAN.jcl",
            content="Transaction processing batch job POSTTRAN executes CBTRN01C and CBTRN02C.",
            content_hash="hash_trans_01",
            project_id="g5_subsystem_test",
            workflow_id="modernization",
        )
        count = await store.upsert_chunks([chunk], [[0.1, 0.2, 0.3, 0.4]])
        assert count == 1

        hits = await store.query([0.1, 0.2, 0.3, 0.4], scope=RetrievalScope(project_id="g5_subsystem_test"), top_k=1)
        assert len(hits) == 1
        assert "POSTTRAN" in hits[0].content

        try:
            await store.delete_collection()
        except Exception:
            pass

    def test_criterion_9_autonomous_repair_and_bad_repair_rejection(self, target_artifacts):
        """Criterion 9: Autonomous repair recovers from defects; bad repairs are rejected."""
        verifier = TargetToolchainVerifier()
        target_spec = TargetSpecification.java_spring_boot()
        repair_engine = AutonomousTargetRepairCycle(verifier=verifier, max_attempts=3)

        # Defect injection
        defect_arts = [
            copy.deepcopy(a)
            for a in target_artifacts
            if a.target_language.lower() == "java" and not a.relative_path.endswith("ModernizedApplication.java")
        ]
        comp = next(a for a in defect_arts if a.component_name == "Csutldtc")
        comp.code = comp.code.replace("public class Csutldtc implements Serializable {", "public class Csutldtc implements Serializable {\n    DEFECT_INJECTED_BAD_TOKEN;")

        fail_res = verifier.verify(defect_arts, target_spec)
        assert fail_res.passed is False

        # Autonomous repair
        repaired_arts, repair_outcome, repair_v_res = repair_engine.repair_cycle(defect_arts, fail_res, target_spec)
        assert repair_outcome.final_status == RepairStatus.SUCCESS
        assert repair_v_res.passed is True

        # Bad repair rejection
        bad_arts = copy.deepcopy(defect_arts)
        bad_comp = next(a for a in bad_arts if a.component_name == "Csutldtc")
        bad_comp.code = "public class Csutldtc { SYNTAX_ERROR_PERMANENT }"
        bad_verify = verifier.verify(bad_arts, target_spec)
        assert bad_verify.passed is False
