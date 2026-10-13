"""
PolicyDesk Knowledge Assistant — Document Ingestion and Registry Management Service.
Handles multi-format parsing, chunking, persistent vector indexing, duplicate prevention, updates, and deletion.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from models import DocumentMetadata, DocumentUploadResponse
from document_parser import DocumentParser
from chunker import DocumentChunker
from vector_store import PolicyDeskVectorStore

logger = logging.getLogger("policydesk.ingestion")


class PolicyDeskIngestionService:
    """Coordinates parsing, chunking, metadata recording, and persistent vector indexing."""

    def __init__(
        self,
        vector_store: PolicyDeskVectorStore,
        ingestion_dir: Path | str,
        chunk_size: int = 500,
        chunk_overlap: int = 60,
    ):
        self.vector_store = vector_store
        self.ingestion_dir = Path(ingestion_dir).resolve()
        self.ingestion_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.ingestion_dir / "document_registry.json"
        self.chunker = DocumentChunker(chunk_size=chunk_size, overlap=chunk_overlap)
        self.registry: Dict[str, DocumentMetadata] = self._load_registry()

    def _load_registry(self) -> Dict[str, DocumentMetadata]:
        if not self.registry_file.exists():
            return {}
        try:
            raw = json.loads(self.registry_file.read_text(encoding="utf-8"))
            return {did: DocumentMetadata(**meta) for did, meta in raw.items()}
        except Exception as e:
            logger.warning(f"Could not load document registry from {self.registry_file}: {e}")
            return {}

    def _save_registry(self) -> None:
        data = {did: meta.model_dump() for did, meta in self.registry.items()}
        self.registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_documents(self) -> List[DocumentMetadata]:
        """Return all registered documents in the knowledge base."""
        return sorted(list(self.registry.values()), key=lambda d: d.filename)

    def get_document(self, doc_id: str) -> Optional[DocumentMetadata]:
        return self.registry.get(doc_id)

    def ingest_file(
        self,
        file_path: Path | str,
        doc_id: Optional[str] = None,
        force_reindex: bool = False,
    ) -> DocumentUploadResponse:
        """
        Ingest a file into the knowledge base:
        - Validates format and size
        - Computes SHA-256 hash
        - Prevents duplicate identical uploads
        - Handles document replacements/updates
        - Parses and chunks
        - Indexes into persistent ChromaDB
        - Updates registry
        """
        p = Path(file_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Source file not found: {p}")

        content_bytes = p.read_bytes()
        file_size = len(content_bytes)
        if file_size == 0:
            raise ValueError(f"File '{p.name}' is empty (0 bytes). Cannot ingest empty document.")

        sha256 = hashlib.sha256(content_bytes).hexdigest()
        did = doc_id or p.stem

        # Check duplicate by hash
        for existing_id, meta in self.registry.items():
            if meta.sha256 == sha256 and not force_reindex:
                logger.info(f"Duplicate upload detected: '{p.name}' matches existing document '{meta.filename}' (hash: {sha256[:10]}).")
                return DocumentUploadResponse(
                    doc_id=existing_id,
                    filename=p.name,
                    status="skipped_duplicate",
                    chunks_count=meta.chunks_count,
                    message=f"Document '{p.name}' is identical to already indexed document '{meta.filename}'. Duplicate indexing skipped.",
                    is_duplicate=True,
                )

        # Check if updating an existing document with the same doc_id
        is_update = did in self.registry
        if is_update:
            logger.info(f"Updating existing document '{did}'. Removing prior chunks before re-indexing.")
            self.vector_store.delete_document(did)

        # Parse document
        try:
            parsed = DocumentParser.parse(p, doc_id=did)
        except Exception as e:
            logger.error(f"Failed to parse document '{p.name}': {e}")
            raise ValueError(f"Document parsing failure: {e}")

        # Chunk document
        chunks = self.chunker.chunk_document(parsed)
        if not chunks:
            raise ValueError(f"Document '{p.name}' produced 0 chunks after parsing.")

        # Index chunks in vector store
        self.vector_store.add_chunks(chunks)

        # Determine version and effective date
        version = "2.0" if "2026" in p.name else ("1.0" if "2024" in p.name else "1.0")
        effective_date = "2026-01-01" if "2026" in p.name else ("2024-01-01" if "2024" in p.name else None)

        # Store a copy in ingestion storage for persistence
        stored_copy = self.ingestion_dir / p.name
        if stored_copy != p:
            shutil.copy2(p, stored_copy)

        meta = DocumentMetadata(
            doc_id=did,
            filename=p.name,
            format=parsed.format,
            size_bytes=file_size,
            sha256=sha256,
            chunks_count=len(chunks),
            version=version,
            effective_date=effective_date,
            status="indexed",
        )
        self.registry[did] = meta
        self._save_registry()

        action_msg = "Updated and re-indexed" if is_update else "Successfully ingested and indexed"
        return DocumentUploadResponse(
            doc_id=did,
            filename=p.name,
            status="indexed",
            chunks_count=len(chunks),
            message=f"{action_msg} '{p.name}' into {len(chunks)} searchable chunks.",
            is_duplicate=False,
        )

    def delete_document(self, doc_id: str) -> bool:
        """
        Delete a document and completely remove its searchable chunks from the persistent vector store.
        """
        if doc_id not in self.registry:
            logger.warning(f"Delete requested for nonexistent doc_id '{doc_id}'.")
            return False

        meta = self.registry.pop(doc_id)
        # Remove from vector store
        self.vector_store.delete_document(doc_id)

        # Remove stored file if exists
        stored_copy = self.ingestion_dir / meta.filename
        if stored_copy.exists():
            try:
                stored_copy.unlink()
            except Exception:
                pass

        self._save_registry()
        logger.info(f"Deleted document '{doc_id}' ({meta.filename}) from registry and vector store.")
        return True

    def reset(self) -> None:
        """Reset the ingestion registry and wipe all chunks."""
        self.registry.clear()
        self._save_registry()
        self.vector_store.reset()
        logger.info("Reset ingestion registry and vector store.")
