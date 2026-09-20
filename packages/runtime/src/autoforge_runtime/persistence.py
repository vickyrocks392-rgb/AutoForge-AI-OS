"""Persistence Layer — durable state persistence for the Runtime State Manager.

Implements the Runtime Persistence Model (Runtime State Manager Specification
v1.0, Section 15) and the Persistence Layer component (Sections 7.3 and 32.4).

Phase 18-J (Durable Execution + Resume + Idempotency), step 18-J.1
-----------------------------------------------------------------
The persistent store is backed by SQLite, replacing the process-local
dictionaries that made the runtime's "durable storage" claim untrue::

    Cache Layer      -> CacheLayer        low-latency read cache
    Persistent Store -> SQLiteStorage     transactional durable database
    History Store    -> HistoryStore      append-only transition audit trail
    Coordinator      -> PersistenceLayer  facade used by the runtime

Write path (Section 15.3): validate -> write to database -> update cache
Read  path (Section 15.4): check cache -> read from database -> cache -> return

Storage location
----------------
``PersistenceLayer(db_path=...)`` (and ``SQLiteStorage(db_path=...)``) open a
durable database file. When no path is supplied the default is read from the
``AUTOFORGE_RUNTIME_STATE_DB`` environment variable; if that is unset, the
store is created in memory (``:memory:``) so that every instance stays fully
isolated — preserving the runtime's long-standing per-process semantics for
tests and single-shot tooling.

Guarantees
----------
- Durability (Section 27.6): file databases run with ``journal_mode=WAL`` and
  ``synchronous=FULL``, so a committed write survives process death.
- Atomicity: :meth:`PersistenceLayer.transaction` groups multi-entity writes
  and history appends into one SQLite transaction; a rollback also discards
  the cache entries written inside the failed transaction.
- Optimistic concurrency: :meth:`SQLiteStorage.write` accepts
  ``expected_version`` and raises :class:`VersionConflictError` on a stale
  write; every row additionally carries a monotonic ``revision`` counter.
- Idempotency (Section 5.9): history rows are keyed by ``transition_id`` and
  inserted with ``INSERT OR IGNORE``, so replaying a transition can never
  duplicate the audit trail.
- Thread safety (Section 5.11): a re-entrant lock serialises connection access.

``PersistentStore`` remains available as an alias of :class:`SQLiteStorage`, so
existing imports (``autoforge_runtime.PersistentStore``) keep working.
"""

from __future__ import annotations

import copy
import logging
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoforge_runtime.exceptions import (
    EntityNotFoundError,
    PersistenceError,
    VersionConflictError,
)
from autoforge_runtime.models import (
    ApprovalRequestState,
    CheckpointState,
    EngineeringLoopState,
    EntityType,
    ExecutionAttemptState,
    ExecutionCheckpointState,
    ExecutionState,
    IdempotentOperationState,
    ProjectState,
    RecoveryState,
    StateModel,
    StateTransition,
    TaskState,
    WorkerState,
    WorkflowState,
)

logger = logging.getLogger("autoforge.runtime.persistence")

#: Environment variable that enables durable storage without code changes.
DB_PATH_ENV_VAR = "AUTOFORGE_RUNTIME_STATE_DB"

#: SQLite sentinel for a private in-memory database.
IN_MEMORY_PATH = ":memory:"

#: Current durable schema revision (recorded in ``runtime_schema_meta``).
SCHEMA_VERSION = "1"

#: Entity type -> (state model, primary-key attribute).
_ENTITY_MODEL_MAP: dict[EntityType, tuple[type[StateModel], str]] = {
    EntityType.PROJECT: (ProjectState, "project_id"),
    EntityType.WORKFLOW: (WorkflowState, "workflow_id"),
    EntityType.LOOP: (EngineeringLoopState, "loop_id"),
    EntityType.TASK: (TaskState, "task_id"),
    EntityType.WORKER: (WorkerState, "worker_id"),
    EntityType.CHECKPOINT: (CheckpointState, "checkpoint_id"),
    EntityType.RECOVERY: (RecoveryState, "recovery_id"),
    # Phase 18-J.2 — durable execution identity lives in the same store as
    # every other runtime entity: one database, one source of truth.
    EntityType.EXECUTION: (ExecutionState, "execution_id"),
    EntityType.EXECUTION_ATTEMPT: (ExecutionAttemptState, "attempt_id"),
    EntityType.EXECUTION_CHECKPOINT: (ExecutionCheckpointState, "checkpoint_id"),
    # Phase 18-J.4 — durable idempotent operations live in the same store as
    # every other runtime entity: one database, one source of truth.
    EntityType.IDEMPOTENT_OPERATION: (IdempotentOperationState, "operation_id"),
    # Phase 18-J.5 — durable HITL approvals live in the same store as
    # every other runtime entity: one database, one source of truth.
    EntityType.APPROVAL_REQUEST: (ApprovalRequestState, "approval_id"),
}


# ── Path, identity and serialisation helpers ─────────────────────────────


