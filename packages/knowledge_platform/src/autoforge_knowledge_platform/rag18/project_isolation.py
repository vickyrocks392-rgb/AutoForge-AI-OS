"""
AutoForge AI — Qdrant Project Isolation & Knowledge Partitioning Engine
Ensures strong isolation between project-scoped vector stores and global engineering knowledge.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set
from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger("autoforge.knowledge.project_isolation")

GLOBAL_KNOWLEDGE_COLLECTION = "autoforge_global_knowledge"


class QdrantProjectIsolationManager:
    """
    Manages project-scoped Qdrant collections, cross-project retrieval barriers,
    and distinct global knowledge repositories.
    """

    def __init__(self, client: QdrantClient, global_collection: str = GLOBAL_KNOWLEDGE_COLLECTION):
        self.client = client
        self.global_collection = global_collection

    def get_project_collection_name(self, project_id: str, namespace: str = "knowledge") -> str:
        """Derives canonical project collection name."""
        clean_pid = project_id.replace("-", "_").lower()
        clean_ns = namespace.replace("-", "_").lower()
        return f"project_{clean_pid}_{clean_ns}"

    def ensure_project_collection(
        self,
        project_id: str,
        vector_size: int = 4,
        distance: models.Distance = models.Distance.COSINE,
        namespace: str = "knowledge",
    ) -> str:
        """Creates an isolated project collection if it does not already exist."""
        col_name = self.get_project_collection_name(project_id, namespace)
        existing = {c.name for c in self.client.get_collections().collections}
        if col_name not in existing:
            self.client.create_collection(
                collection_name=col_name,
                vectors_config=models.VectorParams(size=vector_size, distance=distance),
            )
            logger.info(f"Created isolated Qdrant collection '{col_name}' for project '{project_id}'")
        return col_name

    def ensure_global_collection(
        self,
        vector_size: int = 4,
        distance: models.Distance = models.Distance.COSINE,
    ) -> str:
        """Creates the permanent global knowledge repository if it does not already exist."""
        existing = {c.name for c in self.client.get_collections().collections}
        if self.global_collection not in existing:
            self.client.create_collection(
                collection_name=self.global_collection,
                vectors_config=models.VectorParams(size=vector_size, distance=distance),
            )
            logger.info(f"Created global knowledge Qdrant collection '{self.global_collection}'")
        return self.global_collection

    def insert_project_knowledge(
        self,
        project_id: str,
        points: List[Dict[str, Any]],
        namespace: str = "knowledge",
    ) -> int:
        """Inserts vector points strictly tagged with project ownership into project collection."""
        col_name = self.ensure_project_collection(project_id, namespace=namespace)
        qdrant_points = []
        for p in points:
            pid = p.get("id") or p.get("point_id")
            vec = p["vector"]
            payload = dict(p.get("payload", {}))
            payload["project_id"] = project_id
            payload["is_global"] = False
            qdrant_points.append(models.PointStruct(id=pid, vector=vec, payload=payload))

        self.client.upsert(collection_name=col_name, points=qdrant_points)
        return len(qdrant_points)

    def insert_global_knowledge(self, points: List[Dict[str, Any]]) -> int:
        """Inserts permanent, cross-project global modernization patterns into global store."""
        col_name = self.ensure_global_collection()
        qdrant_points = []
        for p in points:
            pid = p.get("id") or p.get("point_id")
            vec = p["vector"]
            payload = dict(p.get("payload", {}))
            payload["is_global"] = True
            qdrant_points.append(models.PointStruct(id=pid, vector=vec, payload=payload))

        self.client.upsert(collection_name=col_name, points=qdrant_points)
        return len(qdrant_points)

    def query_project_knowledge(
        self,
        project_id: str,
        query_vector: List[float],
        top_k: int = 5,
        namespace: str = "knowledge",
    ) -> List[Dict[str, Any]]:
        """
        Queries project-scoped collection with mandatory project_id filter.
        Guarantees that no cross-project contamination is possible.
        """
        col_name = self.get_project_collection_name(project_id, namespace)
        existing = {c.name for c in self.client.get_collections().collections}
        if col_name not in existing:
            return []

        # Filter strictly on project_id
        project_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="project_id",
                    match=models.MatchValue(value=project_id),
                )
            ]
        )

        float_query = [float(v) for v in query_vector]
        if hasattr(self.client, "query_points"):
            res = self.client.query_points(
                collection_name=col_name,
                query=float_query,
                query_filter=project_filter,
                limit=top_k,
                with_payload=True,
            )
            raw_points = getattr(res, "points", []) or []
        else:
            raw_points = self.client.search(
                collection_name=col_name,
                query_vector=float_query,
                query_filter=project_filter,
                limit=top_k,
            )

        hits = []
        for hit in raw_points:
            hits.append({
                "id": hit.id,
                "score": float(getattr(hit, "score", 0.0) or 0.0),
                "payload": getattr(hit, "payload", {}) or {},
            })
        return hits

    def query_global_knowledge(
        self,
        query_vector: List[float],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Queries shared global engineering patterns."""
        existing = {c.name for c in self.client.get_collections().collections}
        if self.global_collection not in existing:
            return []

        float_query = [float(v) for v in query_vector]
        if hasattr(self.client, "query_points"):
            res = self.client.query_points(
                collection_name=self.global_collection,
                query=float_query,
                limit=top_k,
                with_payload=True,
            )
            raw_points = getattr(res, "points", []) or []
        else:
            raw_points = self.client.search(
                collection_name=self.global_collection,
                query_vector=float_query,
                limit=top_k,
            )

        hits = []
        for hit in raw_points:
            hits.append({
                "id": hit.id,
                "score": float(getattr(hit, "score", 0.0) or 0.0),
                "payload": getattr(hit, "payload", {}) or {},
            })
        return hits

    def purge_project_collection(self, project_id: str, namespace: str = "knowledge") -> bool:
        """Deletes the project collection completely from Qdrant."""
        col_name = self.get_project_collection_name(project_id, namespace)
        existing = {c.name for c in self.client.get_collections().collections}
        if col_name in existing:
            self.client.delete_collection(collection_name=col_name)
            logger.info(f"Purged project Qdrant collection '{col_name}'")
            return True
        return False

    def inventory_collections(self) -> Dict[str, Any]:
        """Provides an audit of all active collections partitioned by project and global."""
        cols = self.client.get_collections().collections
        project_cols = []
        global_cols = []
        orphaned_cols = []

        for c in cols:
            name = c.name
            try:
                info = self.client.get_collection(name)
                pts = getattr(info, "points_count", 0) or getattr(info, "vectors_count", 0)
            except Exception:
                pts = 0

            entry = {"name": name, "points_count": pts}
            if name.startswith("project_"):
                project_cols.append(entry)
            elif name.startswith("global_") or name == self.global_collection:
                global_cols.append(entry)
            else:
                orphaned_cols.append(entry)

        return {
            "total_collections": len(cols),
            "project_scoped": project_cols,
            "global_knowledge": global_cols,
            "orphaned_legacy": orphaned_cols,
        }
