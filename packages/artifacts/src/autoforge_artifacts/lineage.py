"""Artifact lineage — Phase 12.

Manages parent→child derivation relationships between artifacts.
Uses an in-memory adjacency list representation — not a graph database.

Design rules
------------
- Lineage is explicit and queryable.
- Supports the full engineering lifecycle chain.
- Ancestor/descendant traversal is deterministic BFS.
- No AI controls lineage relationships.
"""

from __future__ import annotations

import uuid
from collections import deque

from autoforge_artifacts.models import ArtifactLineageEntry
from autoforge_artifacts.store import ArtifactStoreProtocol


class LineageService:
    """Manages artifact lineage graph traversal and recording."""

    def __init__(self, store: ArtifactStoreProtocol) -> None:
        self._store = store

    def record_lineage(self, entry: ArtifactLineageEntry) -> None:
        """Record a parent→child derivation relationship."""
        self._store.store_lineage(entry)

    def get_parents(self, artifact_id: uuid.UUID) -> list[ArtifactLineageEntry]:
        """Get direct parents of an artifact."""
        return self._store.get_lineage_parents(artifact_id)

    def get_children(self, artifact_id: uuid.UUID) -> list[ArtifactLineageEntry]:
        """Get direct children of an artifact."""
        return self._store.get_lineage_children(artifact_id)

    def get_ancestors(self, artifact_id: uuid.UUID) -> list[ArtifactLineageEntry]:
        """BFS traversal to find all ancestors (transitive parents).

        Returns entries ordered by discovery (breadth-first).
        """
        visited: set[uuid.UUID] = {artifact_id}
        result: list[ArtifactLineageEntry] = []
        queue: deque[uuid.UUID] = deque([artifact_id])

        while queue:
            current = queue.popleft()
            parents = self._store.get_lineage_parents(current)
            for entry in parents:
                result.append(entry)
                if entry.parent_artifact_id not in visited:
                    visited.add(entry.parent_artifact_id)
                    queue.append(entry.parent_artifact_id)

        return result

    def get_descendants(self, artifact_id: uuid.UUID) -> list[ArtifactLineageEntry]:
        """BFS traversal to find all descendants (transitive children).

        Returns entries ordered by discovery (breadth-first).
        """
        visited: set[uuid.UUID] = {artifact_id}
        result: list[ArtifactLineageEntry] = []
        queue: deque[uuid.UUID] = deque([artifact_id])

        while queue:
            current = queue.popleft()
            children = self._store.get_lineage_children(current)
            for entry in children:
                result.append(entry)
                if entry.child_artifact_id not in visited:
                    visited.add(entry.child_artifact_id)
                    queue.append(entry.child_artifact_id)

        return result

    def get_lineage_chain(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]:
        """Get the full lineage chain (ancestors + descendants)."""
        ancestors = self.get_ancestors(artifact_id)
        descendants = self.get_descendants(artifact_id)
        return ancestors + descendants
