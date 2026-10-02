"""Adversarial matrix G — project isolation (Gate 14 G, Gate 11).

Both isolation shapes required by the gate are covered:

* same candidate id, different project,
* different candidate id, different project.

Cross-project operations must fail closed at every stage: read, evaluate,
approve, promote, rollback.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from autoforge_learning.promotion import PromotionError, RollbackError
from autoforge_learning.store import ActiveLearningState, DurableLearningStore
from tests.helpers import evidence_payload_for, healthy_metrics, make_human, make_service

KIND = "pattern_template"
KEY = "template-alpha"


def _make_candidate(project_id, summary="candidate"):
    from autoforge_learning.models import LearningCandidate, LearningScope, LearningScopeKind

    return LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind=KIND,
        summary=summary,
    )


def _ready(service, project_id, evidence=None, summary="candidate"):
    """A stored, evaluated, human-approved candidate for ``project_id``.

    Evidence is built *for this project* — deliberately, so that a caller
    cannot accidentally pass another project's bundle and get a false pass.
    """
    evidence = evidence or evidence_payload_for(
        healthy_metrics(latency_ms=90.0), project_id
    )
    record = service.record_evidence(
        service.create_candidate(_make_candidate(project_id, summary)), evidence
    )
    report = service.evaluate(
        record=record,
        baseline=healthy_metrics(latency_ms=100.0),
        candidate_metrics=healthy_metrics(latency_ms=90.0),
    )
    approval = service.approvals.record_decision(
        approval=service.request_approval(
            record=record,
            evaluation=report,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=make_service(),
        ),
        approver=make_human(),
        approve=True,
        reason="ok",
    )
    return record, report, approval


# ── G.1 CROSS-PROJECT READ ───────────────────────────────────────────────────


def test_project_b_cannot_read_project_as_candidate(
    service, passing_evidence, project_id, other_project_id
):
    """G.1 — same candidate id, different project: not found, not shared."""
    record_a, _, _ = _ready(service, project_id, passing_evidence)
    found_b = service.store.get_candidate(other_project_id, record_a.candidate_id)
    assert found_b is None
    assert service.store.get_candidate(project_id, record_a.candidate_id) is not None


def test_project_b_listing_never_includes_project_a(
    service, passing_evidence, project_id, other_project_id
):
    """G.1 — no accidental global learning state."""
    _ready(service, project_id, passing_evidence)
    _ready(service, other_project_id)

    a_ids = {c.candidate_id for c in service.store.list_candidates(project_id)}
    b_ids = {c.candidate_id for c in service.store.list_candidates(other_project_id)}

    assert a_ids and b_ids
    assert a_ids.isdisjoint(b_ids)
    assert len(a_ids) == 1 and len(b_ids) == 1


def test_the_two_projects_store_in_separate_directories(
    service, passing_evidence, project_id, other_project_id
):
    """G.1 — isolation is structural, not a filter applied on read."""
    _ready(service, project_id, passing_evidence)
    _ready(service, other_project_id)
    root = service.store.root
    assert (root / str(project_id)).is_dir()
    assert (root / str(other_project_id)).is_dir()


# ── G.2 CROSS-PROJECT EVALUATE ───────────────────────────────────────────────


def test_project_b_evidence_cannot_validate_project_as_candidate(
    service, passing_evidence, project_id, other_project_id
):
    """G.2 — evidence is bound to the project it was collected in."""
    record_b = service.create_candidate(
        _make_candidate(other_project_id, "B"),
    )
    # Attach project A's evidence to project B's candidate.
    record_b = service.record_evidence(record_b, passing_evidence)
    report = service.evaluate(
        record=record_b,
        baseline=healthy_metrics(latency_ms=100.0),
        candidate_metrics=healthy_metrics(latency_ms=90.0),
    )
    assert report.promotable is False


# ── G.3 CROSS-PROJECT APPROVE ────────────────────────────────────────────────


def test_project_b_cannot_approve_project_as_candidate(
    service, passing_evidence, project_id, other_project_id
):
    """G.3 — an approval is bound to one project; verification re-checks it."""
    record_a, report_a, approval_a = _ready(service, project_id, passing_evidence)
    with pytest.raises(PromotionError):
        service.promotion.promote(
            project_id=other_project_id,
            candidate_id=record_a.candidate_id,
            evaluation=report_a,
            approval=approval_a,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=make_human(),
        )
    assert service.active_state(other_project_id, KIND, KEY) is None


# ── G.4 CROSS-PROJECT PROMOTE ────────────────────────────────────────────────


def test_project_b_cannot_promote_project_as_candidate(
    service, passing_evidence, project_id, other_project_id
):
    """G.4 — promotion under the wrong project id activates nothing anywhere."""
    record_a, report_a, approval_a = _ready(service, project_id, passing_evidence)
    with pytest.raises(PromotionError):
        service.promotion.promote(
            project_id=other_project_id,
            candidate_id=record_a.candidate_id,
            evaluation=report_a,
            approval=approval_a,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=make_human(),
        )
    assert service.active_state(other_project_id, KIND, KEY) is None
    assert service.active_state(project_id, KIND, KEY) is None


def test_a_misfiled_active_state_is_refused(tmp_path, project_id, other_project_id):
    """G.4 — a record whose envelope disagrees with its content fails closed."""
    import json

    store = DurableLearningStore(tmp_path / "iso")
    state = ActiveLearningState(
        project_id=project_id,
        kind=KIND,
        key=KEY,
        version_id=uuid.uuid4(),
        version_number=1,
        activation_timestamp=datetime.now(timezone.utc),
        scope_kind="project",
    )
    store.set_active_state(state)
    path = tmp_path / "iso" / str(project_id) / "active" / f"{KIND}__{KEY}.json"
    raw = json.loads(path.read_text())
    # Rewrite the envelope's project without touching the payload: the store
    # must refuse rather than return a record belonging to another project.
    raw["project_id"] = str(other_project_id)
    path.write_text(json.dumps(raw))
    with pytest.raises(Exception):
        store.get_active_state(project_id, KIND, KEY)


# ── G.5 CROSS-PROJECT ROLLBACK ───────────────────────────────────────────────


def test_project_b_cannot_rollback_project_as_promotion(
    service, passing_evidence, project_id, other_project_id
):
    """G.5 — a handle is only usable inside its own project."""
    record, report, approval = _ready(service, project_id, passing_evidence)
    promoted = service.promote(
        record=record,
        evaluation=report,
        approval=approval,
        kind=KIND,
        key=KEY,
        proposed_effect="effect",
        requested_by=make_human(),
    )
    with pytest.raises(RollbackError):
        service.rollback(
            project_id=other_project_id, handle_id=promoted.rollback_handle_id
        )
    # Project A remains promoted — the foreign rollback changed nothing.
    assert service.active_state(project_id, KIND, KEY) is not None


def test_each_project_rolls_back_independently(
    service, passing_evidence, project_id, other_project_id
):
    """G.5 — rolling back A leaves B untouched."""
    a = _ready(service, project_id, passing_evidence, "A")
    b = _ready(service, other_project_id, summary="B")

    pa = service.promote(
        record=a[0], evaluation=a[1], approval=a[2], kind=KIND, key=KEY,
        proposed_effect="a", requested_by=make_human(),
    )
    pb = service.promote(
        record=b[0], evaluation=b[1], approval=b[2], kind=KIND, key=KEY,
        proposed_effect="b", requested_by=make_human(),
    )

    service.rollback(project_id=project_id, handle_id=pa.rollback_handle_id)

    assert service.active_state(project_id, KIND, KEY) is None
    active_b = service.active_state(other_project_id, KIND, KEY)
    assert active_b is not None
    assert active_b.candidate_id == b[0].candidate_id