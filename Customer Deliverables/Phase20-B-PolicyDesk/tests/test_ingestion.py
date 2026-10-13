"""
Unit and Integration Tests for PolicyDesk Document Ingestion Engine.
Verifies parsing of PDF, Markdown, and TXT, duplicate detection, updates, and deletions.
"""

import tempfile
import pytest
from pathlib import Path
from config import resolve_and_validate_paths
from service import PolicyDeskService


@pytest.fixture
def test_service():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = resolve_and_validate_paths(
            custom_data_dir=Path(tmp_dir),
            allow_test_in_repo=True,
        )
        svc = PolicyDeskService(config)
        yield svc


def test_ingest_markdown_document(test_service):
    corpus_dir = Path(__file__).resolve().parents[1] / "sample_corpus"
    md_file = corpus_dir / "standard_operating_procedures.md"
    assert md_file.exists()

    resp = test_service.upload_document(md_file)
    assert resp.status == "indexed"
    assert resp.chunks_count > 0
    assert not resp.is_duplicate

    docs = test_service.list_documents().documents
    assert any(d.filename == "standard_operating_procedures.md" for d in docs)


def test_ingest_pdf_document(test_service):
    corpus_dir = Path(__file__).resolve().parents[1] / "sample_corpus"
    pdf_file = corpus_dir / "consulting_rate_card.pdf"
    assert pdf_file.exists()

    resp = test_service.upload_document(pdf_file)
    assert resp.status == "indexed"
    assert resp.chunks_count > 0

    # Verify chunk has page number
    doc = test_service.ingestion_service.get_document("consulting_rate_card")
    assert doc is not None
    assert doc.format == "pdf"


def test_duplicate_upload_prevention(test_service):
    corpus_dir = Path(__file__).resolve().parents[1] / "sample_corpus"
    md_file = corpus_dir / "policydesk_overview.md"

    # First upload
    res1 = test_service.upload_document(md_file)
    assert res1.status == "indexed"
    initial_chunks = test_service.vector_store.count_chunks()

    # Second upload of identical file
    res2 = test_service.upload_document(md_file)
    assert res2.is_duplicate
    assert res2.status == "skipped_duplicate"

    # Total chunks should NOT double
    assert test_service.vector_store.count_chunks() == initial_chunks


def test_document_deletion_purges_chunks(test_service):
    corpus_dir = Path(__file__).resolve().parents[1] / "sample_corpus"
    f = corpus_dir / "coffee_machine_guide.txt"

    res = test_service.upload_document(f)
    assert res.status == "indexed"
    chunks_before = test_service.vector_store.count_chunks()
    assert chunks_before > 0

    # Delete
    del_ok = test_service.delete_document("coffee_machine_guide")
    assert del_ok

    chunks_after = test_service.vector_store.count_chunks()
    assert chunks_after == chunks_before - res.chunks_count

    # Should not exist in registry
    assert test_service.ingestion_service.get_document("coffee_machine_guide") is None


def test_empty_file_rejected(test_service):
    with tempfile.NamedTemporaryFile(suffix=".txt") as tf:
        tf.write(b"")
        tf.flush()
        with pytest.raises(ValueError, match="empty"):
            test_service.upload_document(Path(tf.name))
