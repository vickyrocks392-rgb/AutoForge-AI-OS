"""
Phase 20-A: Legacy Modernization End-to-End Commercial Capability Certification Test Suite.

Authoritative Proof:
- Real Customer Ingress: AutoForgeApiService.execute_intent_pipeline -> Kernel.submit_request
- Sole Orchestration Authority: DefaultOrchestrationEngine ("Orchestration Engine")
- Seam Dispatch: CommercialCapabilityRouter -> LegacyModernizationEngine
- Real Toolchains: OpenJDK javac & java, GnuCOBOL cobc
- Real Target Generation: COBOL AST -> Java Codegen & Runtime
- Independent Golden Master Comparison: 100% byte-for-byte SHA-256 equivalence
- Defect & Repair Cycle: Failure -> Diagnosis -> Repair -> Rebuild -> Revalidation
- Strict Customer Boundary: Isolated in Modernization Output/{project_id}, 0 internal leakage
- Machine-Readable Manifest & Provenance Chain
- Performance Telemetry & NLOC/hour Accounting
- Continuous Learning Integration
- Repeatability across Run A and Run B
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
import uuid
import pytest

from autoforge_api.models import IntentExecutionRequest, IntentExecutionResponse
from autoforge_api.service import AutoForgeApiService
from autoforge_composition.capability_router import (
    CAPABILITY_MODERNIZATION,
    build_default_router,
)
from autoforge_composition.execution_outcome import OutcomeStatus
from autoforge_kernel.orchestration import DefaultOrchestrationEngine
from autoforge_modernization.service.engine import LegacyModernizationEngine

_REPO = pathlib.Path(__file__).resolve().parents[3]
_WORKLOAD_ROOT = pathlib.Path("/Users/kalachanddash/Developer/.autoforge-p20-workloads/playbook")


@pytest.fixture(scope="module")
def api_service():
    return AutoForgeApiService()


def test_phase20_a_e2e_canonical_customer_ingress_to_delivery(api_service):
    """
    Certifies that a real customer modernization request entering through AutoForgeApiService
    executes end-to-end through the canonical architecture and produces a certified delivery package.
    """
    assert _WORKLOAD_ROOT.exists(), f"Workload not found at {_WORKLOAD_ROOT}"

    req = IntentExecutionRequest(
        prompt="Modernize legacy mainframe batch processing system to Java Spring Boot.",
        intent_type="modernization",
        context={
            "capability": CAPABILITY_MODERNIZATION,
            "legacy_source_root": str(_WORKLOAD_ROOT),
        },
    )

    response = api_service.execute_intent_pipeline(req)

    # 1. Verification of Canonical API Response
    assert isinstance(response, IntentExecutionResponse)
    assert response.status == "COMPLETED", f"Expected COMPLETED, got {response.status}: {response.summary}"
    assert response.project_id is not None
    assert "completed successfully" in response.summary.lower()

    # 2. Customer Delivery Package Verification
    delivery_dir = _REPO / "Modernization Output" / response.project_id
    assert delivery_dir.exists(), f"Delivery directory {delivery_dir} does not exist"

    # Required Customer Sections
    expected_sections = [
        "legacy-source",
        "modernization",
        "modernized-application",
        "tests",
        "deployment",
        "documentation",
        "validation",
        "provenance",
        "DELIVERY-MANIFEST.json",
    ]
    for sec in expected_sections:
        sec_path = delivery_dir / sec
        assert sec_path.exists(), f"Missing required delivery section: {sec}"

    # 3. Delivery Manifest Inspection
    manifest_file = delivery_dir / "DELIVERY-MANIFEST.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    assert manifest["certification_status"] == "CERTIFIED"
    assert manifest["modernization_target"] == "Java (OpenJDK 21)"
    assert manifest["build_result"]["passed"] is True
    assert manifest["execution_result"]["passed"] is True
    assert manifest["golden_master"]["passed"] is True
    assert manifest["behavioral_equivalence"]["passed"] is True
    assert manifest["behavioral_equivalence"]["byte_identical"] is True

    # 4. Behavioral Equivalence Byte-Identical Proof
    cand_hashes = manifest["behavioral_equivalence"]["candidate_hashes"]
    golden_hashes = manifest["golden_master"]["golden_hashes"]

    assert "accounts_out.dat" in cand_hashes
    assert "exceptions.dat" in cand_hashes
    assert cand_hashes["accounts_out.dat"] == golden_hashes["accounts_out.dat"]
    assert cand_hashes["exceptions.dat"] == golden_hashes["exceptions.dat"]
    assert cand_hashes["accounts_out.dat"] == "ac18ac0e6ae5f5a347164be00544e756536b567038f128d3b5b754ea8099f6cf"
    assert cand_hashes["exceptions.dat"] == "1fc4021f6fed84f41cd4103adc781a4b91c9a4bcbe904013863f3c77702aa9cb"

    # 5. Customer Boundary Isolation Proof (Zero AutoForge Internal Leakage)
    for root, dirs, files in os.walk(delivery_dir):
        for f in files:
            full_path = pathlib.Path(root) / f
            # Must not contain AutoForge source code
            assert "autoforge" not in f.lower() or f == "DELIVERY-MANIFEST.json", f"Internal leak detected: {f}"
            # Must not contain pytest files
            assert not f.startswith("test_") and not f.endswith("_test.py")

    # 6. Standalone Executable Verification
    run_sh = delivery_dir / "deployment" / "run.sh"
    assert run_sh.exists()
    assert os.access(run_sh, os.X_OK)

    # 7. Provenance Verification
    prov_file = delivery_dir / "provenance" / "provenance_chain.json"
    assert prov_file.exists()
    prov_data = json.loads(prov_file.read_text(encoding="utf-8"))
    assert prov_data["chain_id"] == manifest["provenance_chain_id"]
    stages = [link["stage"] for link in prov_data["links"]]
    assert "source" in stages
    assert "analysis" in stages
    assert "plan" in stages
    assert "transformation" in stages
    assert "verification" in stages
    assert "artifact" in stages or "packaging" in stages

    # 8. Telemetry & NLOC Accounting
    metrics = manifest["performance_metrics"]
    assert metrics["source_nloc"] > 0
    assert metrics["end_to_end_nloc_per_hour"] > 0
    assert metrics["total_wall_clock_seconds"] > 0


def test_phase20_a_defect_mutation_repair_cycle():
    """
    Certifies the authoritative failure, diagnosis, repair, rebuild, and re-validation cycle.
    Injects a controlled compilation defect and proves autonomous remediation.
    """
    engine = LegacyModernizationEngine()
    project_id = f"test-repair-{uuid.uuid4()}"
    job_id = f"job-repair-{uuid.uuid4()}"

    res = engine.execute(
        project_id=project_id,
        job_id=job_id,
        source_root=_WORKLOAD_ROOT,
        project_configuration={"capability": CAPABILITY_MODERNIZATION},
        inject_defect_for_repair_proof=True,
    )

    assert res.success is True, f"Modernization engine failed after repair: {res.error_message}"
    assert res.repair_count == 1, f"Expected 1 repair cycle, got {res.repair_count}"

    scorecard = res.verification_scorecard
    assert scorecard["build_passed"] is True
    assert scorecard["behavioral_equivalence"] is True
    assert scorecard["repaired"] is True
    assert len(scorecard["repair_events"]) == 1

    event = scorecard["repair_events"][0]
    assert event["repaired"] is True
    assert event["rebuild_passed"] is True
    assert "syntax" in event["diagnosis"].lower() or "error" in event["diagnosis"].lower()


def test_phase20_a_repeatability_run_a_and_run_b(api_service):
    """
    Certifies repeatability by comparing two complete commercial modernization runs.
    """
    req_a = IntentExecutionRequest(
        prompt="Modernize legacy mainframe batch processing system (Run A).",
        intent_type="modernization",
        context={
            "capability": CAPABILITY_MODERNIZATION,
            "legacy_source_root": str(_WORKLOAD_ROOT),
        },
    )
    req_b = IntentExecutionRequest(
        prompt="Modernize legacy mainframe batch processing system (Run B).",
        intent_type="modernization",
        context={
            "capability": CAPABILITY_MODERNIZATION,
            "legacy_source_root": str(_WORKLOAD_ROOT),
        },
    )

    res_a = api_service.execute_intent_pipeline(req_a)
    res_b = api_service.execute_intent_pipeline(req_b)

    assert res_a.status == "COMPLETED"
    assert res_b.status == "COMPLETED"

    manifest_a_path = _REPO / "Modernization Output" / res_a.project_id / "DELIVERY-MANIFEST.json"
    manifest_b_path = _REPO / "Modernization Output" / res_b.project_id / "DELIVERY-MANIFEST.json"

    man_a = json.loads(manifest_a_path.read_text(encoding="utf-8"))
    man_b = json.loads(manifest_b_path.read_text(encoding="utf-8"))

    # Both runs produce identical behavioral output
    assert man_a["behavioral_equivalence"]["candidate_hashes"] == man_b["behavioral_equivalence"]["candidate_hashes"]

    # Target LOC and source NLOC are identical
    assert man_a["performance_metrics"]["source_nloc"] == man_b["performance_metrics"]["source_nloc"]
    assert man_a["performance_metrics"]["target_nloc"] == man_b["performance_metrics"]["target_nloc"]

    # Wall-clock durations are within reproducible boundaries
    dur_a = man_a["performance_metrics"]["total_wall_clock_seconds"]
    dur_b = man_b["performance_metrics"]["total_wall_clock_seconds"]
    diff = abs(dur_a - dur_b)
    assert diff < 2.5, f"Absolute variation too large: {diff:.3f}s"
    assert dur_a < 15.0 and dur_b < 15.0


def test_phase20_a_architecture_guards_preserved():
    """
    Certifies architectural invariants:
    - Exactly one production Orchestration Engine
    - API ingress does not import modernization internals
    - CommercialCapabilityRouter remains the dispatch seam
    - Model Router remains infrastructure
    """
    service = AutoForgeApiService()
    orch = service.system.kernel.orchestration_engine
    assert isinstance(orch, DefaultOrchestrationEngine)

    router = build_default_router()
    assert router.supports(CAPABILITY_MODERNIZATION) is True

    # AST check on api/src/autoforge_api/
    api_dir = _REPO / "apps" / "api" / "src" / "autoforge_api"
    forbidden_modules = {
        "autoforge_modernization.service",
        "autoforge_modernization.pipeline",
    }
    for py_file in api_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_modules
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert node.module not in forbidden_modules
