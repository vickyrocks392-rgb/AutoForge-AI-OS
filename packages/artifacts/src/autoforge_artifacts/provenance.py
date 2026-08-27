"""Artifact provenance — Phase 12.

Canonical provenance assembly and Phase 10 adapter.

Design rules
------------
- Provenance captures who/what/when/from-what.
- No secrets in provenance metadata.
- Compatible with Phase 10 ``ArtifactProvenance``.
- Provenance is deterministic and immutable.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_artifacts.models import CanonicalProvenance


def build_provenance(
    *,
    task_id: str | None = None,
    worker_id: str | None = None,
    workflow_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    execution_id: str | None = None,
    review_id: str | None = None,
    parent_artifact_id: uuid.UUID | None = None,
    attempt_id: str | None = None,
    correlation_id: uuid.UUID | None = None,
    attempt_number: int = 1,
    iteration: int = 1,
    actor: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CanonicalProvenance:
    """Factory for constructing canonical provenance from available context.

    Only includes fields that are genuinely available.  Does not invent
    identifiers.
    """
    # Scrub any secrets from metadata.
    clean_metadata = _scrub_secrets(metadata or {})

    return CanonicalProvenance(
        task_id=task_id,
        worker_id=worker_id,
        workflow_id=workflow_id,
        project_id=project_id,
        execution_id=execution_id,
        review_id=review_id,
        parent_artifact_id=parent_artifact_id,
        attempt_id=attempt_id,
        correlation_id=correlation_id,
        attempt_number=attempt_number,
        iteration=iteration,
        actor=actor,
        metadata=clean_metadata,
    )


def from_execution_provenance(execution_prov: Any) -> CanonicalProvenance:
    """Adapt Phase 10's ``ArtifactProvenance`` to canonical provenance.

    Accepts any object with Phase 10 provenance attributes, extracting
    available fields without importing Phase 10 types (to keep the
    adapter loosely coupled).
    """
    workflow_id = getattr(execution_prov, "workflow_id", None)
    correlation_id = getattr(execution_prov, "correlation_id", None)
    raw_metadata = getattr(execution_prov, "metadata", None) or {}

    return build_provenance(
        task_id=getattr(execution_prov, "task_id", None),
        worker_id=getattr(execution_prov, "worker_id", None),
        workflow_id=workflow_id,
        correlation_id=correlation_id,
        attempt_number=getattr(execution_prov, "attempt_number", 1),
        iteration=getattr(execution_prov, "iteration", 1),
        metadata=raw_metadata,
    )


# Secret patterns to scrub from provenance metadata.
_SECRET_KEYS = frozenset({
    "password", "secret", "token", "api_key", "apikey",
    "credential", "private_key", "access_key", "auth",
})


def _scrub_secrets(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove any keys that look like secrets from metadata.

    Prevents accidental secret leakage through provenance.
    """
    return {
        k: v for k, v in metadata.items()
        if k.lower() not in _SECRET_KEYS
    }