def resolve_db_path(db_path: str | Path | None = None) -> str:
    """Resolve the SQLite path for the runtime state store.

    Precedence: explicit argument -> ``AUTOFORGE_RUNTIME_STATE_DB`` env var
    -> a private, volatile in-memory database (``:memory:``).

    Args:
        db_path: Explicit database path, or ``None`` to use the default.

    Returns:
        The resolved path, or :data:`IN_MEMORY_PATH` for volatile storage.
    """
    if db_path is not None:
        return str(Path(str(db_path)).expanduser())
    configured = os.environ.get(DB_PATH_ENV_VAR, "").strip()
    return str(Path(configured).expanduser()) if configured else IN_MEMORY_PATH


def coerce_entity_type(entity_type: EntityType | str) -> EntityType:
    """Return ``entity_type`` as an :class:`EntityType` member.

    Raises:
        PersistenceError: If the entity type is not recognised.
    """
    if isinstance(entity_type, EntityType):
        return entity_type
    try:
        return EntityType(entity_type)
    except ValueError:
        raise PersistenceError(
            f"Unsupported entity type: {entity_type}",
            details={"entity_type": str(entity_type)},
        ) from None


def coerce_entity_id(entity_id: uuid.UUID | str) -> uuid.UUID:
    """Return ``entity_id`` as a :class:`uuid.UUID`.

    Raises:
        PersistenceError: If the identifier is not a valid UUID.
    """
    if isinstance(entity_id, uuid.UUID):
        return entity_id
    try:
        return uuid.UUID(str(entity_id))
    except (AttributeError, TypeError, ValueError):
        raise PersistenceError(
            f"Invalid entity identifier: {entity_id!r}",
            details={"entity_id": str(entity_id)},
        ) from None


def entity_model(entity_type: EntityType | str) -> tuple[type[StateModel], str]:
    """Return the ``(state model, primary-key attribute)`` pair for a type.

    Raises:
        PersistenceError: If the entity type carries no runtime state model.
    """
    etype = coerce_entity_type(entity_type)
    try:
        return _ENTITY_MODEL_MAP[etype]
    except KeyError:
        raise PersistenceError(
            f"Unsupported entity type: {etype.value}",
            details={"entity_type": etype.value},
        ) from None


def entity_id_of(entity_type: EntityType | str, state: StateModel) -> uuid.UUID:
    """Return the primary-key UUID carried by ``state``."""
    etype = coerce_entity_type(entity_type)
    _model, attribute = entity_model(etype)
    value = getattr(state, attribute, None)
    if not isinstance(value, uuid.UUID):
        raise PersistenceError(
            f"{type(state).__name__} does not expose a UUID '{attribute}'",
            details={"entity_type": etype.value, "attribute": attribute},
        )
    return value


