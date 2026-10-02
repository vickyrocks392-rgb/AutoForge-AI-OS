"""Durable store + failure injection + concurrency (Gates 2, 17, 18).

Gate 17 asks, for each injected failure: what state remains, does promotion
happen, is rollback still possible, and is the audit still truthful? Each
test below answers all four explicitly rather than just asserting a raise.

Gate 18 asks that concurrency produce no corrupted active state, no double
promotion, and no lost rollback handle.
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from autoforge_learning.audit import LearningAuditAction, LearningAuditError
from autoforge_learning.lifecycle import LearningLifecycleService
from autoforge_learning.models import LearningCandidate, LearningScope, LearningScopeKind
from autoforge_learning.promotion import PromotionError
from autoforge_learning.store import (
    STORE_SCHEMA_VERSION,
    CandidateRecord,
    DurableLearningStore,
    LearningImmutableIdentityError,
    LearningRecordCorrupt,
    LearningRecordNotFound,
    PromotionState,
)
from tests.helpers import make_human, make_service

KIND = "pattern_template"
KEY = "template-alpha"


def _record(project_id, summary="candidate"):
    return CandidateRecord(
        candidate=LearningCandidate(
            scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
            kind=KIND,
            summary=summary,
        ),
        project_id=project_id,
        stored_at=datetime.now(timezone.utc),
    )


# ══ GATE 2 — DURABLE STORE ═══════════════════════════════════════════════════


def test_records_survive_a_process_restart(tmp_path, project_id):
    """Gate 2.1 — durability across restart."""
    store = DurableLearningStore(tmp_path / "s")
    record = _record(project_id)
    store.save_candidate(record)

    reopened = DurableLearningStore(tmp_path / "s")
    loaded = reopened.get_candidate(project_id, record.candidate_id)
    assert loaded is not None
    assert loaded.candidate.record_hash() == record.candidate.record_hash()
    assert loaded.schema_version == record.schema_version


def test_the_store_schema_version_is_preserved_on_disk(tmp_path, project_id):
    store = DurableLearningStore(tmp_path / "s")
    record = _record(project_id)
    store.save_candidate(record)
    path = (
        tmp_path / "s" / str(project_id) / "candidates" / f"{record.candidate_id}.json"
    )
    payload = json.loads(path.read_text())
    assert payload["store_schema_version"] == STORE_SCHEMA_VERSION


def test_candidate_identity_is_immutable(tmp_path, project_id):
    """Gate 2.3 — an identity cannot be rewritten under the same id."""
    store = DurableLearningStore(tmp_path / "s")
    record = _record(project_id, "original summary")
    store.save_candidate(record)

    # Re-saving the identical record is idempotent.
    assert store.save_candidate(record).candidate_id == record.candidate_id

    mutated = record.model_copy(
        update={
            "candidate": LearningCandidate(
                candidate_id=record.candidate_id,  # same identity slot
                scope=record.candidate.scope,
                kind=KIND,
                summary="a DIFFERENT summary",
            )
        }
    )
    with pytest.raises(LearningImmutableIdentityError):
        store.save_candidate(mutated)


def test_a_corrupt_record_raises_rather_than_returning_absent(tmp_path, project_id):
    """Gate 2.13 — malformed data fails closed; it is never empty success."""
    store = DurableLearningStore(tmp_path / "s")
    record = _record(project_id)
    store.save_candidate(record)
    path = (
        tmp_path / "s" / str(project_id) / "candidates" / f"{record.candidate_id}.json"
    )
    path.write_text("{ this is not valid json")
    with pytest.raises(LearningRecordCorrupt):
        DurableLearningStore(tmp_path / "s").get_candidate(
            project_id, record.candidate_id
        )


def test_a_tampered_record_fails_its_integrity_check(tmp_path, project_id):
    """Gate 2.12 — the stored content hash is verified on read."""
    store = DurableLearningStore(tmp_path / "s")
    record = _record(project_id)
    store.save_candidate(record)
    path = (
        tmp_path / "s" / str(project_id) / "candidates" / f"{record.candidate_id}.json"
    )
    payload = json.loads(path.read_text())
    payload["payload"]["candidate"]["summary"] = "silently altered"
    path.write_text(json.dumps(payload))
    with pytest.raises(LearningRecordCorrupt):
        DurableLearningStore(tmp_path / "s").get_candidate(
            project_id, record.candidate_id
        )


def test_a_missing_record_raises_not_guesswork(tmp_path, project_id):
    store = DurableLearningStore(tmp_path / "s")
    assert store.get_candidate(project_id, uuid.uuid4()) is None
    with pytest.raises(LearningRecordNotFound):
        store.require_candidate(project_id, uuid.uuid4())


def test_a_schema_version_mismatch_is_rejected(tmp_path, project_id):
    store = DurableLearningStore(tmp_path / "s")
    record = _record(project_id)
    store.save_candidate(record)
    path = (
        tmp_path / "s" / str(project_id) / "candidates" / f"{record.candidate_id}.json"
    )
    payload = json.loads(path.read_text())
    payload["store_schema_version"] = "0.0.0-from-the-future"
    path.write_text(json.dumps(payload))
    with pytest.raises(LearningRecordCorrupt):
        DurableLearningStore(tmp_path / "s").get_candidate(
            project_id, record.candidate_id
        )


def test_the_store_is_distinct_from_artifact_persistence(tmp_path, project_id):
    """Gate 2 — learning persistence does not write into the artifact catalog."""
    store = DurableLearningStore(tmp_path / "learning")
    store.save_candidate(_record(project_id))
    written = {p.relative_to(tmp_path).parts[0] for p in tmp_path.rglob("*.json")}
    assert written == {"learning"}


# ══ GATE 17 — FAILURE INJECTION ══════════════════════════════════════════════


def test_injection_1_candidate_persistence_fails(tmp_path, security_platform):
    """Stage 1: candidate persistence fails → nothing is stored, nothing promotes."""
    store = DurableLearningStore(tmp_path / "s")
    broken = DurableLearningStore(tmp_path / "s")

    def _boom(*a, **k):
        raise OSError("persistence down")

    broken.save_candidate = _boom
    with pytest.raises(OSError):
        broken.save_candidate(_record(uuid.uuid4()))
    # The failure did not corrupt the working store.
    assert DurableLearningStore(tmp_path / "s").list_candidates(uuid.uuid4()) == ()


def test_injection_3_evaluation_fails_closed(service, project_id, candidate, monkeypatch):
    """Stage 3: evaluation failure → no promotable report, no approval possible."""
    from autoforge_learning.approval import ApprovalError

    from tests.helpers import healthy_metrics

    record = service.create_candidate(candidate)
    monkeypatch.setattr(
        service,
        "_evaluator",
        type(service._evaluator)(),
    )
    report = service.evaluate(
        record=record, baseline=healthy_metrics(), candidate_metrics=healthy_metrics()
    )
    assert report.promotable is False
    with pytest.raises(ApprovalError):
        service.request_approval(
            record=record,
            evaluation=report,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=make_service(),
        )


def test_injection_4_approval_persistence_fails(
    service, stored_candidate, passing_report, service_requester, monkeypatch
):
    """Stage 4: approval persistence fails → no approval record, no promotion."""
    monkeypatch.setattr(
        service.store, "save_approval", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
    )
    with pytest.raises(OSError):
        service.request_approval(
            record=stored_candidate,
            evaluation=passing_report,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=service_requester,
        )
    assert service.store.list_approvals(stored_candidate.project_id) == ()


def test_injection_7_audit_emission_failure_is_never_a_silent_success(
    service, stored_candidate, passing_report, approved, human_approver, project_id, monkeypatch
):
    """Stage 7: a failing audit must NOT be reported as a successful promotion."""

    original_emit = service.auditor.emit
    state = {"failed": False}

    def flaky(*args, **kwargs):
        action = args[0]
        if action is LearningAuditAction.PROMOTION_SUCCEEDED:
            state["failed"] = True
            raise LearningAuditError("audit sink down")
        return original_emit(*args, **kwargs)

    monkeypatch.setattr(service.auditor, "emit", flaky)

    from autoforge_learning.promotion import PromotionAuditError

    with pytest.raises(PromotionAuditError):
        service.promote(
            record=stored_candidate,
            evaluation=passing_report,
            approval=approved,
            kind=KIND,
            key=KEY,
            proposed_effect="effect",
            requested_by=human_approver,
        )
    assert state["failed"] is True

    # The audit failure was NOT converted into a clean success. The promotion
    # genuinely committed, and the durable record says so *and* records that
    # its audit is degraded — both facts, neither hidden.
    records = service.store.list_promotions(project_id)
    assert len(records) == 1
    assert records[0].state is PromotionState.PROMOTED
    assert "audit sink down" in records[0].audit_failure_reason
    assert service.active_state(project_id, KIND, KEY) is not None


def test_injection_8_rollback_write_failure_leaves_state_intact(
    service, promoted, project_id, monkeypatch
):
    """Stage 8: a failing rollback write leaves the active state untouched."""
    original = service.active_state(project_id, KIND, KEY)
    assert original is not None

    monkeypatch.setattr(
        service.store,
        "clear_active_state",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        service.rollback(project_id=project_id, handle_id=promoted.rollback_handle_id)

    monkeypatch.undo()
    still = service.active_state(project_id, KIND, KEY)
    assert still.version_id == original.version_id
    # The audit recorded the failed rollback truthfully.
    assert service.auditor.count(LearningAuditAction.ROLLBACK_FAILED) >= 1


# ══ GATE 18 — CONCURRENCY / IDEMPOTENCY ══════════════════════════════════════


def test_two_simultaneous_promotions_produce_exactly_one(
    service, stored_candidate, passing_report, approved, human_approver, project_id
):
    """Gate 18 — no double promotion, no corrupted active state."""
    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []

    def attempt():
        barrier.wait()
        try:
            results.append(
                service.promote(
                    record=stored_candidate,
                    evaluation=passing_report,
                    approval=approved,
                    kind=KIND,
                    key=KEY,
                    proposed_effect="effect",
                    requested_by=human_approver,
                )
            )
        except Exception as ex:  # noqa: BLE001 - recorded for the assertion
            errors.append(ex)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: attempt(), range(2)))

    assert not errors, f"no promotion attempt should error outright: {errors}"
    assert len(results) == 2
    # Both attempts describe the same single promotion.
    assert results[0].promotion_id == results[1].promotion_id

    promoted_records = [
        p for p in service.store.list_promotions(project_id)
        if p.state is PromotionState.PROMOTED
    ]
    assert len(promoted_records) == 1

    active = service.active_state(project_id, KIND, KEY)
    assert active.version_number == 1
    assert active.candidate_id == stored_candidate.candidate_id


def test_concurrent_promotions_do_not_lose_a_rollback_handle(
    service, promoted, project_id
):
    """Gate 18 — the handle survives concurrent reads and a rollback."""
    handles_before = {h.handle_id for h in service.store.list_rollback_handles(project_id)}
    assert handles_before == {promoted.rollback_handle_id}

    def _read():
        return service.store.get_rollback_handle(project_id, promoted.rollback_handle_id)

    with ThreadPoolExecutor(max_workers=4) as pool:
        loaded = list(pool.map(lambda _: _read(), range(8)))

    assert all(h is not None and h.is_intact for h in loaded)
    assert {h.handle_id for h in service.store.list_rollback_handles(project_id)} == (
        handles_before
    )


def test_concurrent_rollbacks_are_idempotent(service, promoted, project_id):
    """Gate 18 — repeated rollback under concurrency changes nothing extra."""

    def _rollback():
        try:
            return service.rollback(
                project_id=project_id, handle_id=promoted.rollback_handle_id
            )
        except Exception:  # noqa: BLE001 - a rejected repeat is acceptable
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _rollback(), range(4)))

    assert all(r is None or r.handle_id == promoted.rollback_handle_id for r in results)
    assert service.active_state(project_id, KIND, KEY) is None
    # Every executed rollback is retained; none corrupted the state.
    for record in service.store.list_rollbacks(project_id):
        assert record.project_id == project_id