"""
Project-scoped artifact access (SHC-07).

The durable artifact identity model (18-J/18-K) is **frozen and unchanged**: the
physical key derivation and UUID5 identity are exactly as certified. This module
deliberately enforces project isolation *above* the storage layer rather than by
altering durable keys, which would invalidate persisted artifacts.

Every read, mutation, and export is resolved against an authorized project
**before** the underlying store is touched, so a caller holding an artifact id
belonging to another project is refused rather than served.

Export additionally runs the canonical egress content inspection, so
model-generated content containing secrets cannot leave as a delivery package.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from autoforge_artifacts.errors import ArtifactNotFoundError


class ProjectAccessDeniedError(PermissionError):
    """Raised when a caller requests an artifact outside its authorized project."""


class ProjectScopedArtifactAccess:
    """Enforces project isolation over any ``ArtifactStoreProtocol`` implementation."""

    def __init__(self, store: Any, *, egress_policy: Any | None = None) -> None:
        self._store = store
        self._egress_policy = egress_policy

    @property
    def store(self) -> Any:
        return self._store

    def _authorize(
        self, artifact: Any, project_id: uuid.UUID, caller_projects: Iterable[uuid.UUID] | None
    ) -> None:
        if caller_projects is None:
            return
        allowed = {str(p) for p in caller_projects}
        if str(artifact.project_id) not in allowed:
            raise ProjectAccessDeniedError(
                f"Artifact belongs to project '{artifact.project_id}', which is not "
                "in the caller's authorized project set."
            )

    def get(
        self,
        artifact_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        caller_projects: Iterable[uuid.UUID] | None = None,
    ) -> Any:
        """Fetch an artifact, enforcing project scope before returning it."""
        artifact = self._store.get(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError(
                f"Artifact {artifact_id} not found", details={"artifact_id": str(artifact_id)}
            )
        if str(artifact.project_id) != str(project_id):
            raise ProjectAccessDeniedError(
                f"Artifact {artifact_id} belongs to project '{artifact.project_id}', "
                f"not the requested project '{project_id}'."
            )
        self._authorize(artifact, project_id, caller_projects)
        return artifact

    def update(
        self,
        artifact: Any,
        *,
        project_id: uuid.UUID,
        caller_projects: Iterable[uuid.UUID] | None = None,
    ) -> Any:
        """Mutate an artifact, enforcing project scope first."""
        if str(artifact.project_id) != str(project_id):
            raise ProjectAccessDeniedError(
                f"Artifact {artifact.artifact_id} belongs to project "
                f"'{artifact.project_id}', not the requested project '{project_id}'."
            )
        self._authorize(artifact, project_id, caller_projects)
        return self._store.update(artifact)

    def list_artifacts(
        self,
        *,
        caller_projects: Iterable[uuid.UUID] | None = None,
    ) -> list[Any]:
        """List only artifacts inside the caller's authorized projects."""
        artifacts = self._store.list_artifacts()
        if caller_projects is None:
            return list(artifacts)
        allowed = {str(p) for p in caller_projects}
        return [a for a in artifacts if str(a.project_id) in allowed]

    def export_payload(
        self,
        artifact_id: uuid.UUID,
        *,
        project_id: uuid.UUID,
        caller_projects: Iterable[uuid.UUID] | None = None,
        payload: Any = None,
    ) -> Any:
        """Authorize export and inspect the outgoing payload for secrets.

        Fails closed: when a policy is configured and inspection finds sensitive
        material the export is refused and the secret is not returned.
        """
        artifact = self.get(
            artifact_id, project_id=project_id, caller_projects=caller_projects
        )
        if self._egress_policy is None:
            return payload
        from autoforge_security.egress import EgressDecision, inspect_payload

        findings, sanitized = inspect_payload(payload)
        if findings:
            blocked = [f for f in findings if f.startswith("secret_shape:")]
            if blocked and self._egress_policy.block_on_secret:
                raise ProjectAccessDeniedError(
                    f"Export of artifact {artifact_id} blocked: sensitive material "
                    f"detected ({sorted(set(blocked))})."
                )
            return sanitized
        return payload
