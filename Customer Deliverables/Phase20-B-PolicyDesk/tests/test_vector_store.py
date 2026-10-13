"""
Tests for Persistent ChromaDB Vector Store Adapter.
"""

import tempfile
from pathlib import Path
from vector_store import PolicyDeskVectorStore
from models import ChunkRecord


def test_vector_store_persistence_and_search():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = PolicyDeskVectorStore(
            persist_dir=Path(tmp_dir),
            collection_name="test_collection",
        )

        chunks = [
            ChunkRecord(
                chunk_id="c01",
                doc_id="doc_rates",
                filename="rates.txt",
                format="txt",
                page=None,
                line_start=1,
                line_end=5,
                section="Rates",
                content="Associate Consultant standard rate is $150 per hour.",
                content_hash="h1",
            ),
            ChunkRecord(
                chunk_id="c02",
                doc_id="doc_rates",
                filename="rates.txt",
                format="txt",
                page=None,
                line_start=6,
                line_end=10,
                section="Rates",
                content="Principal Consultant hourly rate is $350 per hour.",
                content_hash="h2",
            ),
        ]

        store.add_chunks(chunks)
        assert store.count_chunks() == 2

        # Query
        results = store.query("What is the Associate Consultant billing rate?", top_k=2)
        assert len(results) > 0
        top_chunk, score = results[0]
        assert top_chunk.chunk_id == "c01"
        assert score > 0.3

        # Delete by doc_id
        deleted_count = store.delete_document("doc_rates")
        assert deleted_count == 2
        assert store.count_chunks() == 0
