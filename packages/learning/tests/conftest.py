"""Shared fixtures for the Phase 19B-2 promotion-path tests.

The fixtures deliberately build the REAL certified components —
``SecurityPlatform`` with its guardrails, HITL manager, governance engine and
audit engine — so the tests exercise the production boundary rather than a
stub that could drift from it.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning.lifecycle import LearningLifecycleService
from autoforge_learning.models import (
    LearningCandidate,
    LearningScope,
    LearningScopeKind,
)
from autoforge_security.engine import SecurityPlatform
from tests.helpers import (
    evidence_payload_for,
    healthy_metrics,
    make_human,
    make_service,
    make_worker,
)


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def other_project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def security_platform() -> SecurityPlatform:
    return SecurityPlatform()


@pytest.fixture()
def service(tmp_path, security_platform) -> LearningLifecycleService:
    return LearningLifecycleService.build(
        store_root=tmp_path / "learning-store",
        security_platform=security_platform,
    )


@pytest.fixture()
def human_approver():
    return make_human()


@pytest.fixture()
def service_requester():
    """The non-human principal that requests approval. Never approves."""
    return make_service()


@pytest.fixture()
def worker_subject():
    """An AI/worker principal — must never be able to approve."""
    return make_worker()


@pytest.fixture()
def baseline_metrics():
    return healthy_metrics()


@pytest.fixture()
def passing_metrics():
    return healthy_metrics(latency_ms=90.0)


@pytest.fixture()
def passing_evidence(passing_metrics, project_id):
    return evidence_payload_for(passing_metrics, project_id)


@pytest.fixture()
def candidate(project_id) -> LearningCandidate:
    return LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind="pattern_template",
        summary="Prefer the project's established template for this task type.",
        rationale="Derived from completed executions in this project.",
    )


@pytest.fixture()
def stored_candidate(service, candidate, passing_evidence):
    record = service.create_candidate(candidate)
    return service.record_evidence(record, passing_evidence)


@pytest.fixture()
def passing_report(service, stored_candidate, baseline_metrics, passing_metrics):
    return service.evaluate(
        record=stored_candidate,
        baseline=baseline_metrics,
        candidate_metrics=passing_metrics,
    )


KIND = "pattern_template"
KEY = "template-alpha"
EFFECT = "Use the learned template for this project's task type"


@pytest.fixture()
def approved(
    service,
    stored_candidate,
    passing_report,
    service_requester,
    human_approver,
):
    """A fully approved, ready-to-promote candidate."""
    approval = service.request_approval(
        record=stored_candidate,
        evaluation=passing_report,
        kind=KIND,
        key=KEY,
        proposed_effect=EFFECT,
        requested_by=service_requester,
    )
    return service.approvals.record_decision(
        approval=approval,
        approver=human_approver,
        approve=True,
        reason="Reviewed evidence and invariants; approved.",
    )


@pytest.fixture()
def promoted(
    service,
    stored_candidate,
    passing_report,
    approved,
    human_approver,
):
    return service.promote(
        record=stored_candidate,
        evaluation=passing_report,
        approval=approved,
        kind=KIND,
        key=KEY,
        proposed_effect=EFFECT,
        requested_by=human_approver,
    )