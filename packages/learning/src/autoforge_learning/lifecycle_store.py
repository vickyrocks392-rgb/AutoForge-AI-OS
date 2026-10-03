"""Durable, project-scoped learning lifecycle store — Phase 19 FINAL (Gate 8).

The 19B-2 store in :mod:`autoforge_learning.store` persists the promotion
path (candidates, evaluations, approvals, promotions, handles, rollbacks,
active pointers). Phase 19 FINAL closes the "several services still hold state
in memory" limitation by persisting the *whole* learning lifecycle so a process
restart loses nothing that matters: experiences, signals, hypotheses,
experiments, runs, activations, regressions, lineage and PI-8 measurements.

Design constraints, unchanged from the 19B-2 store and re-asserted here:

* **Reuse the existing filesystem discipline** — staging write, ``fsync``,
  ``os.replace``, directory ``fsync``. A reader only ever sees a complete
  record. No new storage framework is invented.
* **Append-only.** Records are written once; nothing is edited in place, so
  history is never silently rewritten.
* **Project isolation is structural.** Records live under a per-project
  directory; every read is project-scoped.
* **Fail closed.** Corruption, truncation, a wrong hash, a wrong project or a
  stale schema raises. Corruption is *never* converted into an empty-but-
  successful result.
* **Loss is never silent.** ``verify_complete`` reports exactly which record
  kinds exist, so a partially-written lifecycle cannot look healthy.

Ephemeral data (an in-flight experiment's stdout buffer, a cached metric) is
deliberately not persisted — it is safe to lose. Everything that governs an
authority-bearing decision is.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from autoforge_learning.store import (
    LIFECYCLE_SCHEMA_VERSION,
    LearningImmutableIdentityError,
    LearningProjectIsolationError,
    LearningRecordCorrupt,
)

logger = logging.getLogger("autoforge.learning.lifecycle_store")

__test__ = False  # declares persistence, not tests


class LifecycleEnvelope(BaseModel):
    """On-disk envelope around every Phase 19 FINAL lifecycle record.

    Carries the schema version, record kind, owning project, record identity,
    payload, and a content hash recomputed on every read. A record that does
    not verify is rejected rather than returned.
    """

    store_schema_version: str = LIFECYCLE_SCHEMA_VERSION
    kind: str
    project_id: uuid.UUID
    record_id: str
    payload: dict[str, Any]
    content_hash: str = ""


class LifecycleIntegrityError(LearningRecordCorrupt):
    """A lifecycle record's stored hash does not match its payload."""


#: kind -> (id attribute, model class, on-disk collection). Populated lazily to
#: avoid a circular import at module load. ``record_id`` is always the record's
#: own identity — never a caller-supplied path — so a crafted identifier can
#: never traverse out of the project directory.
_LIFECYCLE_KINDS: dict[str, tuple[str, type[BaseModel], str]] = {}


def _install_registry() -> None:
    if _LIFECYCLE_KINDS:
        return
    from autoforge_learning.activation import ActivationRecord
    from autoforge_learning.experiments import Experiment, ExperimentRun
    from autoforge_learning.models import (
        ExecutionObservation,
        Hypothesis,
        LearningLineage,
        LearningSignal,
    )
    from autoforge_learning.monitoring import RegressionReport

    _LIFECYCLE_KINDS.update(
        {
            "observation": ("observation_id", ExecutionObservation, "observations"),
            "signal": ("signal_id", LearningSignal, "signals"),
            "hypothesis": ("hypothesis_id", Hypothesis, "hypotheses"),
            "experiment": ("experiment_id", Experiment, "experiments"),
            "experiment_run": ("run_id", ExperimentRun, "experiment_runs"),
            "activation": ("activation_id", ActivationRecord, "activations"),
            "regression": ("report_id", RegressionReport, "regressions"),
            "lineage": ("lineage_id", LearningLineage, "lineage"),
        }
    )


