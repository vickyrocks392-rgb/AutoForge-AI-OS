"""
Tests for Grounded Question Answering, Citations, and Abstention.
"""

import tempfile
import pytest
from pathlib import Path
from config import resolve_and_validate_paths
from service import PolicyDeskService
from models import QueryRequest


@pytest.fixture(scope="module")
def populated_service():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = resolve_and_validate_paths(
            custom_data_dir=Path(tmp_dir),
            allow_test_in_repo=True,
        )
        svc = PolicyDeskService(config)
        corpus_dir = Path(__file__).resolve().parents[1] / "sample_corpus"
        for f in sorted(corpus_dir.glob("*.*")):
            if f.name == "corpus_manifest.json":
                continue
            svc.upload_document(f)
        yield svc


def test_exact_fact_query_with_citation(populated_service):
    req = QueryRequest(query="What is the hourly billing rate for an Associate Consultant?")
    resp = populated_service.query(req)

    assert not resp.abstained
    assert "150" in resp.answer
    assert len(resp.citations) > 0
    top_citation = resp.citations[0]
    assert "consulting_rate_card.pdf" in top_citation.filename
    assert top_citation.page == 1
    assert resp.is_grounded


def test_multi_document_synthesis(populated_service):
    req = QueryRequest(
        query="What is the hourly rate for a Senior Consultant and what is our deadline for submitting weekly timesheets?"
    )
    resp = populated_service.query(req)

    assert not resp.abstained
    assert "250" in resp.answer
    assert "6:00" in resp.answer or "Friday" in resp.answer

    cited_files = [c.filename for c in resp.citations]
    assert any("rate_card" in f for f in cited_files)
    assert any("operating_procedures" in f for f in cited_files)


def test_unanswerable_question_abstains(populated_service):
    req = QueryRequest(query="What is PolicyDesk's parental leave policy duration and maternity benefit?")
    resp = populated_service.query(req)

    assert resp.abstained
    assert "cannot find" in resp.answer.lower() or "not documented" in resp.answer.lower()
    assert resp.is_grounded
