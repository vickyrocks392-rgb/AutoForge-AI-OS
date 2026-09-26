"""18-J defect reproduction: ArtifactPipeline re-records the same logical artifact.

Establishes the ACTUAL failure mechanism before any repair, so the repair targets
the true root cause rather than the error message.

Chain:
  1. Engineering loop emits an artifact (e.g. "evaluation_report_iter_1.json").
  2. record_artifact() -> register_artifact() (CREATED)
     -> begin_staging() (STAGING) -> commit_artifact() (COMMITTED).
  3. The SAME task is re-executed (resume/retry/re-materialisation).
     register_artifact() is idempotent and returns the COMMITTED record.
  4. begin_staging() is then called on a COMMITTED artifact -> InvalidTransitionError.

Note the artifact NAME is iteration-scoped in most loops, so this reproduces on
any repeated record_artifact() with an identical derived key -- which is exactly
what resume/replay does.
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _pkg in (
    "execution/src", "composition/src", "workflows/src", "ai_infrastructure/src",
    "runtime/src", "events/src", "event_platform/src", "kernel/src",
    "artifacts/src", "security/src", "models/src", "connectors/src",
    "memory/src", "knowledge_platform/src", "observability/src",
):
    _p = REPO / "packages" / _pkg
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.models import (
    ArtifactProvenance,
    ArtifactType,
)
from autoforge_runtime.artifact_catalog import (
    ArtifactConflictError,
    DurableArtifactCatalog,
)
from autoforge_runtime.exceptions import InvalidTransitionError
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore


def build(tmp: Path):
    store = PhysicalArtifactStore(
        artifact_root=tmp / "artifacts",
        staging_root=tmp / "artifacts" / ".staging",
        quarantine_root=tmp / "artifacts" / ".quarantine",
    )
    catalog = DurableArtifactCatalog(persistence=PersistenceLayer(), physical_store=store)
    return store, catalog


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="af_18j_repro_"))
    store, catalog = build(tmp)
    pipeline = ArtifactPipeline(durable_catalog=catalog, physical_store=store)

    provenance = ArtifactProvenance(
        task_id="t-18j-repro",
        worker_id="w-1",
        workflow_id=uuid.UUID("11111111-1111-5111-8111-111111111111"),
        correlation_id=uuid.UUID("22222222-2222-5222-8222-222222222222"),
        attempt_number=1,
        iteration=1,
    )

    print("--- pass 1: first materialisation ---")
    first = pipeline.record_artifact(
        name="evaluation_report_iter_1.json",
        artifact_type=ArtifactType.EVALUATION_REPORT,
        content='{"passed": false}',
        provenance=provenance,
    )
    state = catalog.get_artifact(first.artifact_id)
    print("status after pass 1 :", state.status.value)

    print("--- pass 2a: resume / re-materialisation, IDENTICAL content ---")
    try:
        second = pipeline.record_artifact(
            name="evaluation_report_iter_1.json",
            artifact_type=ArtifactType.EVALUATION_REPORT,
            content='{"passed": false}',
            provenance=provenance,
        )
        st = catalog.get_artifact(second.artifact_id)
        print("  same artifact_id  :", second.artifact_id == first.artifact_id)
        print("  status            :", st.status.value)
        print("  RESULT: idempotent replay OK")
        ok = True
    except Exception as exc:
        print("  RESULT:", type(exc).__name__, "-", exc)
        ok = False

    print("--- pass 2b: same key, DIFFERENT content (must conflict, not corrupt) ---")
    try:
        pipeline.record_artifact(
            name="evaluation_report_iter_1.json",
            artifact_type=ArtifactType.EVALUATION_REPORT,
            content='{"passed": true, "DIFFERENT": true}',
            provenance=provenance,
        )
        print("  RESULT: NO ERROR (BAD - committed artifact was overwritten)")
        ok = False
    except ArtifactConflictError as exc:
        st = catalog.get_artifact(first.artifact_id)
        print("  RESULT: ArtifactConflictError (correct)")
        print("  committed state preserved:", st.status.value, st.content_hash[:12])
        ok = ok and st.status.value == "committed"
    except Exception as exc:
        print("  RESULT:", type(exc).__name__, "-", exc)
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
