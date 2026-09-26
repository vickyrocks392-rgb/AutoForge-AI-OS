"""
Context Compaction — artifact-backed storage (18-L Gate 3, Gate 2 §9, §10, §19).

Gate 2 §9 deliberately did not mandate a new ``EntityType`` and recommended
storing the compact record as a **durable artifact**, precisely so no new entity
type or durable-state-model change is required. This module implements that
recommendation using only the existing substrate:

* :class:`DurableArtifactCatalog` (identity, lifecycle, content hash, versioning,
  supersession, conflict semantics) — **unmodified**;
* :class:`PhysicalArtifactStore` (staging, atomic publish, integrity) — **unmodified**.

Two consequences worth stating explicitly:

* **18-J is reused, not modified.** A retry of the same compaction produces the
  same deterministic key, so ``register_artifact`` returns the existing record
  and the 18-J idempotent-replay contract applies unchanged — identical content
  reuses the artifact, differing content raises ``ArtifactConflictError``. The
  state machine is never reopened.
* **No migration is needed.** A compact record is a cache; a record whose
  ``compaction_schema_version`` is unsupported is ignored and re-derived rather
  than migrated (Gate 2 §20).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from autoforge_execution.compaction.compaction_schema import (
    CompactedContextRecord,
    DurableRef,
)
from autoforge_execution.compaction.compaction_validation import (
    SUPPORTED_SCHEMA_VERSION,
)

logger = logging.getLogger("autoforge.execution.compaction.storage")

#: Artifact type label for compact records. A string, so the existing
#: ``DurableArtifactState.artifact_type`` carries it without a schema change.
COMPACTION_ARTIFACT_TYPE = "context_compaction_record"

#: Artifact name prefix, so compact records are identifiable in the catalog.
COMPACTION_ARTIFACT_PREFIX = "compaction_"

#: The ``compaction_id`` form. Kept next to the prefix so the two cannot drift.
COMPACTION_ID_PREFIX = "cmp_"


def is_compaction_bookkeeping_artifact(name: str) -> bool:
    """True when a file name is a Context Compaction bookkeeping artifact.

    18-L C-3. Context Compaction persists its records as durable artifacts under
    the workspace (the composition root places the durable artifact root at
    ``<workspace>/artifacts``). Those records are *compaction's own bookkeeping*,
    not engineering inputs.

    The predicate is defined here, beside :class:`CompactionRecordStore` and the
    naming constants it owns, so that the writer and the reader of this convention
    can never drift apart. Context Engineering consults it at candidate discovery
    only; nothing else in the CE pipeline changes.
    """
    return str(name).startswith(
        f"{COMPACTION_ARTIFACT_PREFIX}{COMPACTION_ID_PREFIX}"
    )


class CatalogReferenceResolver:
    """Resolves iteration source refs to durable artifact references.

    Implements :class:`ContextCompactor`'s ``DurableReferenceResolver`` protocol
    over the existing ``DurableArtifactCatalog`` (read-only). Gate 3 §8: a
    reference identifies its source, preserves provenance, is resolvable, keeps
    source identity/version, and never masquerades as the content itself.
    """

    def __init__(self, catalog: Any) -> None:
        self._catalog = catalog

    def resolve(self, source_ref: str) -> DurableRef | None:
        """Return a durable ref for ``source_ref``, or ``None`` when unresolved.

        Only COMMITTED artifacts are returned: a reference must point at content
        that is already durable, never at an in-flight staging write.
        """
        if not source_ref:
            return None
        name = f"{source_ref}"
        try:
            states = self._catalog.find_by_status(_committed_status())
        except Exception as exc:  # noqa: BLE001 - a hint must never break compaction
            logger.debug("catalog reference lookup failed: %s", exc)
            return None
        for state in states or []:
            if getattr(state, "artifact_name", "") == name:
                return DurableRef(
                    artifact_id=str(state.artifact_id),
                    content_hash=state.content_hash or "",
                    logical_version=int(getattr(state, "logical_version", 1) or 1),
                    artifact_type=COMPACTION_ARTIFACT_TYPE,
                    source_ref=name,
                )
        return None


def _committed_status():
    from autoforge_runtime.models import DurableArtifactStatus

    return DurableArtifactStatus.COMMITTED


class CompactionRecordStore:
    """Durable, idempotent storage for compact records.

    Wraps the existing artifact substrate. Gate 2 §19 idempotency comes from the
    18-J contract rather than from new machinery: the deterministic
    ``compaction_id`` makes the artifact key stable, so a retry replays through
    ``register_artifact`` and either reuses the existing committed artifact
    (identical content) or raises ``ArtifactConflictError`` (different content).
    """

    def __init__(self, catalog: Any, physical_store: Any) -> None:
        self._catalog = catalog
        self._physical_store = physical_store

    @staticmethod
    def artifact_name(record: CompactedContextRecord) -> str:
        """Deterministic artifact name, derived from the compaction id.

        The name is a pure function of the record identity, so a retry maps to the
        same artifact — which is exactly what makes the store idempotent.
        """
        return f"{COMPACTION_ARTIFACT_PREFIX}{record.compaction_id}"

    def save(self, record: CompactedContextRecord) -> str:
        """Persist a compact record as a durable artifact. Returns artifact_id.

        Never reopens a COMMITTED artifact (18-J, Gate 3 §3): the deterministic
        key means a retry lands on the same artifact, and 18-J's idempotent
        replay contract decides the outcome.
        """
        from autoforge_runtime.artifact_catalog import (
            ArtifactConflictError,
            derive_artifact_key,
        )

        name = self.artifact_name(record)
        payload = json.dumps(record.as_dict(), indent=2, default=str)
        key = derive_artifact_key(
            artifact_name=name,
            task_id=record.task_id,
            execution_id=record.execution_id,
            operation_type=COMPACTION_ARTIFACT_TYPE,
        )

        state = self._catalog.register_artifact(
            artifact_key=key,
            artifact_name=name,
            artifact_type=COMPACTION_ARTIFACT_TYPE,
            task_id=record.task_id,
            execution_id=record.execution_id,
            logical_version=max(1, record.logical_version),
        )

        if self._physical_store is None:
            return str(state.artifact_id)

        # 18-J: if the artifact is already COMMITTED this is an idempotent
        # replay.
        #
        # 18-L P1 repair: the replay decision is made on LOGICAL IDENTITY, not on
        # raw bytes. The previous comparison was `_sha256(payload)` against the
        # catalog's physical ``content_hash``, which answered "are these the same
        # bytes?" — not "are these the same compaction result?". Two logically
        # identical records differing only in runtime metadata (duration, clock)
        # therefore produced different byte hashes and were wrongly rejected as a
        # conflict, violating the contract that identical content reuses the
        # artifact. The catalog's ``content_hash`` is deliberately left as the
        # raw-byte hash so PHYSICAL integrity detection is untouched.
        if state.status is not None and getattr(state.status, "value", "") == "committed":
            committed_identity = self._committed_logical_identity(state)
            if committed_identity is not None and committed_identity == (
                record.logical_identity()
            ):
                # Same logical result: reuse. The committed artifact stays
                # immutable, as 18-J requires.
                return str(state.artifact_id)
            raise ArtifactConflictError(
                f"Compaction record {record.compaction_id} already exists with "
                f"different logical content; refusing to overwrite durable state.",
                details={
                    "compaction_id": record.compaction_id,
                    "artifact_id": str(state.artifact_id),
                    "stored_hash": state.content_hash,
                    "stored_logical_identity": committed_identity,
                    "incoming_logical_identity": record.logical_identity(),
                },
            )

        staging_path = self._physical_store.create_staging_file(key)
        self._catalog.begin_staging(state.artifact_id, staging_path=str(staging_path))
        content_hash, size_bytes = self._physical_store.write_staging_text(
            staging_path, payload
        )
        published = self._physical_store.atomic_publish(
            staging_path, name, expected_hash=content_hash, expected_size=size_bytes
        )
        self._catalog.commit_artifact(
            state.artifact_id,
            storage_path=str(published),
            content_hash=content_hash,
            size_bytes=size_bytes,
        )
        return str(state.artifact_id)

    def _committed_logical_identity(self, state: Any) -> str | None:
        """Recompute the LOGICAL identity of an already-committed record.

        The value is always RECOMPUTED from the persisted fields rather than read
        from the stored ``logical_identity`` field, so a tampered or truncated
        record cannot forge its way into an idempotent-replay reuse. Returns
        ``None`` when the committed record cannot be read, which the caller
        treats as "not provably identical" and therefore a conflict — fail-safe,
        because refusing to reuse is recoverable while wrongly reusing is not.
        """
        path = getattr(state, "storage_path", None)
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                committed = json.load(handle)
        except Exception as exc:  # noqa: BLE001 - unreadable => not provably equal
            logger.debug(
                "committed compaction record %s unreadable during replay: %s",
                getattr(state, "artifact_name", "?"),
                exc,
            )
            return None
        if not isinstance(committed, dict):
            return None
        try:
            return CompactedContextRecord.from_dict(committed).logical_identity()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "committed compaction record %s could not be reconstructed: %s",
                getattr(state, "artifact_name", "?"),
                exc,
            )
            return None

    def load(self, compaction_id: str) -> CompactedContextRecord | None:
        """Load a compact record. Returns ``None`` when absent or unreadable.

        An unsupported schema version is **not** migrated (Gate 2 §20): it is
        ignored so the caller re-derives instead of trusting stale meaning.
        """
        name = f"{COMPACTION_ARTIFACT_PREFIX}{compaction_id}"
        for state in self._catalog.find_by_status(_committed_status()) or []:
            if getattr(state, "artifact_name", "") != name:
                continue
            path = getattr(state, "storage_path", None)
            if not path:
                return None
            try:
                with open(path, encoding="utf-8") as handle:
                    raw = handle.read()
            except Exception as exc:  # noqa: BLE001 - a cache read must never fail work
                logger.warning("compact record %s unreadable: %s", compaction_id, exc)
                return None

            # Gate 4: verify the durable bytes against the committed hash before
            # trusting them. Without this, an artifact corrupted on disk (but
            # still parseable JSON) would be returned as if it were authoritative,
            # i.e. a silent substitution (task §15). The catalog's committed
            # content_hash is the independent authority here; the in-record
            # content_digest() is derived from the same bytes and cannot detect
            # this on its own.
            stored_hash = getattr(state, "content_hash", None)
            if stored_hash and _sha256(raw) != stored_hash:
                logger.warning(
                    "compact record %s failed integrity check: on-disk content "
                    "does not match the committed hash; refusing to load",
                    compaction_id,
                )
                return None

            try:
                payload = json.loads(raw)
            except Exception as exc:  # noqa: BLE001 - a cache read must never fail work
                logger.warning("compact record %s unreadable: %s", compaction_id, exc)
                return None
            if int(payload.get("compaction_schema_version", 1)) > SUPPORTED_SCHEMA_VERSION:
                logger.info(
                    "compact record %s uses unsupported schema version; ignoring",
                    compaction_id,
                )
                return None

            record = CompactedContextRecord.from_dict(payload)

            # 18-L P1: defence in depth on the LOGICAL layer. The byte hash above
            # proves the bytes are unmodified; this proves the bytes actually
            # describe the logical identity they claim. A record whose stored
            # ``logical_identity`` disagrees with the value recomputed from its
            # own content has been internally tampered with, and is refused.
            claimed = payload.get("logical_identity")
            if claimed is not None and claimed != record.logical_identity():
                logger.warning(
                    "compact record %s failed logical-identity check: stored "
                    "identity does not match its own content; refusing to load",
                    compaction_id,
                )
                return None

            return record
        return None


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "COMPACTION_ARTIFACT_PREFIX",
    "COMPACTION_ARTIFACT_TYPE",
    "CatalogReferenceResolver",
    "CompactionRecordStore",
]
