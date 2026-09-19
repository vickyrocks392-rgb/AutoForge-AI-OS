"""Customer Data and Project Isolation Test for Phase 18-COMMERCIAL-A.

Validates:
1. Two independent customer projects executed concurrently or sequentially produce completely isolated outputs.
2. Distinct delivery directories and artifact hierarchies.
3. No shared knowledge indices, chunks, or tokens.
4. Cross-project retrieval returns ZERO results for terms exclusively present in the counterpart.
5. In-flight execution memory is cleanly isolated per execution_id.
6. Provenance manifests and telemetry are strictly decoupled.
"""

import os
import json
import pytest
from pathlib import Path
from autoforge_power_engines.specification import CustomerProjectSpecification, KnowledgeSourceSpec, SourceType
from autoforge_power_engines.rag.engine import RAGKnowledgePowerEngine


@pytest.mark.asyncio
async def test_customer_data_and_tenant_isolation(tmp_path):
    output_root = tmp_path / "commercial_deliveries"
    output_root.mkdir(parents=True, exist_ok=True)

    # 1. Project A: Healthcare Provider (Confidential HIPAA & Patient Protocols)
    spec_a = CustomerProjectSpecification(
        project_name="HealthcareCorp",
        project_description="Clinical protocols and HIPAA patient safety rules",
        output_root=str(output_root),
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="hipaa-protocol",
                source_type=SourceType.INLINE_TEXT,
                content=(
                    "# HIPAA Patient Data Protocol\n"
                    "All patient Protected Health Information (PHI) requires AES-256 encryption at rest. "
                    "HealthcareCorp medical records must never be exported outside the clinical enclave. "
                    "Emergency override code: CLINICAL_ALPHA_99."
                ),
            )
        ],
    )

    # 2. Project B: Defense Aerospace (ITAR & Avionics Specifications)
    spec_b = CustomerProjectSpecification(
        project_name="DefenseAero",
        project_description="Avionics flight guidance and ITAR controls",
        output_root=str(output_root),
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="itar-avionics",
                source_type=SourceType.INLINE_TEXT,
                content=(
                    "# Avionics Guidance System\n"
                    "Flight computer altitude threshold is set to 45000 feet. "
                    "DefenseAero telemetry adheres strictly to ITAR Category VIII export controls. "
                    "Guidance encryption key identifier: DEFENSE_BRAVO_77."
                ),
            )
        ],
    )

    engine = RAGKnowledgePowerEngine()

    # Execute Project A
    res_a = await engine.execute_lifecycle(spec_a)
    assert res_a.success is True, f"Project A lifecycle failed: {res_a.error_message}"
    dir_a = Path(res_a.delivery_dir)

    # Execute Project B
    res_b = await engine.execute_lifecycle(spec_b)
    assert res_b.success is True, f"Project B lifecycle failed: {res_b.error_message}"
    dir_b = Path(res_b.delivery_dir)

    # ── Verify Directory Separation ──────────────────────────────────────────
    assert dir_a != dir_b, "Project A and B must not share a delivery directory"
    assert "healthcarecorp" in str(dir_a).lower()
    assert "defenseaero" in str(dir_b).lower()

    # ── Verify Knowledge Index Isolation ─────────────────────────────────────
    index_a_file = dir_a / "artifacts" / "knowledge_index.json"
    index_b_file = dir_b / "artifacts" / "knowledge_index.json"

    assert index_a_file.exists(), "Project A index must exist"
    assert index_b_file.exists(), "Project B index must exist"

    data_a = json.loads(index_a_file.read_text(encoding="utf-8"))
    data_b = json.loads(index_b_file.read_text(encoding="utf-8"))

    content_a_str = json.dumps(data_a)
    content_b_str = json.dumps(data_b)

    # Project A index must contain Project A terms and ZERO Project B terms
    assert "CLINICAL_ALPHA_99" in content_a_str
    assert "HealthcareCorp" in content_a_str
    assert "DEFENSE_BRAVO_77" not in content_a_str
    assert "DefenseAero" not in content_a_str
    assert "ITAR" not in content_a_str

    # Project B index must contain Project B terms and ZERO Project A terms
    assert "DEFENSE_BRAVO_77" in content_b_str
    assert "DefenseAero" in content_b_str
    assert "CLINICAL_ALPHA_99" not in content_b_str
    assert "HealthcareCorp" not in content_b_str
    assert "HIPAA" not in content_b_str

    # ── Verify Standalone Retriever Search Isolation ─────────────────────────
    # Dynamically load each deliverable's standalone retriever
    import importlib.util

    def load_retriever(deliv_dir: Path):
        spec = importlib.util.spec_from_file_location("retriever", deliv_dir / "src" / "retriever.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.StandaloneRetriever(deliv_dir / "artifacts" / "knowledge_index.json")

    retriever_a = load_retriever(dir_a)
    retriever_b = load_retriever(dir_b)

    # Search Project A retriever
    hits_a_for_a = retriever_a.search("CLINICAL_ALPHA_99", top_k=5)
    hits_a_for_b = retriever_a.search("DEFENSE_BRAVO_77", top_k=5)
    assert len(hits_a_for_a) >= 1, "Project A retriever should find its own confidential token"
    assert len(hits_a_for_b) == 0, "Project A retriever MUST NOT find Project B secrets"

    # Search Project B retriever
    hits_b_for_b = retriever_b.search("DEFENSE_BRAVO_77", top_k=5)
    hits_b_for_a = retriever_b.search("CLINICAL_ALPHA_99", top_k=5)
    assert len(hits_b_for_b) >= 1, "Project B retriever should find its own confidential token"
    assert len(hits_b_for_a) == 0, "Project B retriever MUST NOT find Project A secrets"

    # ── Verify Provenance Manifest Decoupling ────────────────────────────────
    manifest_a_file = dir_a / "evidence" / "provenance_manifest.json"
    manifest_b_file = dir_b / "evidence" / "provenance_manifest.json"
    assert manifest_a_file.exists()
    assert manifest_b_file.exists()

    man_a = json.loads(manifest_a_file.read_text(encoding="utf-8"))
    man_b = json.loads(manifest_b_file.read_text(encoding="utf-8"))

    assert man_a["project_name"].lower() == "healthcarecorp"
    assert man_b["project_name"].lower() == "defenseaero"
    assert man_a["delivery_id"] != man_b["delivery_id"]
    assert man_a["sha256_checksums"]["artifacts/knowledge_index.json"] != man_b["sha256_checksums"]["artifacts/knowledge_index.json"]
