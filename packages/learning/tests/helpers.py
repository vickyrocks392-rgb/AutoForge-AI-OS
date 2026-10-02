"""Test helpers for the Phase 19B-2 promotion-path tests.

Kept in a plain importable module (rather than ``conftest``) so test files can
import the builders directly, matching the repository's existing
``tests/helpers.py`` convention.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_learning.evaluation import build_evidence_refs
from autoforge_learning.invariants import InvariantMetrics
from autoforge_learning.models import ValidationTruth
from autoforge_security.models import Subject, SubjectType
from autoforge_security.roles import Roles

#: The certified role that carries ``Permissions.GOVERNANCE_APPROVE``. Taken
#: from the RBAC table rather than invented, so the tests exercise the real
#: permission check in ``SecurityPlatform.submit_approval_decision``.
GOVERNANCE_ROLE = Roles.REVIEWER


def healthy_metrics(**overrides: Any) -> InvariantMetrics:
    """Metrics that pass every *required* invariant."""
    base: dict[str, Any] = dict(
        security_violations=0,
        validation_truth=ValidationTruth.PASSED,
        review_approved=True,
        completion_succeeded=True,
        tests_total=10,
        tests_passed=10,
        tests_failed=0,
        tests_errors=0,
        failure_rate=0.0,
        retry_rate=0.0,
        latency_ms=100.0,
        isolation_violations=0,
        cross_project_access_attempts=0,
    )
    base.update(overrides)
    return InvariantMetrics(**base)


def empty_metrics() -> InvariantMetrics:
    """Every measurement absent. The default for a fresh candidate."""
    return InvariantMetrics()


def evidence_payload_for(metrics: InvariantMetrics, project_id: uuid.UUID) -> tuple:
    """Build a complete evidence bundle for ``metrics``.

    Only measured fields are emitted — an unmeasured metric produces no
    reference at all, which is exactly how absence must be represented. A
    ``validation_truth`` of ``UNAVAILABLE`` is itself an absence, so it
    produces no PI-2 reference either.
    """
    validation = metrics.validation_truth
    payload: dict[str, dict[str, Any]] = {
        "PI-1": {"security_violations": metrics.security_violations},
        "PI-3": {"review_approved": metrics.review_approved},
        "PI-4": {"completion_succeeded": metrics.completion_succeeded},
        "PI-5": {
            "tests_total": metrics.tests_total,
            "tests_passed": metrics.tests_passed,
        },
        "PI-6": {"failure_rate": metrics.failure_rate, "retry_rate": metrics.retry_rate},
        "PI-7": {"latency_ms": metrics.latency_ms},
        "PI-9": {
            "isolation_violations": metrics.isolation_violations,
            "cross_project_access_attempts": metrics.cross_project_access_attempts,
        },
    }
    if validation is not ValidationTruth.UNAVAILABLE:
        payload["PI-2"] = {"validation_truth": validation.value}
    cleaned = {
        inv: {k: v for k, v in fields.items() if v is not None}
        for inv, fields in payload.items()
    }
    return tuple(build_evidence_refs(cleaned, project_id=project_id))


def make_human(subject_id: str = "human.approver.19b2") -> Subject:
    return Subject(
        subject_id=subject_id,
        display_name="19B-2 Approver",
        subject_type=SubjectType.HUMAN,
        roles=frozenset({GOVERNANCE_ROLE}),
        attributes={"department": "platform-governance"},
    )


def make_service(subject_id: str = "service.learning.19b2", *, with_governance_role: bool = False) -> Subject:
    """A non-human service principal.

    ``with_governance_role`` lets a test prove that *subject type* is the
    blocker, independent of RBAC: a service holding the governance role is
    still refused.
    """
    return Subject(
        subject_id=subject_id,
        display_name="AutoForge Learning",
        subject_type=SubjectType.SERVICE,
        roles=frozenset({GOVERNANCE_ROLE}) if with_governance_role else frozenset(),
    )


def make_worker(subject_id: str = "worker.19b2") -> Subject:
    """An AI/worker principal. Carries the role but is not a human."""
    return Subject(
        subject_id=subject_id,
        display_name="Worker",
        subject_type=SubjectType.WORKER,
        roles=frozenset({GOVERNANCE_ROLE}),
    )


__all__ = [
    "GOVERNANCE_ROLE",
    "empty_metrics",
    "evidence_payload_for",
    "healthy_metrics",
    "make_human",
    "make_service",
    "make_worker",
]