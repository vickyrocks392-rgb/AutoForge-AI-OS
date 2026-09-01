"""Phase 18-D — Qdrant local KnowledgeStore backend.

Production path uses the self-hosted local Qdrant server bound to 127.0.0.1
(Rust, real HNSW index, persistent local disk). Development/tests may use the
embedded pure-Python local mode via ``qdrant_path``.

The store never contacts a cloud/hosted Qdrant endpoint. ``_assert_local_url``
rejects any non-localhost URL at construction time.
"""

from __future__ import annotations

from pathlib import Path
import logging
import time
from typing import Any
from urllib.parse import urlparse

from autoforge_knowledge_platform.rag18.config import DEFAULT_COLLECTION_NAME, KnowledgeConfig
from autoforge_knowledge_platform.rag18.errors import (
    IncompatibleEmbeddingModelError,
    VectorStoreUnavailableError,
)
from autoforge_knowledge_platform.rag18.models import KnowledgeChunk, RetrievalScope
from autoforge_knowledge_platform.rag18.store import (
    KnowledgeStore,
    KnowledgeStoreHealth,
    ScoredStoreHit,
)

logger = logging.getLogger(__name__)
_LOCALHOSTS = {"127.0.0.1", "localhost", "::1"}

def _assert_local_url(url):
    if not url:
        return
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname not in _LOCALHOSTS:
        raise VectorStoreUnavailableError(
            f"Qdrant URL ''{url}'' resolves to non-local host ''{parsed.hostname}''. "
            "Phase 18-D requires a local vector database."
        )


def _scope_conditions(scope):
    from qdrant_client import models
    conditions = []
    for field, value in (
        ('project_id', scope.project_id),
        ('workflow_id', scope.workflow_id),
        ('execution_id', scope.execution_id),
        ('workspace_root', scope.workspace_root),
    ):
        if value is not None:
            if field == 'workspace_root':
                value = str(Path(value).resolve())  # normalize symlinks
            conditions.append(
                models.FieldCondition(
                    key=field,
                    match=models.MatchValue(value=str(value))
                )
            )
    return conditions


def _deleted_count(result):
    try:
        value = getattr(result, 'status', None)
        if value is None:
            value = result
        if isinstance(value, dict) and 'deleted' in value:
            return int(value['deleted'])
        if isinstance(value, str):
            return -1
        return -1
    except Exception:
        return -1
