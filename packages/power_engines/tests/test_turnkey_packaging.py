"""Tests for Turnkey Customer Packaging & Documentation Generator."""

import pytest
from pathlib import Path
from autoforge_power_engines.packaging import CustomerProjectPackager
from autoforge_power_engines.specification import CustomerProjectSpecification, DeploymentPreference


def test_customer_packaging_structure(tmp_path):
    deliv_dir = tmp_path / "acme_rag" / "delivery-001"
    packager = CustomerProjectPackager(deliv_dir)
    dirs = packager.prepare_directories()

    assert (deliv_dir / "src").is_dir()
    assert (deliv_dir / "tests").is_dir()
    assert (deliv_dir / "config").is_dir()
    assert (deliv_dir / "scripts").is_dir()
    assert (deliv_dir / "docs").is_dir()
    assert (deliv_dir / "artifacts").is_dir()
    assert (deliv_dir / "evidence").is_dir()
    assert (deliv_dir / "verification").is_dir()

    spec = CustomerProjectSpecification(
        project_name="Acme RAG",
        project_description="Enterprise Q&A Knowledge Assistant",
        deployment_preference=DeploymentPreference.STANDALONE_FASTAPI,
    )

    readme = packager.generate_readme(
        spec=spec,
        architecture_summary="FastAPI + BM25 in-memory local vector index",
        run_command="python3 src/app.py",
        knowledge_sources_summary=["Manual.pdf (12 chunks, 4500 bytes)"],
        test_summary="2/2 tests passed",
        verification_summary="1.00 Grounding Precision",
    )
    readme_path = packager.write_file("README.md", readme)
    assert readme_path.exists()
    assert "Acme RAG" in readme_path.read_text(encoding="utf-8")

    report = packager.generate_delivery_report(
        spec=spec,
        execution_id="exec-123",
        stages_executed=["INTAKE", "EXECUTE", "PACKAGE"],
        repair_cycles=0,
        sources_processed=[{"source_id": "doc1", "path": "manual.pdf", "type": "pdf", "size_bytes": 4500}],
        chunks_count=12,
        tests_run=2,
        tests_passed=2,
        grounding_score=1.0,
        provenance_records=[{"stage": "PACKAGED"}],
    )
    report_path = packager.write_file("DELIVERY_REPORT.md", report)
    assert report_path.exists()
    assert "OFFICIAL CUSTOMER DELIVERY REPORT" in report_path.read_text(encoding="utf-8")

    manifest = packager.create_manifest()
    assert manifest.total_bytes > 0
    assert "README.md" in manifest.files_created
    assert "DELIVERY_REPORT.md" in manifest.files_created
    assert "README.md" in manifest.sha256_checksums
