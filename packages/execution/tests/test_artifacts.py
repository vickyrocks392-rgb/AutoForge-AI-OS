"""
Unit tests for ArtifactPipeline and provenance tracking.
"""

import uuid
import pytest

from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.models import (
    ArtifactProvenance,
    ArtifactType,
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
)


class MockEventSink:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def test_artifact_pipeline_record_and_index():
    sink = MockEventSink()
    pipeline = ArtifactPipeline(sink)

    prov = ArtifactProvenance(
        task_id="t-art-1",
        worker_id="w-art-1",
        workflow_id=uuid.uuid4(),
        attempt_number=1,
        iteration=1,
    )

    art = pipeline.record_artifact(
        name="output.json",
        artifact_type=ArtifactType.METRIC,
        content='{"score": 98}',
        provenance=prov,
    )

    assert art.name == "output.json"
    assert pipeline.get_artifact(art.artifact_id) == art
    assert pipeline.get_artifacts_for_task("t-art-1") == [art]
    assert pipeline.get_artifacts_for_worker("w-art-1") == [art]
    assert len(sink.events) == 1


def test_artifact_pipeline_evaluation_and_diagnosis_artifacts():
    pipeline = ArtifactPipeline()
    prov = ArtifactProvenance(task_id="t-eval", worker_id="w-1", iteration=2)

    eval_res = EvaluationResult(status=EvaluationStatus.PASSED)
    eval_art = pipeline.record_evaluation_artifact(eval_res, prov)
    assert eval_art.artifact_type == ArtifactType.EVALUATION_REPORT
    assert "passed" in eval_art.content

    diag = DiagnosisReport(root_cause="Syntax Error in line 12")
    diag_art = pipeline.record_diagnosis_artifact(diag, prov)
    assert diag_art.artifact_type == ArtifactType.DIAGNOSIS_REPORT
    assert "Syntax Error" in diag_art.content
