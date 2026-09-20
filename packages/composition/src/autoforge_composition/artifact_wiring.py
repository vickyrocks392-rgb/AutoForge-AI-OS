"""Artifact Platform wiring — Phase 12.

Constructs the Artifact Platform and bridges it to the composition root.
No business logic lives here — only construction and connection.
"""

from __future__ import annotations

from typing import Any

from autoforge_artifacts.engine import (
    ArtifactPlatformServices,
    build_artifact_platform,
)
from autoforge_artifacts.events import ArtifactEventSinkProtocol
from autoforge_artifacts.policies import ArtifactPolicy
from autoforge_artifacts.store import ArtifactStoreProtocol


def build_artifact_platform_from_bus(
    *,
    canonical_bus: ArtifactEventSinkProtocol | None = None,
    policy: ArtifactPolicy | None = None,
    store: ArtifactStoreProtocol | None = None,
) -> ArtifactPlatformServices:
    """Construct the Artifact Platform wired to the canonical event bus.

    Parameters
    ----------
    canonical_bus
        The ``CanonicalEventBus`` instance (satisfies ``ArtifactEventSinkProtocol``
        structurally via its ``publish()`` method).
    policy
        Optional artifact governance policy.  Defaults to safe defaults.
    store
        Optional artifact store implementation (e.g. DurableArtifactStoreBridge).
    """
    return build_artifact_platform(
        event_sink=canonical_bus,
        policy=policy,
        store=store,
    )
