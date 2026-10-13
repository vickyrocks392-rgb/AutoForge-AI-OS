"""
Tests for Index and Ingestion Persistence Across Restarts.
"""

import tempfile
from pathlib import Path
from config import resolve_and_validate_paths
from service import PolicyDeskService
from models import QueryRequest


def test_clean_restart_preserves_persistent_index():
    with tempfile.TemporaryDirectory() as tmp_dir:
        data_path = Path(tmp_dir)

        # 1. First Process Session: Ingest documents
        config1 = resolve_and_validate_paths(
            custom_data_dir=data_path,
            allow_test_in_repo=True,
        )
        svc1 = PolicyDeskService(config1)
        corpus_dir = Path(__file__).resolve().parents[1] / "sample_corpus"
        svc1.upload_document(corpus_dir / "policydesk_overview.md")
        svc1.upload_document(corpus_dir / "standard_operating_procedures.md")

        initial_doc_count = len(svc1.list_documents().documents)
        initial_chunk_count = svc1.vector_store.count_chunks()
        assert initial_doc_count == 2
        assert initial_chunk_count > 0

        # Terminate / delete first service instance
        del svc1

        # 2. Second Process Session: Fresh startup on same data_dir
        config2 = resolve_and_validate_paths(
            custom_data_dir=data_path,
            allow_test_in_repo=True,
        )
        svc2 = PolicyDeskService(config2)

        # Verify index and registry were preserved without re-ingesting
        reloaded_docs = svc2.list_documents().documents
        reloaded_chunks = svc2.vector_store.count_chunks()

        assert len(reloaded_docs) == initial_doc_count
        assert reloaded_chunks == initial_chunk_count

        # Test query on restored state
        resp = svc2.query(QueryRequest(query="What is the deadline for submitting weekly timesheets?"))
        assert not resp.abstained
        assert "6:00" in resp.answer or "Friday" in resp.answer
        assert len(resp.citations) > 0
        assert "standard_operating_procedures.md" in resp.citations[0].filename