def _state_version(state: StateModel) -> int:
    """Return the integer version carried by ``state`` (defaulting to 1)."""
    sv = getattr(state, "state_version", None)
    if isinstance(sv, int) and not isinstance(sv, bool):
        return sv
    version = getattr(state, "version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        # WorkflowState.version is a UUID revision marker, not a counter.
        return 1
    return version


def _to_iso(value: datetime) -> str:
    """Normalise a datetime to a timezone-aware ISO-8601 UTC string."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _utc_now_iso() -> str:
    """Return the current UTC time as a normalised ISO-8601 string."""
    return _to_iso(datetime.now(timezone.utc))


def _serialize_state(entity_type: EntityType | str, state: StateModel) -> str:
    """Serialise a state model to its durable JSON payload."""
    etype = coerce_entity_type(entity_type)
    try:
        return state.model_dump_json()
    except Exception as exc:  # pragma: no cover - defensive
        raise PersistenceError(
            f"Failed to serialise {etype.value} state: {exc}",
            details={"entity_type": etype.value},
        ) from exc


def _deserialize_state(
    entity_type: EntityType | str, entity_id: uuid.UUID, payload: str
) -> StateModel:
    """Rebuild a state model from its durable JSON payload."""
    etype = coerce_entity_type(entity_type)
    model, _attribute = entity_model(etype)
    try:
        return model.model_validate_json(payload)
    except Exception as exc:
        raise PersistenceError(
            f"Corrupted {etype.value} state for ID {entity_id}: {exc}",
            details={"entity_type": etype.value, "entity_id": str(entity_id)},
        ) from exc


#: Durable schema: entity rows, append-only history, schema metadata.
_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS runtime_entities (
    entity_type   TEXT    NOT NULL,
    entity_id     TEXT    NOT NULL,
    seq           INTEGER NOT NULL,
    state_version INTEGER NOT NULL,
    revision      INTEGER NOT NULL,
    payload       TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_runtime_entities_seq
    ON runtime_entities (entity_type, seq);

CREATE TABLE IF NOT EXISTS runtime_history (
    sequence      INTEGER PRIMARY KEY AUTOINCREMENT,
    transition_id TEXT    NOT NULL UNIQUE,
    entity_type   TEXT    NOT NULL,
    entity_id     TEXT    NOT NULL,
    from_state    TEXT    NOT NULL,
    to_state      TEXT    NOT NULL,
    actor         TEXT    NOT NULL DEFAULT 'system',
    timestamp     TEXT    NOT NULL,
    payload       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_history_entity
    ON runtime_history (entity_type, entity_id, sequence);

CREATE INDEX IF NOT EXISTS idx_runtime_history_timestamp
    ON runtime_history (timestamp, sequence);

CREATE TABLE IF NOT EXISTS runtime_schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class CacheLayer:
    """In-memory cache for frequently accessed state (Section 7.3).

    The cache is a pure accelerator: every write to the persistent store also
    updates (or invalidates) the corresponding entry, so a cache hit always
    equals a fresh read. Values are deep-copied on write and on read, so
    callers never observe shared mutable state.
    """

    def __init__(self) -> None:
        """Initialize the cache layer."""
        self._cache: dict[tuple[EntityType, uuid.UUID], StateModel] = {}
        self._hits = 0
        self._misses = 0
        self._lock = threading.RLock()

    def get(self, entity_type: EntityType | str, entity_id: uuid.UUID | str) -> StateModel | None:
        """Get state from cache (a deep copy), or ``None`` on a miss."""
        key = (coerce_entity_type(entity_type), coerce_entity_id(entity_id))
        with self._lock:
            state = self._cache.get(key)
            if state is None:
                self._misses += 1
                return None
            self._hits += 1
            return copy.deepcopy(state)

    def set(
        self,
        entity_type: EntityType | str,
        entity_id: uuid.UUID | str,
        state: StateModel,
    ) -> None:
        """Set state in cache (stored as a deep copy)."""
        key = (coerce_entity_type(entity_type), coerce_entity_id(entity_id))
        with self._lock:
            self._cache[key] = copy.deepcopy(state)

    def invalidate(self, entity_type: EntityType | str, entity_id: uuid.UUID | str) -> None:
        """Invalidate cache entry."""
        key = (coerce_entity_type(entity_type), coerce_entity_id(entity_id))
        with self._lock:
            self._cache.pop(key, None)

    def invalidate_type(self, entity_type: EntityType | str) -> int:
        """Invalidate every entry of one entity type; return the count."""
        etype = coerce_entity_type(entity_type)
        with self._lock:
            keys = [key for key in self._cache if key[0] == etype]
            for key in keys:
                del self._cache[key]
            return len(keys)

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()

    def keys(self, entity_type: EntityType | str | None = None) -> list[tuple[EntityType, uuid.UUID]]:
        """Return the cached keys, optionally filtered by entity type."""
        with self._lock:
            keys = list(self._cache)
        if entity_type is None:
            return keys
        etype = coerce_entity_type(entity_type)
        return [key for key in keys if key[0] == etype]

    def stats(self) -> dict[str, int]:
        """Return cache size and hit/miss counters."""
        with self._lock:
            return {"entries": len(self._cache), "hits": self._hits, "misses": self._misses}

    def __len__(self) -> int:
        """Return the number of cached entries."""
        with self._lock:
            return len(self._cache)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a developer-friendly representation."""
        return f"CacheLayer(entries={len(self)})"


class SQLiteStorage:
    """Durable, transactional storage for all runtime state.

    This is the specification's "Persistent Store" (Section 7.3): a relational
    database with transactions, durability guarantees and backup support. A
    single connection — guarded by a re-entrant lock — services every read and
    write. The driver runs in autocommit mode (``isolation_level=None``), so a
    single statement is durable as soon as it returns; :meth:`begin`,
    :meth:`commit` and :meth:`rollback` add explicit, nestable transactions for
    multi-statement atomicity.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        timeout: float = 5.0,
        synchronous: str = "FULL",
        journal_mode: str | None = None,
        connect: bool = True,
    ) -> None:
        """Initialize the durable store.

        Args:
            db_path: Database file, or ``":memory:"`` for volatile storage.
                Defaults to ``AUTOFORGE_RUNTIME_STATE_DB`` / ``":memory:"``.
            timeout: SQLite busy timeout in seconds.
            synchronous: SQLite ``synchronous`` pragma (``FULL`` by default so
                that a committed write survives power loss).
            journal_mode: SQLite ``journal_mode`` pragma; defaults to ``WAL``
                for file databases and ``MEMORY`` for in-memory databases.
            connect: Open the connection immediately; ``False`` exercises the
                lazy-open path.
        """
        self._path = resolve_db_path(db_path)
        self._timeout = float(timeout)
        self._synchronous = synchronous.upper()
        self._journal_mode = (
            journal_mode.upper()
            if journal_mode is not None
            else ("MEMORY" if self._path == IN_MEMORY_PATH else "WAL")
        )
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self._connection: sqlite3.Connection | None = None
        if connect:
            self.initialize()

    # ── Connection management ────────────────────────────────────────────

    @property
    def db_path(self) -> str:
        """The resolved database path (``":memory:"`` when volatile)."""
        return self._path

    @property
    def is_durable(self) -> bool:
        """Whether writes survive process exit (i.e. a file-backed store)."""
        return self._path != IN_MEMORY_PATH

    @property
    def is_open(self) -> bool:
        """Whether the underlying connection is open."""
        return self._connection is not None

    @property
    def in_transaction(self) -> bool:
        """Whether a transaction (or nested savepoint) is in progress."""
        return self._transaction_depth > 0

    @property
    def transaction_depth(self) -> int:
        """Nesting depth of the active transaction (``0`` when none)."""
        return self._transaction_depth

    def initialize(self) -> None:
        """Open the connection and create the durable schema when needed.

        Idempotent: calling it on an open store is a no-op.

        Raises:
            PersistenceError: If the database cannot be opened or initialised.
        """
        with self._lock:
            if self._connection is not None:
                return
            try:
                if self._path != IN_MEMORY_PATH:
                    Path(self._path).parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(
                    self._path,
                    timeout=self._timeout,
                    isolation_level=None,
                    check_same_thread=False,
                )
                connection.row_factory = sqlite3.Row
                connection.execute(f"PRAGMA journal_mode={self._journal_mode}")
                connection.execute(f"PRAGMA synchronous={self._synchronous}")
                connection.execute(f"PRAGMA busy_timeout={int(self._timeout * 1000)}")
                connection.executescript(_SCHEMA_DDL)
                connection.execute(
                    "INSERT OR IGNORE INTO runtime_schema_meta (key, value)"
                    " VALUES ('schema_version', ?)",
                    (SCHEMA_VERSION,),
                )
            except (OSError, sqlite3.Error) as exc:
                raise PersistenceError(
                    f"Failed to open runtime state database at {self._path}: {exc}",
                    details={"db_path": self._path},
                ) from exc
            self._connection = connection
            logger.debug("Runtime state store opened at %s", self._path)

    def close(self) -> None:
        """Close the connection (idempotent).

        Volatile (in-memory) stores lose their contents on close.
        """
        with self._lock:
            connection = self._connection
            self._connection = None
            self._transaction_depth = 0
            if connection is None:
                return
            try:
                connection.close()
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                raise PersistenceError(
                    f"Failed to close runtime state database: {exc}",
                    details={"db_path": self._path},
                ) from exc

    def _connection_or_open(self) -> sqlite3.Connection:
        """Return the live connection, opening it when necessary."""
        if self._connection is None:
            self.initialize()
        connection = self._connection
        if connection is None:  # pragma: no cover - initialize() guarantees it
            raise PersistenceError(
                "Runtime state database is not available",
                details={"db_path": self._path},
            )
        return connection

    def __enter__(self) -> SQLiteStorage:
        """Support ``with SQLiteStorage(...) as store:`` usage."""
        self.initialize()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close the store when leaving the ``with`` block."""
        self.close()

    # ── Transactions ─────────────────────────────────────────────────────

    def begin(self) -> None:
        """Begin a transaction (nested calls create savepoints)."""
        with self._lock:
            connection = self._connection_or_open()
            if self._transaction_depth == 0:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute(f"SAVEPOINT sp_{self._transaction_depth}")
            self._transaction_depth += 1

    def commit(self) -> None:
        """Commit the current transaction (or release its savepoint)."""
        with self._lock:
            if self._transaction_depth == 0:
                raise PersistenceError(
                    "Cannot commit: no transaction is in progress",
                    details={"db_path": self._path},
                )
            self._transaction_depth -= 1
            connection = self._connection_or_open()
            if self._transaction_depth == 0:
                connection.execute("COMMIT")
            else:
                connection.execute(f"RELEASE sp_{self._transaction_depth}")

    def rollback(self) -> None:
        """Roll back the current transaction (or its savepoint)."""
        with self._lock:
            if self._transaction_depth == 0:
                raise PersistenceError(
                    "Cannot roll back: no transaction is in progress",
                    details={"db_path": self._path},
                )
            self._transaction_depth -= 1
            connection = self._connection_or_open()
            if self._transaction_depth == 0:
                connection.execute("ROLLBACK")
            else:
                connection.execute(f"ROLLBACK TO sp_{self._transaction_depth}")
                connection.execute(f"RELEASE sp_{self._transaction_depth}")

    # ── Entity writes & reads ────────────────────────────────────────────

    def write(
        self,
        entity_type: EntityType | str,
        entity_id: uuid.UUID | str,
        state: StateModel,
        *,
        expected_version: int | None = None,
    ) -> int:
        """Write state to durable storage, returning the new row revision.

        Args:
            entity_type: The entity type being written.
            entity_id: The entity identifier (must match the state model).
            state: The (frozen) state model instance.
            expected_version: Optional optimistic-concurrency guard; the write
                is rejected unless the stored state version matches.

        Returns:
            The monotonic revision of the stored row.

        Raises:
            PersistenceError: If the entity type is unsupported or the
                identifier disagrees with the state model.
            VersionConflictError: If ``expected_version`` is stale.
        """
        etype = coerce_entity_type(entity_type)
        eid = coerce_entity_id(entity_id)
        declared = entity_id_of(etype, state)
        if declared != eid:
            raise PersistenceError(
                f"Entity identifier mismatch for {etype.value}: {eid} != {declared}",
                details={
                    "entity_type": etype.value,
                    "entity_id": str(eid),
                    "state_entity_id": str(declared),
                },
            )
        return self._write_row(
            etype,
            eid,
            _serialize_state(etype, state),
            _state_version(state),
            expected_version,
        )

    def _write_row(
        self,
        entity_type: EntityType,
        entity_id: uuid.UUID,
        payload: str,
        state_version: int,
        expected_version: int | None,
    ) -> int:
        """Upsert one entity row while holding the store lock."""
        now = _utc_now_iso()
        with self._lock:
            connection = self._connection_or_open()
            row = connection.execute(
                "SELECT seq, state_version, revision, created_at"
                " FROM runtime_entities WHERE entity_type = ? AND entity_id = ?",
                (entity_type.value, str(entity_id)),
            ).fetchone()
            if row is None:
                if expected_version is not None:
                    raise VersionConflictError(
                        f"Expected version {expected_version} for "
                        f"{entity_type.value} {entity_id}, but no state exists",
                        details={
                            "entity_type": entity_type.value,
                            "entity_id": str(entity_id),
                            "expected_version": expected_version,
                        },
                    )
                seq = self._next_seq(connection)
                revision = 1
                created_at = now
            else:
                if expected_version is not None and row["state_version"] != expected_version:
                    raise VersionConflictError(
                        f"Version conflict for {entity_type.value} {entity_id}: "
                        f"expected {expected_version}, stored {row['state_version']}",
                        details={
                            "entity_type": entity_type.value,
                            "entity_id": str(entity_id),
                            "expected_version": expected_version,
                            "stored_version": row["state_version"],
                        },
                    )
                seq = row["seq"]
                revision = row["revision"] + 1
                created_at = row["created_at"]
            connection.execute(
                "INSERT INTO runtime_entities"
                " (entity_type, entity_id, seq, state_version, revision, payload,"
                "  created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (entity_type, entity_id) DO UPDATE SET"
                "  seq = excluded.seq,"
                "  state_version = excluded.state_version,"
                "  revision = excluded.revision,"
                "  payload = excluded.payload,"
                "  updated_at = excluded.updated_at",
                (
                    entity_type.value,
                    str(entity_id),
                    seq,
                    state_version,
                    revision,
                    payload,
                    created_at,
                    now,
                ),
            )
            return revision

    @staticmethod
    def _next_seq(connection: sqlite3.Connection) -> int:
        """Return the next insertion-order sequence number."""
        row = connection.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM runtime_entities"
        ).fetchone()
        return int(row["next_seq"])

    def read(self, entity_type: EntityType | str, entity_id: uuid.UUID | str) -> StateModel:
        """Read state from durable storage.

        Raises:
            EntityNotFoundError: If no state is stored for the identifier.
        """
        etype = coerce_entity_type(entity_type)
        eid = coerce_entity_id(entity_id)
        with self._lock:
            row = self._connection_or_open().execute(
                "SELECT payload FROM runtime_entities"
                " WHERE entity_type = ? AND entity_id = ?",
                (etype.value, str(eid)),
            ).fetchone()
        if row is None:
            raise EntityNotFoundError(
                f"{etype.value.capitalize()} with ID {eid} not found",
                details={"entity_id": str(eid), "entity_type": etype.value},
            )
        return _deserialize_state(etype, eid, row["payload"])

    def read_all(self, entity_type: EntityType | str) -> list[StateModel]:
        """Read every stored state of one entity type, in insertion order."""
        etype = coerce_entity_type(entity_type)
        entity_model(etype)  # validates that this type has a state model
        with self._lock:
            rows = self._connection_or_open().execute(
                "SELECT entity_id, payload FROM runtime_entities"
                " WHERE entity_type = ? ORDER BY seq",
                (etype.value,),
            ).fetchall()
        return [
            _deserialize_state(etype, uuid.UUID(row["entity_id"]), row["payload"])
            for row in rows
        ]

    def snapshot_store(self, entity_type: EntityType | str) -> dict[uuid.UUID, StateModel]:
        """Return a copy of one entity store, keyed by entity ID."""
        etype = coerce_entity_type(entity_type)
        return {entity_id_of(etype, state): state for state in self.read_all(etype)}

    def exists(self, entity_type: EntityType | str, entity_id: uuid.UUID | str) -> bool:
        """Return whether state exists for the identifier."""
        etype = coerce_entity_type(entity_type)
        eid = coerce_entity_id(entity_id)
        with self._lock:
            row = self._connection_or_open().execute(
                "SELECT 1 AS present FROM runtime_entities"
                " WHERE entity_type = ? AND entity_id = ?",
                (etype.value, str(eid)),
            ).fetchone()
        return row is not None

    def delete(self, entity_type: EntityType | str, entity_id: uuid.UUID | str) -> bool:
        """Delete state from durable storage; returns ``True`` when removed."""
        etype = coerce_entity_type(entity_type)
        eid = coerce_entity_id(entity_id)
        with self._lock:
            cursor = self._connection_or_open().execute(
                "DELETE FROM runtime_entities WHERE entity_type = ? AND entity_id = ?",
                (etype.value, str(eid)),
            )
        return cursor.rowcount > 0

    def get_version(
        self, entity_type: EntityType | str, entity_id: uuid.UUID | str
    ) -> int | None:
        """Return the stored state version, or ``None`` when absent."""
        return self._scalar(entity_type, entity_id, "state_version")

    def get_revision(
        self, entity_type: EntityType | str, entity_id: uuid.UUID | str
    ) -> int | None:
        """Return the stored row revision, or ``None`` when absent."""
        return self._scalar(entity_type, entity_id, "revision")

    def _scalar(
        self,
        entity_type: EntityType | str,
        entity_id: uuid.UUID | str,
        column: str,
    ) -> int | None:
        """Return one integer column for a single entity row."""
        etype = coerce_entity_type(entity_type)
        eid = coerce_entity_id(entity_id)
        with self._lock:
            row = self._connection_or_open().execute(
                f"SELECT {column} AS value FROM runtime_entities"
                " WHERE entity_type = ? AND entity_id = ?",
                (etype.value, str(eid)),
            ).fetchone()
        return int(row["value"]) if row is not None else None

    def count(self, entity_type: EntityType | str) -> int:
        """Return the number of stored entities of one type."""
        etype = coerce_entity_type(entity_type)
        with self._lock:
            row = self._connection_or_open().execute(
                "SELECT COUNT(*) AS total FROM runtime_entities WHERE entity_type = ?",
                (etype.value,),
            ).fetchone()
        return int(row["total"])

    # ── Transition history (append-only audit trail) ─────────────────────

    def append_history(self, transition: StateTransition) -> bool:
        """Append a transition to the immutable history log.

        Returns:
            ``True`` when a new row was appended, ``False`` when the
            transition had already been recorded (idempotent replay).
        """
        with self._lock:
            cursor = self._connection_or_open().execute(
                "INSERT OR IGNORE INTO runtime_history"
                " (transition_id, entity_type, entity_id, from_state, to_state,"
                "  actor, timestamp, payload)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(transition.transition_id),
                    coerce_entity_type(transition.entity_type).value,
                    str(transition.entity_id),
                    transition.from_state,
                    transition.to_state,
                    transition.actor,
                    _to_iso(transition.timestamp),
                    transition.model_dump_json(),
                ),
            )
        return cursor.rowcount > 0

    def read_history(
        self,
        entity_type: EntityType | str | None = None,
        entity_id: uuid.UUID | str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[StateTransition]:
        """Read recorded transitions, filtered and in append order."""
        clauses: list[str] = []
        parameters: list[Any] = []
        if entity_type is not None:
            clauses.append("entity_type = ?")
            parameters.append(coerce_entity_type(entity_type).value)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            parameters.append(str(coerce_entity_id(entity_id)))
        if start is not None:
            clauses.append("timestamp >= ?")
            parameters.append(_to_iso(start))
        if end is not None:
            clauses.append("timestamp <= ?")
            parameters.append(_to_iso(end))
        clause = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection_or_open().execute(
                f"SELECT payload FROM runtime_history{clause} ORDER BY sequence",
                parameters,
            ).fetchall()
        return [StateTransition.model_validate_json(row["payload"]) for row in rows]

    def history_count(self) -> int:
        """Return the number of recorded transitions."""
        with self._lock:
            row = self._connection_or_open().execute(
                "SELECT COUNT(*) AS total FROM runtime_history"
            ).fetchone()
        return int(row["total"])

    # ── Maintenance, backup and health ───────────────────────────────────

    def clear(self) -> None:
        """Delete every entity row and every history row (schema preserved)."""
        with self._lock:
            connection = self._connection_or_open()
            connection.execute("DELETE FROM runtime_entities")
            connection.execute("DELETE FROM runtime_history")

    def clear_history(self) -> None:
        """Delete the transition history (entity state is untouched)."""
        with self._lock:
            self._connection_or_open().execute("DELETE FROM runtime_history")

    def backup(self, destination: str | Path) -> Path:
        """Write a consistent online copy of the database to ``destination``.

        Returns:
            The destination path.

        Raises:
            PersistenceError: If the backup cannot be written.
        """
        target = Path(str(destination)).expanduser()
        with self._lock:
            source = self._connection_or_open()
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(str(target)) as backup_connection:
                    source.backup(backup_connection)
            except (OSError, sqlite3.Error) as exc:
                raise PersistenceError(
                    f"Failed to back up runtime state database: {exc}",
                    details={"db_path": self._path, "destination": str(target)},
                ) from exc
        return target

    def health_check(self) -> dict[str, Any]:
        """Return storage health for dependency verification.

        Runs SQLite's ``quick_check`` and reports entity/transition counts.
        """
        report: dict[str, Any] = {
            "healthy": False,
            "db_path": self._path,
            "durable": self.is_durable,
            "journal_mode": self._journal_mode,
            "synchronous": self._synchronous,
            "schema_version": SCHEMA_VERSION,
            "entities": 0,
            "transitions": 0,
        }
        try:
            with self._lock:
                connection = self._connection_or_open()
                integrity_row = connection.execute("PRAGMA quick_check").fetchone()
                schema_row = connection.execute(
                    "SELECT value FROM runtime_schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                entities = connection.execute(
                    "SELECT COUNT(*) AS total FROM runtime_entities"
                ).fetchone()
                transitions = connection.execute(
                    "SELECT COUNT(*) AS total FROM runtime_history"
                ).fetchone()
            integrity = str(integrity_row[0]) if integrity_row is not None else "unknown"
            report.update(
                {
                    "healthy": integrity == "ok",
                    "integrity": integrity,
                    "schema_version": (
                        str(schema_row["value"]) if schema_row is not None else SCHEMA_VERSION
                    ),
                    "entities": int(entities["total"]),
                    "transitions": int(transitions["total"]),
                }
            )
        except PersistenceError as exc:
            report["integrity"] = "unavailable"
            report["error"] = str(exc)
        return report

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a developer-friendly representation."""
        return f"SQLiteStorage(db_path={self._path!r})"


class HistoryStore:
    """Append-only store for the complete state-transition history.

    Implements the History Store of Section 7.3: an immutable audit trail that
    supports historical queries and state replay. Entries are only ever
    appended and are keyed by ``transition_id``, which makes replaying a
    transition idempotent.

    A stand-alone store (no storage supplied) creates its own private
    in-memory database, so ``HistoryStore()`` keeps working exactly like the
    original in-memory implementation.
    """

    def __init__(self, storage: SQLiteStorage | None = None) -> None:
        """Initialize the history store.

        Args:
            storage: Backing durable storage; a private in-memory store is
                created when omitted.
        """
        self._owns_storage = storage is None
        self._storage = storage if storage is not None else SQLiteStorage(IN_MEMORY_PATH)

    @property
    def storage(self) -> SQLiteStorage:
        """The backing durable storage."""
        return self._storage

    def write(self, transition: StateTransition) -> bool:
        """Append a transition to the immutable audit trail.

        Returns:
            ``True`` when a new entry was recorded, ``False`` on replay.
        """
        return self._storage.append_history(transition)

    def read_all(self) -> list[StateTransition]:
        """Read all transitions in append order."""
        return self._storage.read_history()

    def read_by_entity(
        self, entity_type: EntityType | str, entity_id: uuid.UUID | str
    ) -> list[StateTransition]:
        """Read transitions for a specific entity, in append order."""
        return self._storage.read_history(entity_type, entity_id)

    def read_by_entity_type(self, entity_type: EntityType | str) -> list[StateTransition]:
        """Read transitions for a specific entity type, in append order."""
        return self._storage.read_history(entity_type)

    def read_between(self, start: datetime, end: datetime) -> list[StateTransition]:
        """Read transitions recorded inside a time range."""
        return self._storage.read_history(start=start, end=end)

    def count(self) -> int:
        """Return the number of recorded transitions."""
        return self._storage.history_count()

    def clear(self) -> None:
        """Clear the history store."""
        self._storage.clear_history()

    def close(self) -> None:
        """Close the storage owned by this store (no-op when injected)."""
        if self._owns_storage:
            self._storage.close()

    def __len__(self) -> int:
        """Return the number of recorded transitions."""
        return self.count()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a developer-friendly representation."""
        return f"HistoryStore(transitions={len(self)})"


class PersistenceLayer:
    """Coordinates persistence across cache, durable store and history.

    Implements Section 32.4 of the specification and is the single entry point
    used by the Runtime State Manager, the Transition Engine, the Checkpoint
    Manager and the Query Engine. The classic attributes stay part of the
    public surface: :attr:`cache`, :attr:`store` and :attr:`history`.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        storage: SQLiteStorage | None = None,
        cache: CacheLayer | None = None,
        history: HistoryStore | None = None,
    ) -> None:
        """Initialize the persistence layer.

        Args:
            db_path: Database path for the durable store; defaults to
                ``AUTOFORGE_RUNTIME_STATE_DB`` or ``":memory:"``.
            storage: Pre-built durable store (overrides ``db_path``).
            cache: Pre-built cache layer (mainly for tests).
            history: Pre-built history store (mainly for tests).
        """
        self.store: SQLiteStorage = storage if storage is not None else SQLiteStorage(db_path)
        self.cache: CacheLayer = cache if cache is not None else CacheLayer()
        self.history: HistoryStore = history if history is not None else HistoryStore(self.store)
        self._lock = threading.RLock()
        # (transaction depth, entity type, entity id) for writes made inside a
        # transaction; a rollback invalidates exactly these cache entries.
        self._pending_invalidations: list[tuple[int, EntityType, uuid.UUID]] = []

    # ── Introspection ────────────────────────────────────────────────────

    @property
    def db_path(self) -> str:
        """The resolved durable database path (``":memory:"`` when volatile)."""
        return self.store.db_path

    @property
    def is_durable(self) -> bool:
        """Whether state survives process restarts."""
        return self.store.is_durable

    @property
    def in_transaction(self) -> bool:
        """Whether a persistence transaction is in progress."""
        return self.store.in_transaction

    # ── Write path (Section 15.3) ────────────────────────────────────────

    def write_state(
        self,
        entity_type: EntityType | str,
        entity_id: uuid.UUID | str,
        state: StateModel,
        *,
        expected_version: int | None = None,
    ) -> int:
        """Write state to durable storage and update the cache.

        Returns:
            The new row revision (useful for replay/idempotency bookkeeping).

        Raises:
            VersionConflictError: If ``expected_version`` is stale.
            PersistenceError: If the state cannot be persisted.
        """
        etype = coerce_entity_type(entity_type)
        eid = coerce_entity_id(entity_id)
        with self._lock:
            revision = self.store.write(etype, eid, state, expected_version=expected_version)
            if self.store.in_transaction:
                # A rollback must not leave uncommitted state in the cache.
                self._pending_invalidations.append(
                    (self.store.transaction_depth, etype, eid)
                )
            self.cache.set(etype, eid, state)
            return revision

    def write_history(self, transition: StateTransition) -> bool:
        """Write a transition to the history store."""
        return self.history.write(transition)

    def write_checkpoint(self, checkpoint: CheckpointState) -> int:
        """Write a checkpoint to the durable store and the cache."""
        return self.write_state(EntityType.CHECKPOINT, checkpoint.checkpoint_id, checkpoint)

    def delete_state(self, entity_type: EntityType | str, entity_id: uuid.UUID | str) -> bool:
        """Delete state from the store and invalidate the cache entry."""
        etype = coerce_entity_type(entity_type)
        eid = coerce_entity_id(entity_id)
        with self._lock:
            deleted = self.store.delete(etype, eid)
            self.cache.invalidate(etype, eid)
        return deleted

    # ── Read path (Section 15.4) ─────────────────────────────────────────

    def read_state(self, entity_type: EntityType | str, entity_id: uuid.UUID | str) -> StateModel:
        """Read state, checking the cache before the durable store."""
        etype = coerce_entity_type(entity_type)
        eid = coerce_entity_id(entity_id)
        cached = self.cache.get(etype, eid)
        if cached is not None:
            return cached
        state = self.store.read(etype, eid)
        self.cache.set(etype, eid, state)
        return state

    def read_all(self, entity_type: EntityType | str) -> list[StateModel]:
        """Read all states of a given type, in insertion order."""
        return self.store.read_all(entity_type)

    def snapshot_store(self, entity_type: EntityType | str) -> dict[uuid.UUID, StateModel]:
        """Return a copy of one entity store, keyed by entity ID.

        Used by the Runtime State Manager to build immutable
        :class:`~autoforge_runtime.snapshots.RuntimeSnapshot` instances.
        """
        return self.store.snapshot_store(entity_type)

    def exists(self, entity_type: EntityType | str, entity_id: uuid.UUID | str) -> bool:
        """Return whether state exists for the identifier."""
        return self.store.exists(entity_type, entity_id)

    def get_version(
        self, entity_type: EntityType | str, entity_id: uuid.UUID | str
    ) -> int | None:
        """Return the stored state version, or ``None`` when absent."""
        return self.store.get_version(entity_type, entity_id)

    def count(self, entity_type: EntityType | str) -> int:
        """Return the number of stored entities of one type."""
        return self.store.count(entity_type)

    # ── Transactions ─────────────────────────────────────────────────────

    @contextmanager
    def transaction(self) -> Iterator[PersistenceLayer]:
        """Group writes into one atomic, rollback-safe unit of work.

        Yields:
            This persistence layer, so callers can write inside the block.

        Example:
            >>> with persistence.transaction():
            ...     persistence.write_state(EntityType.PROJECT, pid, state)
            ...     persistence.write_history(transition)
        """
        with self._lock:
            self.store.begin()
            scope_depth = self.store.transaction_depth
            try:
                yield self
            except BaseException:
                self.store.rollback()
                self._discard_pending_cache(scope_depth)
                raise
            else:
                self.store.commit()
                if not self.store.in_transaction:
                    self._pending_invalidations.clear()

    def _discard_pending_cache(self, scope_depth: int = 1) -> None:
        """Invalidate cache entries written inside a rolled-back scope.

        Entries written by an enclosing (still open) transaction stay tracked,
        so a later outer rollback still invalidates them.
        """
        with self._lock:
            remaining: list[tuple[int, EntityType, uuid.UUID]] = []
            for depth, entity_type, entity_id in self._pending_invalidations:
                if depth >= scope_depth:
                    self.cache.invalidate(entity_type, entity_id)
                else:
                    remaining.append((depth, entity_type, entity_id))
            self._pending_invalidations = remaining

    # ── Maintenance and health ───────────────────────────────────────────

    def clear(self) -> None:
        """Clear all persistence data (cache, durable store and history)."""
        with self._lock:
            self.cache.clear()
            self.store.clear()
            self.history.clear()
            self._pending_invalidations.clear()

    def backup(self, destination: str | Path) -> Path:
        """Back up the durable store to ``destination``."""
        return self.store.backup(destination)

    def health_check(self) -> dict[str, Any]:
        """Report persistence health (used by the runtime health check)."""
        report = self.store.health_check()
        report["cache"] = self.cache.stats()
        try:
            self.store.count(EntityType.PROJECT)
        except PersistenceError as exc:
            report["readable"] = False
            report["healthy"] = False
            report["error"] = str(exc)
        else:
            report["readable"] = True
        return report

    def close(self) -> None:
        """Close the durable store and the history store."""
        with self._lock:
            self.cache.clear()
            self.history.close()
            self.store.close()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        """Return a developer-friendly representation."""
        return f"PersistenceLayer(db_path={self.db_path!r})"


#: The specification's "Persistent Store" role (Section 7.3). Kept as an alias
#: so that ``autoforge_runtime.PersistentStore`` imports keep working.
PersistentStore = SQLiteStorage

__all__ = [
    "CacheLayer",
    "DB_PATH_ENV_VAR",
    "HistoryStore",
    "IN_MEMORY_PATH",
    "PersistenceLayer",
    "PersistentStore",
    "SCHEMA_VERSION",
    "SQLiteStorage",
    "coerce_entity_id",
    "coerce_entity_type",
    "entity_id_of",
    "entity_model",
    "resolve_db_path",
]
