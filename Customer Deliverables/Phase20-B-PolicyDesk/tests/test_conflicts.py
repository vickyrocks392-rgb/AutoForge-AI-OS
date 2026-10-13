"""
Tests for Policy Versioning, Superseding Disclosure, and Conflict Detection.
"""

import tempfile
import pytest
from pathlib import Path
from config import resolve_and_validate_paths
from service import PolicyDeskService
from models import QueryRequest


@pytest.fixture(scope="module")
def travel_service():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = resolve_and_validate_paths(
            custom_data_dir=Path(tmp_dir),
            allow_test_in_repo=True,
        )
        svc = PolicyDeskService(config)
        corpus_dir = Path(__file__).resolve().parents[1] / "sample_corpus"
        svc.upload_document(corpus_dir / "travel_and_expense_policy_2024.md")
        svc.upload_document(corpus_dir / "travel_and_expense_policy_2026.md")
        yield svc


def test_conflict_detection_and_disclosure(travel_service):
    req = QueryRequest(query="What is the daily meal per diem allowance for business travel?")
    resp = travel_service.query(req)

    assert resp.conflict is not None
    assert resp.conflict.has_conflict
    assert "85" in resp.answer  # Active 2026 rate
    assert "2026" in resp.answer
    assert "superseded" in resp.answer.lower() or "superseded" in resp.conflict.summary.lower()
