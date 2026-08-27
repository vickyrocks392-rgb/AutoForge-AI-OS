"""
Artifact Pipeline — captures execution outputs, logs, diffs, and provenance.

Phase 10 provides execution-side artifact handling with rich provenance
metadata, compatible with the future Phase 12 Artifact Platform.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_events.artifact_events import ArtifactCreated, ArtifactUpdated
from autoforge_events.base import BaseEvent

from autoforge_execution.models import (
    ArtifactProvenance,
    ArtifactRecord,
    ArtifactType,
    DiagnosisReport,
    EvaluationResult,
)


class ArtifactPipeline:
    """
    Manages capturing, indexing, and emitting events for artifacts produced during execution.
    """

    def __init__(self, event_sink: Any = None) -> None:
        self._event_sink = event_sink
        self._artifacts: dict[uuid.UUID, ArtifactRecord] = {}
        self._by_task: dict[str, list[uuid.UUID]] = {}
        self._by_worker: dict[str, list[uuid.UUID]] = {}

    def record_artifact(
        self,
        name: str,
        artifact_type: ArtifactType,
        content: str,
        provenance: ArtifactProvenance,
        path: str | None = None,
    ) -> ArtifactRecord:
        """
        Create and record an artifact, and publish an artifact event.
        """
        record = ArtifactRecord.create(
            name=name,
            artifact_type=artifact_type,
            content=content,
            path=path,
            provenance=provenance,
        )
        self._artifacts[record.artifact_id] = record

        # Indexing
        self._by_task.setdefault(provenance.task_id, []).append(record.artifact_id)
        self._by_worker.setdefault(provenance.worker_id, []).append(record.artifact_id)

        # Emit canonical event if sink available
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
        return self._artifacts.get(artifact_id)

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
