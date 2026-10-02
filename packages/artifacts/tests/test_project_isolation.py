"""
Adversarial tests for project-scoped artifact access (SHC-07 / SHC-08).

Proves that durable artifact identity is preserved (frozen 18-J/18-K semantics)
while cross-project retrieval, mutation, listing and export are refused, and
that generated content carrying secrets cannot be exported.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_artifacts.errors import ArtifactNotFoundError
from autoforge_artifacts.scoped_access import (
    ProjectAccessDeniedError,
    ProjectScopedArtifactAccess,
)
from autoforge_artifacts.store import LocalArtifactStore
from autoforge_security.egress import EgressPolicy

from autoforge_artifacts.models import (
    Artifact,
    CanonicalArtifactType,
    ArtifactState,
)


def _artifact(project_id: uuid.UUID, name: str = "art") -> Artifact:
    return Artifact(
        artifact_id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        artifact_type=CanonicalArtifactType.SOURCE,
        state=ArtifactState.CREATED,
    )


@pytest.fixture
def store() -> LocalArtifactStore:
    return LocalArtifactStore()


def test_cross_project_read_is_denied(store: LocalArtifactStore) -> None:
    alpha, beta = uuid.uuid4(), uuid.uuid4()
    art = store.create(_artifact(alpha))
    access = ProjectScopedArtifactAccess(store)
    with pytest.raises(ProjectAccessDeniedError):
        access.get(art.artifact_id, project_id=beta)


def test_cross_project_mutation_is_denied(store: LocalArtifactStore) -> None:
    alpha, beta = uuid.uuid4(), uuid.uuid4()
    art = store.create(_artifact(alpha))
    access = ProjectScopedArtifactAccess(store)
    with pytest.raises(ProjectAccessDeniedError):
        access.update(art, project_id=beta)
    # The stored artifact must be unchanged.
    assert store.get(art.artifact_id).name == art.name


def test_authorized_project_can_read(store: LocalArtifactStore) -> None:
    alpha = uuid.uuid4()
    art = store.create(_artifact(alpha))
    access = ProjectScopedArtifactAccess(store)
    assert access.get(art.artifact_id, project_id=alpha).artifact_id == art.artifact_id


def test_caller_project_set_is_enforced(store: LocalArtifactStore) -> None:
    alpha, beta = uuid.uuid4(), uuid.uuid4()
    art = store.create(_artifact(beta))
    access = ProjectScopedArtifactAccess(store)
    with pytest.raises(ProjectAccessDeniedError):
        access.get(art.artifact_id, project_id=beta, caller_projects=[alpha])


def test_listing_is_filtered_to_caller_projects(store: LocalArtifactStore) -> None:
    alpha, beta = uuid.uuid4(), uuid.uuid4()
    store.create(_artifact(alpha, "a-art"))
    store.create(_artifact(beta, "b-art"))
    access = ProjectScopedArtifactAccess(store)
    visible = access.list_artifacts(caller_projects=[alpha])
    assert [a.name for a in visible] == ["a-art"]


def test_missing_artifact_raises_not_found(store: LocalArtifactStore) -> None:
    access = ProjectScopedArtifactAccess(store)
    with pytest.raises(ArtifactNotFoundError):
        access.get(uuid.uuid4(), project_id=uuid.uuid4())


def test_export_scans_payload_for_secrets(store: LocalArtifactStore) -> None:
    alpha = uuid.uuid4()
    art = store.create(_artifact(alpha))
    access = ProjectScopedArtifactAccess(store, egress_policy=EgressPolicy())
    payload = {"files": {"app.py": 'KEY = "AKIAIOSFODNN7EXAMPLE"'}}
    with pytest.raises(ProjectAccessDeniedError) as exc:
        access.export_payload(
            art.artifact_id, project_id=alpha, payload=payload
        )
    assert "blocked" in str(exc.value)


def test_export_allows_clean_generated_source(store: LocalArtifactStore) -> None:
    alpha = uuid.uuid4()
    art = store.create(_artifact(alpha))
    access = ProjectScopedArtifactAccess(store, egress_policy=EgressPolicy())
    payload = {"files": {"app.py": "print('hello world')"}}
    assert access.export_payload(
        art.artifact_id, project_id=alpha, payload=payload
    ) == payload


def test_export_is_refused_cross_project(store: LocalArtifactStore) -> None:
    alpha, beta = uuid.uuid4(), uuid.uuid4()
    art = store.create(_artifact(alpha))
    access = ProjectScopedArtifactAccess(store, egress_policy=EgressPolicy())
    with pytest.raises(ProjectAccessDeniedError):
        access.export_payload(
            art.artifact_id, project_id=beta, payload={"files": {}}
        )


def test_durable_identity_semantics_unchanged(store: LocalArtifactStore) -> None:
    """The scoped layer must not alter durable artifact identity."""
    alpha = uuid.uuid4()
    art = store.create(_artifact(alpha))
    access = ProjectScopedArtifactAccess(store)
    fetched = access.get(art.artifact_id, project_id=alpha)
    assert fetched.artifact_id == art.artifact_id
    assert fetched.project_id == alpha


def test_two_projects_same_name_do_not_collide(store: LocalArtifactStore) -> None:
    """Cross-project isolation holds even for identical artifact names."""
    alpha, beta = uuid.uuid4(), uuid.uuid4()
    a1 = store.create(_artifact(alpha, "report"))
    b1 = store.create(_artifact(beta, "report"))
    access = ProjectScopedArtifactAccess(store)
    assert access.get(a1.artifact_id, project_id=alpha).project_id == alpha
    with pytest.raises(ProjectAccessDeniedError):
        access.get(a1.artifact_id, project_id=beta)
    assert access.get(b1.artifact_id, project_id=beta).project_id == beta