class QdrantKnowledgeStore(KnowledgeStore):
    '''Persistent local Qdrant-backed knowledge store.'''

    def __init__(
        self,
        config=None,
        *,
        url=None,
        path=None,
        collection_name=DEFAULT_COLLECTION_NAME,
        timeout_seconds=30.0,
    ):
        cfg = config or KnowledgeConfig()
        _assert_local_url(url or cfg.qdrant_url)
        self._url = url or cfg.qdrant_url
        self._path = path or cfg.qdrant_path
        self._collection = collection_name or cfg.collection_name
        self._timeout = timeout_seconds or cfg.qdrant_timeout_seconds
        self._client = None
        self._expected_dimension = None

    def _lazy_client(self):
        if self._client is not None:
            return self._client
        from qdrant_client import QdrantClient
        # URL (HTTP/server) takes priority over embedded path — callers that set
        # both get the HTTP endpoint, which is the standard production configuration.
        if self._url:
            self._client = QdrantClient(url=self._url, timeout=self._timeout)
        elif self._path:
            self._client = QdrantClient(path=self._path)
        else:
            raise VectorStoreUnavailableError('Neither qdrant url nor path configured')
        return self._client

    @property
    def backend_name(self):
        return 'qdrant-local-server' if self._url else 'qdrant-local-embedded'

    @property
    def collection_name(self):
        return self._collection

    async def set_expected_dimension(self, dimension):
        self._expected_dimension = int(dimension)

    async def initialize(self):
        from qdrant_client import models
        client = self._lazy_client()
        try:
            exists = client.collection_exists(self._collection)
        except Exception as exc:
            raise VectorStoreUnavailableError(
                f'Local Qdrant is unavailable at {self._url or self._path}: {exc}'
            ) from exc
        if exists:
            dim = await self.vector_dimension()
            if (
                self._expected_dimension is not None
                and dim is not None
                and dim != self._expected_dimension
            ):
                raise IncompatibleEmbeddingModelError(
                    f'Vector collection ''{self._collection}'' has dimension {dim} '
                    f'but embedding model expects {self._expected_dimension}. '
                    'Reindex explicitly before use.'
                )
            return
        dimension = self._expected_dimension or 768
        # Use HnswConfigDiff (sparse diff) instead of HnswConfig (full) for the
        # remote create_collection API. HnswConfig requires full_scan_threshold,
        # which the remote schema doesn't accept as a real value.
        client.create_collection(
            collection_name=self._collection,
            vectors_config=models.VectorParams(
                size=dimension,
                distance=models.Distance.COSINE,
            ),
            hnsw_config=models.HnswConfigDiff(
                m=16,
                ef_construct=100,
                full_scan_threshold=20000,
            ),
        )

    async def upsert_chunks(self, chunks, vectors):
        from autoforge_knowledge_platform.rag18.hashing import vector_point_id
        from qdrant_client.models import PointStruct
        if len(chunks) != len(vectors):
            raise ValueError('chunks and vectors length mismatch')
        if not chunks:
            return 0
        client = self._lazy_client()
        points = [
            PointStruct(
                id=vector_point_id(chunk.knowledge_id),
                vector=[float(v) for v in vector],
                payload=chunk.payload(),
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        for start in range(0, len(points), 128):
            client.upsert(
                collection_name=self._collection,
                points=points[start : start + 128]
            )
        return len(points)

    async def query(
        self,
        query_vector,
        scope,
        *,
        top_k,
        score_threshold=None,
        content_max_chars=1400,
        offset=0,
    ):
        from qdrant_client import models
        client = self._lazy_client()
        conditions = _scope_conditions(scope)
        query_filter = models.Filter(must=conditions) if conditions else None
        try:
            response = client.query_points(
                collection_name=self._collection,
                query=[float(v) for v in query_vector],
                query_filter=query_filter,
                limit=top_k,
                offset=offset,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise VectorStoreUnavailableError(
                f'Local Qdrant query failed: {exc}'
            ) from exc
        hits = []
        for pt in getattr(response, 'points', []) or []:
            payload = getattr(pt, 'payload', {}) or {}
            content = payload.get('content', '') or ''
            if content_max_chars and len(content) > content_max_chars:
                content = content[:content_max_chars]
            hits.append(
                ScoredStoreHit(
                    knowledge_id=payload.get('knowledge_id') or payload.get('chunk_id', ''),
                    source_id=payload.get('source_id', ''),
                    path=payload.get('path', ''),
                    content=content,
                    score=float(getattr(pt, 'score', 0.0) or 0.0),
                    metadata={
                        'chunk_id': payload.get('chunk_id'),
                        'project_id': payload.get('project_id'),
                        'workflow_id': payload.get('workflow_id'),
                        'execution_id': payload.get('execution_id'),
                        'workspace_root': payload.get('workspace_root'),
                        'document_type': payload.get('document_type'),
                        'language': payload.get('language'),
                        'start_line': payload.get('start_line'),
                        'end_line': payload.get('end_line'),
                    },
                )
            )
        return hits

    async def delete_by_source(self, source_id):
        from qdrant_client import models
        client = self._lazy_client()
        conditions = [
            models.FieldCondition(
                key='source_id',
                match=models.MatchValue(value=str(source_id))
            )
        ]
        selector = models.FilterSelector(filter=models.Filter(must=conditions))
        result = client.delete(
            collection_name=self._collection,
            points_selector=selector
        )
        return _deleted_count(result)

    async def delete_by_filter(self, payload_filter):
        from qdrant_client import models
        client = self._lazy_client()
        conditions = [
            models.FieldCondition(
                key=str(key),
                match=models.MatchValue(value=str(value))
            )
            for key, value in payload_filter.items()
        ]
        selector = models.FilterSelector(filter=models.Filter(must=conditions))
        result = client.delete(
            collection_name=self._collection,
            points_selector=selector
        )
        return _deleted_count(result)

    async def count(self, scope=None):
        from qdrant_client import models
        client = self._lazy_client()
        if scope is None:
            return int(client.count(collection_name=self._collection).count)
        conditions = _scope_conditions(scope)
        response = client.count(
            collection_name=self._collection,
            count_filter=models.Filter(must=conditions) if conditions else None,
        )
        return int(response.count)

    async def vector_dimension(self):
        try:
            client = self._lazy_client()
            if not client.collection_exists(self._collection):
                return None
            info = client.get_collection(self._collection)
            params = getattr(getattr(info, 'config', None), 'params', None)
            vectors = getattr(params, 'vectors', None)
            size = getattr(vectors, 'size', None)
            return int(size) if size is not None else None
        except Exception as exc:
            logger.debug('vector_dimension probe failed: %s', exc)
            return None

    async def health(self):
        started = time.perf_counter()
        try:
            client = self._lazy_client()
            exists = client.collection_exists(self._collection)
            points = 0
            if exists:
                info = client.get_collection(self._collection)
                points = int(getattr(info, 'points_count', 0) or 0)
            return KnowledgeStoreHealth(
                ok=bool(exists),
                backend=self.backend_name,
                collection=self._collection,
                points_count=points,
                error=None if exists else 'collection missing',
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )
        except Exception as exc:
            return KnowledgeStoreHealth(
                ok=False,
                backend=self.backend_name,
                collection=self._collection,
                error=str(exc),
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

    async def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

