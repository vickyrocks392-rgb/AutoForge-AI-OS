"""AutoForge Artifact Platform — Phase 12.

Canonical engineering artifact management, versioning, provenance,
lineage, publishing, and rollback.

Public API
----------
- ``ArtifactManager``       — central facade for all artifact operations.
- ``build_artifact_platform`` — factory constructing the full platform.
- ``ArtifactPlatformServices`` — DI container grouping all services.

Models:
- ``Artifact``              — canonical artifact with stable identity.
- ``ArtifactVersion``       — immutable artifact version.
- ``ArtifactLineageEntry``  — lineage relationship.
- ``PublicationRecord``     — publication record.
- ``RollbackRecord``        — rollback record.
- ``CanonicalProvenance``   — canonical provenance.
- ``CanonicalArtifactType`` — full artifact type taxonomy.
- ``ArtifactState``         — lifecycle state.

Errors:
- ``ArtifactError``         — base error.
- ``ArtifactValidationError``
- ``ArtifactNotFoundError``
- ``ArtifactConflictError``
- ``ArtifactIntegrityError``
- ``ArtifactAuthorizationError``
- ``ArtifactPublicationError``
- ``ArtifactRollbackError``
- ``ArtifactStorageError``

Store:
- ``ArtifactStoreProtocol`` — storage contract.
- ``LocalArtifactStore``    — in-memory implementation.
"""

from autoforge_artifacts.engine import (
    ArtifactManager,
    ArtifactPlatformServices,
    build_artifact_platform,
)
from autoforge_artifacts.errors import (
    ArtifactAuthorizationError,
    ArtifactConflictError,
    ArtifactError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactPublicationError,
    ArtifactRollbackError,
    ArtifactStorageError,
    ArtifactValidationError,
)
from autoforge_artifacts.models import (
    Artifact,
    ArtifactLineageEntry,
    ArtifactState,
    ArtifactVersion,
    CanonicalArtifactType,
    CanonicalProvenance,
    PublicationRecord,
    RollbackRecord,
)
from autoforge_artifacts.store import ArtifactStoreProtocol, LocalArtifactStore

__all__ = [
    # Engine
    "ArtifactManager",
    "ArtifactPlatformServices",
    "build_artifact_platform",
    # Models
    "Artifact",
    "ArtifactVersion",
    "ArtifactLineageEntry",
    "CanonicalProvenance",
    "CanonicalArtifactType",
    "ArtifactState",
    "PublicationRecord",
    "RollbackRecord",
    # Errors
    "ArtifactError",
    "ArtifactValidationError",
    "ArtifactNotFoundError",
    "ArtifactConflictError",
    "ArtifactIntegrityError",
    "ArtifactAuthorizationError",
    "ArtifactPublicationError",
    "ArtifactRollbackError",
    "ArtifactStorageError",
    # Store
    "ArtifactStoreProtocol",
    "LocalArtifactStore",
]