class DurableLearningLifecycleStore:
    """Project-scoped, crash-safe persistence for the whole learning lifecycle.

    Layout (per project)::

        <root>/<project_id>/observations/<observation_id>.json
        <root>/<project_id>/signals/<signal_id>.json
        <root>/<project_id>/hypotheses/<hypothesis_id>.json
        <root>/<project_id>/experiments/<experiment_id>.json
        <root>/<project_id>/experiment_runs/<run_id>.json
        <root>/<project_id>/activations/<activation_id>.json
        <root>/<project_id>/regressions/<report_id>.json
        <root>/<project_id>/lineage/<lineage_id>.json
        <root>/<project_id>/pi8/<measurement_id>.json
    """

    #: Record kinds a healthy lifecycle is expected to contain. ``verify_complete``
    #: reports counts for all of them so a gap is explicit rather than assumed.
    REQUIRED_KINDS = (
        "observation",
        "signal",
        "hypothesis",
        "experiment",
        "experiment_run",
        "activation",
        "regression",
        "lineage",
    )

    def __init__(self, root: str | Path) -> None:
        _install_registry()
        self._root = Path(root)
        self._lock = threading.RLock()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ── paths ────────────────────────────────────────────────────────────────

    def _project_dir(self, project_id: uuid.UUID) -> Path:
        return self._root / str(project_id)

    def _path(
        self, project_id: uuid.UUID, collection: str, record_id: str, ext: str = "json"
    ) -> Path:
        # Sanitise: a record_id is never used as a caller-supplied path.
        safe = str(record_id).replace("/", "_").replace("\\", "_").replace("..", "_")
        return self._project_dir(project_id) / collection / f"{safe}.{ext}"

    # ── atomic durable write ─────────────────────────────────────────────────

    def _write_atomic(self, path: Path, data: bytes) -> None:
        """Publish ``data`` at ``path`` atomically and durably.

        Same discipline as the 19B-2 store and ``PhysicalArtifactStore``: a
        reader therefore only ever observes a fully written record.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_name(f".{path.name}.staging")
        with open(staging, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(staging, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    # ── generic persist / load ───────────────────────────────────────────────

    def save(self, record: BaseModel, *, kind: str) -> BaseModel:
        """Persist one lifecycle record, refusing to mutate an existing one.

        Re-saving the identical record is idempotent. Re-saving *different*
        content under the same identity raises, so history cannot be rewritten.
        """
        entry = _LIFECYCLE_KINDS.get(kind)
        if entry is None:
            raise LearningRecordCorrupt(f"unknown lifecycle record kind {kind!r}")
        id_attr, _, collection = entry
        record_id = str(getattr(record, id_attr, "") or "")
        if not record_id:
            raise LearningRecordCorrupt(f"{kind} record has no {id_attr}")
        project_id = _record_project(record, kind)

        existing = self.load(project_id, kind, record_id)
        if existing is not None:
            if _content_hash(existing) != _content_hash(record):
                raise LearningImmutableIdentityError(
                    f"{kind} {record_id} already exists with different content; "
                    f"lifecycle records are append-only"
                )
            return existing

        payload = record.model_dump(mode="json")
        envelope = LifecycleEnvelope(
            kind=kind,
            project_id=project_id,
            record_id=record_id,
            payload=payload,
            content_hash=_hash_payload(payload),
        )
        data = json.dumps(
            envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        with self._lock:
            self._write_atomic(self._path(project_id, collection, record_id), data)
        return record

    def load(
        self, project_id: uuid.UUID, kind: str, record_id: str
    ) -> Optional[BaseModel]:
        """Load one lifecycle record. ``None`` only if genuinely absent.

        Corruption, truncation, a wrong hash, a wrong project, or a mismatched
        schema all raise — they are never reported as an absent record.
        """
        entry = _LIFECYCLE_KINDS.get(kind)
        if entry is None:
            raise LearningRecordCorrupt(f"unknown lifecycle record kind {kind!r}")
        _, model, collection = entry
        path = self._path(project_id, collection, record_id)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
        except OSError as ex:
            raise LearningRecordCorrupt(
                f"unreadable lifecycle record at {path}: {ex}"
            ) from ex
        try:
            envelope = LifecycleEnvelope.model_validate(
                json.loads(raw.decode("utf-8"))
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as ex:
            raise LearningRecordCorrupt(
                f"corrupt lifecycle record at {path}: {type(ex).__name__}: {ex}"
            ) from ex

        if envelope.project_id != project_id:
            raise LearningProjectIsolationError(
                f"record at {path} belongs to project {envelope.project_id}, "
                f"not {project_id}"
            )
        if envelope.store_schema_version != LIFECYCLE_SCHEMA_VERSION:
            raise LearningRecordCorrupt(
                f"record at {path} has schema {envelope.store_schema_version!r}; "
                f"this store reads {LIFECYCLE_SCHEMA_VERSION!r}"
            )
        if envelope.content_hash != _hash_payload(envelope.payload):
            raise LifecycleIntegrityError(
                f"lifecycle record {kind}:{record_id} failed integrity "
                f"verification (stored hash does not match payload)"
            )
        try:
            return model.model_validate(envelope.payload)
        except ValidationError as ex:
            raise LearningRecordCorrupt(
                f"malformed {kind} record at {path}: {ex}"
            ) from ex

    def list(self, project_id: uuid.UUID, kind: str) -> tuple[BaseModel, ...]:
        """Every record of ``kind`` for one project, deterministic order.

        A corrupt record aborts the listing rather than being skipped:
        silently dropping an unreadable record would be silent data loss.
        """
        entry = _LIFECYCLE_KINDS.get(kind)
        if entry is None:
            raise LearningRecordCorrupt(f"unknown lifecycle record kind {kind!r}")
        _, _, collection = entry
        directory = self._project_dir(project_id) / collection
        if not directory.is_dir():
            return ()
        out: list[BaseModel] = []
        for path in sorted(directory.glob("*.json")):
            record = self.load(project_id, kind, path.stem)
            if record is not None:
                out.append(record)
        return tuple(out)

    def verify_complete(self, project_id: uuid.UUID) -> dict[str, int]:
        """Count every lifecycle record kind for a project.

        Used by crash recovery: a kind with zero records where one is expected
        is reported explicitly rather than assumed healthy.
        """
        counts = {
            k: len(self.list(project_id, k)) for k in self.REQUIRED_KINDS
        }
        counts["pi8"] = len(self.list_pi8(project_id))
        return counts

    # ── typed convenience accessors ──────────────────────────────────────────

    def save_observation(self, record: Any) -> Any:
        return self.save(record, kind="observation")

    def load_observation(self, project_id: uuid.UUID, observation_id: uuid.UUID) -> Any:
        return self.load(project_id, "observation", str(observation_id))

    def list_observations(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        return self.list(project_id, "observation")

    def save_signal(self, record: Any) -> Any:
        return self.save(record, kind="signal")

    def load_signal(self, project_id: uuid.UUID, signal_id: uuid.UUID) -> Any:
        return self.load(project_id, "signal", str(signal_id))

    def list_signals(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        return self.list(project_id, "signal")

    def save_hypothesis(self, record: Any) -> Any:
        return self.save(record, kind="hypothesis")

    def load_hypothesis(self, project_id: uuid.UUID, hypothesis_id: uuid.UUID) -> Any:
        return self.load(project_id, "hypothesis", str(hypothesis_id))

    def list_hypotheses(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        return self.list(project_id, "hypothesis")

    def save_experiment(self, record: Any) -> Any:
        return self.save(record, kind="experiment")

    def load_experiment(self, project_id: uuid.UUID, experiment_id: uuid.UUID) -> Any:
        return self.load(project_id, "experiment", str(experiment_id))

    def list_experiments(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        return self.list(project_id, "experiment")

    def save_experiment_run(self, record: Any) -> Any:
        return self.save(record, kind="experiment_run")

    def load_experiment_run(self, project_id: uuid.UUID, run_id: uuid.UUID) -> Any:
        return self.load(project_id, "experiment_run", str(run_id))

    def list_experiment_runs(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        return self.list(project_id, "experiment_run")

    def save_activation(self, record: Any) -> Any:
        return self.save(record, kind="activation")

    def load_activation(self, project_id: uuid.UUID, activation_id: uuid.UUID) -> Any:
        return self.load(project_id, "activation", str(activation_id))

    def list_activations(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        return self.list(project_id, "activation")

    def save_regression(self, record: Any) -> Any:
        return self.save(record, kind="regression")

    def load_regression(self, project_id: uuid.UUID, report_id: uuid.UUID) -> Any:
        return self.load(project_id, "regression", str(report_id))

    def list_regressions(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        return self.list(project_id, "regression")

    def save_lineage(self, record: Any) -> Any:
        return self.save(record, kind="lineage")

    def load_lineage(self, project_id: uuid.UUID, lineage_id: uuid.UUID) -> Any:
        return self.load(project_id, "lineage", str(lineage_id))

    def list_lineage(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        return self.list(project_id, "lineage")

    # ── PI-8 outcome measurements ─────────────────────────────────────────────

    def _pi8_path(self, project_id: uuid.UUID, measurement_id: str) -> Path:
        safe = (
            str(measurement_id)
            .replace("/", "_")
            .replace("\\", "_")
            .replace("..", "_")
        )
        return self._project_dir(project_id) / "pi8" / f"{safe}.json"

    def save_pi8(self, measurement: Any) -> Any:
        """Persist one PI-8 outcome measurement built from real evidence.

        PI-8 measurements are append-only and each carries its own numerator
        and denominator. There is no default-success path: a measurement is
        only ever written from a measured population.
        """
        measurement_id = str(getattr(measurement, "measurement_id", "") or "")
        if not measurement_id:
            raise LearningRecordCorrupt("PI-8 measurement has no measurement_id")
        project_id = getattr(measurement, "project_id", None)
        if project_id is None:
            raise LearningRecordCorrupt("PI-8 measurement has no project_id")
        payload = measurement.model_dump(mode="json")
        envelope = LifecycleEnvelope(
            kind="pi8",
            project_id=project_id,
            record_id=measurement_id,
            payload=payload,
            content_hash=_hash_payload(payload),
        )
        data = json.dumps(
            envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        with self._lock:
            self._write_atomic(self._pi8_path(project_id, measurement_id), data)
        return measurement

    def load_pi8(self, project_id: uuid.UUID, measurement_id: str) -> Optional[Any]:
        """Load a PI-8 measurement. Corruption raises; absence returns ``None``."""
        from autoforge_learning.outcomes import CustomerOutcomeMeasurement

        path = self._pi8_path(project_id, measurement_id)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
            envelope = LifecycleEnvelope.model_validate(
                json.loads(raw.decode("utf-8"))
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as ex:
            raise LearningRecordCorrupt(
                f"corrupt PI-8 measurement at {path}: {type(ex).__name__}: {ex}"
            ) from ex
        if envelope.project_id != project_id:
            raise LearningProjectIsolationError(
                f"PI-8 measurement belongs to project {envelope.project_id}, "
                f"not {project_id}"
            )
        if envelope.content_hash != _hash_payload(envelope.payload):
            raise LifecycleIntegrityError(
                f"PI-8 measurement {measurement_id} failed integrity verification"
            )
        try:
            return CustomerOutcomeMeasurement.model_validate(envelope.payload)
        except ValidationError as ex:
            raise LearningRecordCorrupt(f"malformed PI-8 measurement: {ex}") from ex

    def list_pi8(self, project_id: uuid.UUID) -> tuple[Any, ...]:
        directory = self._project_dir(project_id) / "pi8"
        if not directory.is_dir():
            return ()
        out = []
        for path in sorted(directory.glob("*.json")):
            record = self.load_pi8(project_id, path.stem)
            if record is not None:
                out.append(record)
        return tuple(out)
# ── module-level helpers ────────────────────────────────────────────────────


def _record_project(record: BaseModel, kind: str) -> uuid.UUID:
    """Extract the owning project id from a lifecycle record."""
    scope = getattr(record, "scope", None)
    if scope is not None and getattr(scope, "project_id", None) is not None:
        return scope.project_id
    pid = getattr(record, "project_id", None)
    if pid is None:
        raise LearningRecordCorrupt(f"{kind} record has no owning project")
    return pid


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _content_hash(record: BaseModel) -> str:
    return _hash_payload(record.model_dump(mode="json"))
