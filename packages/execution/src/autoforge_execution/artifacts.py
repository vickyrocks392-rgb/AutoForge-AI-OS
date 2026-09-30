"""
Artifact Pipeline — captures execution outputs, logs, diffs, and provenance.

Phase 18-K Hardening:
Execution-produced artifacts are durably registered through the authoritative
runtime DurableArtifactCatalog and PhysicalArtifactStore before observational
events are published.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from autoforge_events.artifact_events import ArtifactCreated, ArtifactUpdated
from autoforge_events.base import BaseEvent

from autoforge_execution.models import (
    ArtifactProvenance,
    ArtifactRecord,
    ArtifactType,
    DiagnosisReport,
    EvaluationResult,
)


class ArtifactRetrievalError(Exception):
    """Raised when artifact retrieval encounters a persistence, I/O, or corruption error."""


class ArtifactPersistenceError(ArtifactRetrievalError):
    """Raised when durable catalog or physical store fails during artifact retrieval."""


class ArtifactPipeline:
    """
    Manages capturing, indexing, and emitting events for artifacts produced during execution.
    Integrates with DurableArtifactCatalog and PhysicalArtifactStore for crash durability.
    """

    def __init__(
        self,
        event_sink: Any = None,
        *,
        durable_catalog: Any = None,
        physical_store: Any = None,
    ) -> None:
        self._event_sink = event_sink
        self._durable_catalog = durable_catalog
        self._physical_store = physical_store
        self._artifacts: dict[uuid.UUID, ArtifactRecord] = {}
        self._by_task: dict[str, list[uuid.UUID]] = {}
        self._by_worker: dict[str, list[uuid.UUID]] = {}

    def _target_owned_by_other(
        self,
        target_rel: Any,
        artifact_id: Any,
        workflow_id: Any = None,
    ) -> bool:
        """DEF-18L-06: is this publish target already owned by a different
        committed artifact?

        Returns True only when the resolved target already exists AND a
        *different* durable artifact record for the same workflow claims that
        same storage path. An inspection failure is treated as "no collision",
        so this guard can never itself block a legitimate publish.
        """
        if self._physical_store is None or self._durable_catalog is None:
            return False
        if workflow_id is None:
            return False
        try:
            resolved = self._physical_store.resolve_artifact_path(target_rel)
            if not resolved.exists():
                return False
            for state in self._durable_catalog.find_by_workflow(workflow_id) or []:
                if str(getattr(state, "storage_path", "") or "") != str(resolved):
                    continue
                if getattr(state, "artifact_id", None) != artifact_id:
                    return True
            # Either no other record claims it, or the only claimant IS this
            # artifact (a legitimate re-publish of its own content).
            return False
        except Exception:  # pragma: no cover - defensive only
            return False

    def record_artifact(
        self,
        name: str,
        artifact_type: ArtifactType,
        content: str,
        provenance: ArtifactProvenance,
        path: str | None = None,
    ) -> ArtifactRecord:
        """
        Create and record an artifact durably, then publish an observational artifact event.
        Durable state is committed BEFORE events are emitted.
        """
        artifact_id = None
        checksum = None
        size_bytes = len(content.encode("utf-8")) if isinstance(content, str) else len(content)

        # ── Authoritative Durable Registration (Phase 18-K) ─────────────────
        if self._durable_catalog is not None:
            try:
                from autoforge_runtime.artifact_catalog import (
                    ArtifactConflictError,
                    derive_artifact_key,
                )
                from autoforge_runtime.models import DurableArtifactStatus

                exec_id = getattr(provenance, "execution_id", None) or provenance.metadata.get("execution_id")

                key = derive_artifact_key(
                    artifact_name=name,
                    workflow_id=provenance.workflow_id,
                    task_id=provenance.task_id,
                    execution_id=exec_id,
                    operation_type=artifact_type.value if hasattr(artifact_type, "value") else str(artifact_type),
                )

                # DEF-18L-05: a revised deliverable is a NEW logical version,
                # not a replay of the previous one.
                #
                # ``derive_artifact_key`` deliberately excludes the iteration,
                # because a retry must reuse the SAME key (18-J idempotent
                # replay). But an engineering loop legitimately re-writes the
                # same file on a later iteration with different content -- that
                # is a new version of the deliverable, not a retry. Registering
                # it under the iteration-less key made the second write collide
                # with the COMMITTED artifact and raise ``ArtifactConflictError``,
                # which aborted the loop.
                #
                # The 18-K catalog already models this: ``register_artifact``
                # returns the existing record for a known key, and the artifact
                # platform already mints a versioned key for a new revision
                # (``DurableArtifactStoreBridge.store_version``). The iteration
                # is therefore folded into the OPERATION SCOPE, which is the
                # existing, non-protected place for it, leaving the 18-J replay
                # guarantee untouched: a genuine retry reuses the same
                # iteration, so it still produces the same key.
                iteration = provenance.iteration or 1
                if iteration and iteration > 1:
                    key = derive_artifact_key(
                        artifact_name=name,
                        workflow_id=provenance.workflow_id,
                        task_id=provenance.task_id,
                        execution_id=exec_id,
                        operation_type=(
                            f"{artifact_type.value if hasattr(artifact_type, 'value') else artifact_type}"
                            f".iter{iteration}"
                        ),
                    )

                durable_state = self._durable_catalog.register_artifact(
                    artifact_key=key,
                    artifact_name=name,
                    artifact_type=artifact_type.value if hasattr(artifact_type, "value") else str(artifact_type),
                    workflow_id=provenance.workflow_id,
                    task_id=provenance.task_id,
                    execution_id=exec_id,
                    logical_version=iteration,
                    provenance={
                        "worker_id": provenance.worker_id,
                        "iteration": provenance.iteration,
                        "correlation_id": str(provenance.correlation_id) if provenance.correlation_id else None,
                    },
                )
                artifact_id = durable_state.artifact_id

                if self._physical_store is not None:
                    # 18-J defect repair: ``register_artifact`` is idempotent by
                    # design (a retry must NOT mint a new logical artifact
                    # identity), so on replay it returns the EXISTING record
                    # unchanged — which may already be COMMITTED.
                    #
                    # The state machine is correct: ``committed -> retired`` is
                    # the only legal exit from COMMITTED, and re-entering STAGING
                    # would un-commit durable, physically verified content. The
                    # defect was that this caller ignored the returned status and
                    # attempted to re-stage unconditionally.
                    #
                    # The correct semantic, per the DurableArtifactState contract
                    # ("an existing key reused with a differing hash is rejected
                    # with a conflict error"), is:
                    #   * already COMMITTED with the SAME content -> idempotent
                    #     replay: the artifact is already durable, so re-use it;
                    #   * already COMMITTED with DIFFERENT content -> a genuine
                    #     conflict, which must be reported, never silently
                    #     overwrite the committed artifact.
                    if durable_state.status is DurableArtifactStatus.COMMITTED:
                        incoming = (
                            content.encode("utf-8")
                            if isinstance(content, str)
                            else content
                        )
                        incoming_hash = hashlib.sha256(incoming).hexdigest()
                        if durable_state.content_hash == incoming_hash:
                            # Idempotent replay: already durable and identical.
                            artifact_id = durable_state.artifact_id
                            checksum = durable_state.content_hash
                            size_bytes = (
                                durable_state.size_bytes or len(incoming)
                            )
                            path = durable_state.storage_path or path
                        else:
                            raise ArtifactConflictError(
                                f"Artifact '{name}' is already committed with "
                                f"different content; refusing to silently "
                                f"overwrite durable artifact {artifact_id}.",
                                details={
                                    "artifact_id": str(artifact_id),
                                    "artifact_key": durable_state.artifact_key,
                                    "committed_content_hash": durable_state.content_hash,
                                    "incoming_content_hash": incoming_hash,
                                    "task_id": provenance.task_id,
                                    "worker_id": provenance.worker_id,
                                },
                            )
                    else:
                        staging_path = self._physical_store.create_staging_file(key)
                        self._durable_catalog.begin_staging(
                            artifact_id, staging_path=str(staging_path)
                        )

                        b_content = (
                            content.encode("utf-8")
                            if isinstance(content, str)
                            else content
                        )
                        c_hash, s_bytes = self._physical_store.write_staging_bytes(
                            staging_path, b_content
                        )
                        checksum = c_hash
                        size_bytes = s_bytes

                        # DEF-18L-05: publish a later revision to its OWN
                        # physical path. Publishing v2 to the same relative
                        # target as v1 would atomically replace the earlier
                        # COMMITTED bytes, so a distinct catalog record would
                        # point at content that no longer matches its recorded
                        # hash. The first version keeps its exact path.
                        target_rel = path or name
                        if iteration and iteration > 1:
                            target_rel = f"{target_rel}.v{iteration}"

                        # DEF-18L-06: never overwrite ANOTHER logical
                        # artifact's committed bytes.
                        #
                        # Two genuinely different artifacts can carry the same
                        # ``artifact_name`` (e.g. two QALoop runs both emit
                        # "qa_test_strategy.md"). They mint different catalog
                        # keys and different artifact_ids, but both resolved to
                        # the same relative target, so the second publish
                        # atomically REPLACED the first artifact's bytes. The
                        # first record stayed COMMITTED while its recorded
                        # content_hash no longer matched the file on disk --
                        # a silent durability violation.
                        #
                        # Disambiguation is applied only on an actual collision
                        # and only for a target this artifact does not already
                        # own, so the ordinary single-artifact path is byte
                        # identical to before.
                        if self._target_owned_by_other(
                            target_rel, artifact_id, provenance.workflow_id
                        ):
                            target_rel = f"{target_rel}.{artifact_id}"

                        published_p = self._physical_store.atomic_publish(
                            staging_path,
                            target_rel,
                            expected_hash=c_hash,
                            expected_size=s_bytes,
                        )
                        path = str(published_p)

                        self._durable_catalog.commit_artifact(
                            artifact_id,
                            storage_path=path,
                            content_hash=c_hash,
                            size_bytes=s_bytes,
                        )
            except Exception as e:
                logger.error(f"Durable artifact registration failed: {e}", exc_info=True)
                raise

        record = ArtifactRecord.create(
            name=name,
            artifact_type=artifact_type,
            content=content,
            path=path,
            provenance=provenance,
        )
        updates: dict[str, Any] = {"size_bytes": size_bytes}
        if artifact_id is not None:
            updates["artifact_id"] = artifact_id
        if checksum is not None:
            updates["checksum"] = checksum
        record = record.model_copy(update=updates)

        self._artifacts[record.artifact_id] = record

        # Indexing
        self._by_task.setdefault(provenance.task_id, []).append(record.artifact_id)
        self._by_worker.setdefault(provenance.worker_id, []).append(record.artifact_id)

        # Emit canonical event only AFTER durable commit
        self._emit_artifact_event(record)
        return record

    def record_evaluation_artifact(
        self,
        evaluation: EvaluationResult,
        provenance: ArtifactProvenance,
    ) -> ArtifactRecord:
        return self.record_artifact(
            name=f"evaluation_report_iter_{provenance.iteration}.json",
            artifact_type=ArtifactType.EVALUATION_REPORT,
            content=evaluation.model_dump_json(indent=2),
            provenance=provenance,
        )

    def record_diagnosis_artifact(
        self,
        diagnosis: DiagnosisReport,
        provenance: ArtifactProvenance,
    ) -> ArtifactRecord:
        return self.record_artifact(
            name=f"diagnosis_report_iter_{provenance.iteration}.json",
            artifact_type=ArtifactType.DIAGNOSIS_REPORT,
            content=diagnosis.model_dump_json(indent=2),
            provenance=provenance,
        )

    def record_diff_artifact(
        self,
        diff_text: str,
        provenance: ArtifactProvenance,
    ) -> ArtifactRecord:
        return self.record_artifact(
            name=f"changes_iter_{provenance.iteration}.diff",
            artifact_type=ArtifactType.DIFF,
            content=diff_text,
            provenance=provenance,
        )

    def get_artifact(self, artifact_id: uuid.UUID) -> ArtifactRecord | None:
        if artifact_id in self._artifacts:
            return self._artifacts[artifact_id]
        if self._durable_catalog is not None:
            try:
                state = self._durable_catalog.get_artifact(artifact_id)
            except Exception as e:
                logger.error("Durable catalog retrieval failed for artifact %s: %s", artifact_id, e, exc_info=True)
                raise ArtifactPersistenceError(
                    f"Durable catalog error retrieving artifact {artifact_id}: {e}"
                ) from e

            if state is not None:
                # Reconstruct ArtifactRecord from durable state
                art_type = ArtifactType.SOURCE_CODE
                for t in ArtifactType:
                    if t.value == state.artifact_type:
                        art_type = t
                        break
                prov_meta = dict(state.provenance.get("metadata", {}))
                if state.execution_id:
                    prov_meta["execution_id"] = str(state.execution_id)
                prov = ArtifactProvenance(
                    workflow_id=state.workflow_id,
                    task_id=state.task_id or "",
                    worker_id=state.provenance.get("worker_id", "system"),
                    iteration=state.provenance.get("iteration", state.logical_version),
                    metadata=prov_meta,
                )
                content = ""
                if state.storage_path:
                    p = Path(state.storage_path)
                    if p.exists():
                        try:
                            content = p.read_text(encoding="utf-8")
                        except Exception as io_err:
                            logger.error("Failed to read artifact content at %s: %s", state.storage_path, io_err)
                            raise ArtifactRetrievalError(
                                f"I/O error reading artifact content for {artifact_id} at {state.storage_path}: {io_err}"
                            ) from io_err
                rec = ArtifactRecord(
                    artifact_id=state.artifact_id,
                    name=state.artifact_name,
                    artifact_type=art_type,
                    content=content,
                    path=state.storage_path,
                    checksum=state.content_hash,
                    size_bytes=state.size_bytes,
                    provenance=prov,
                )
                self._artifacts[state.artifact_id] = rec
                return rec
        return None

    def get_artifacts_for_task(self, task_id: str) -> list[ArtifactRecord]:
        return [self._artifacts[aid] for aid in self._by_task.get(task_id, []) if aid in self._artifacts]

    def get_artifacts_for_worker(self, worker_id: str) -> list[ArtifactRecord]:
        return [self._artifacts[aid] for aid in self._by_worker.get(worker_id, []) if aid in self._artifacts]

    def _emit_artifact_event(self, record: ArtifactRecord) -> None:
        if not self._event_sink:
            return
        try:
            task_uuid = None
            if record.provenance.task_id:
                try:
                    task_uuid = uuid.UUID(record.provenance.task_id)
                except ValueError:
                    task_uuid = None

            event = ArtifactCreated(
                aggregate_id=record.artifact_id,
                project_id=record.provenance.workflow_id or uuid.uuid4(),
                task_id=task_uuid,
                artifact_name=record.name,
                artifact_type=record.artifact_type.value,
                file_path=record.path,
                size_bytes=record.size_bytes,
                content_hash=record.checksum,
                correlation_id=record.provenance.correlation_id,
            )
            self._event_sink.publish(event)
        except Exception:
            # Event emission failures must never break execution
            pass
