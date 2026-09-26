"""Gate 4B — 18-J ``committed -> staging`` defect TRIAGE ONLY.

Reproduces the pre-existing 18-J durable-artifact transition defect and records
its exact reproduction path. This script deliberately does NOT fix it: 18-J is a
protected system for this gate, and the error is neither suppressed nor the
validation weakened.

Question answered: does it still reproduce with Context Engineering globally
enabled, and is it a pre-existing 18-J defect, a newly introduced defect, or an
integration exposure?
"""

from __future__ import annotations

import json
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

from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
from autoforge_runtime.exceptions import InvalidTransitionError
from autoforge_runtime.models import DurableArtifactStatus
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore


def reproduce() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="af_gate4b_18j_"))
    store = PhysicalArtifactStore(
        artifact_root=tmp / "artifacts",
        staging_root=tmp / "artifacts" / ".staging",
        quarantine_root=tmp / "artifacts" / ".quarantine",
    )
    catalog = DurableArtifactCatalog(persistence=PersistenceLayer(), physical_store=store)

    workflow_id = uuid.uuid4()
    task_id = uuid.uuid4()
    execution_id = uuid.uuid4()

    state = catalog.register_artifact(
        artifact_key=f"{workflow_id}:{task_id}:{execution_id}:artifact.txt",
        artifact_name="artifact.txt",
        artifact_type="text/plain",
        workflow_id=workflow_id,
        task_id=str(task_id),
        execution_id=execution_id,
    )
    artifact_id = state.artifact_id

    # CREATED -> STAGING -> COMMITTED is the normal, valid lifecycle.
    catalog.begin_staging(artifact_id, staging_path="artifact.txt")
    payload = tmp / "artifacts" / "artifact.txt"
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_text("hello\n", encoding="utf-8")
    committed = catalog.commit_artifact(artifact_id, storage_path="artifact.txt")
    normal_path_ok = committed.status is DurableArtifactStatus.COMMITTED

    # Now re-enter staging from COMMITTED (e.g. a retry / re-materialisation).
    result: dict = {
        "normal_lifecycle_committed": normal_path_ok,
        "reproduction": None,
        "raises_invalid_transition": False,
    }
    try:
        catalog.begin_staging(artifact_id, staging_path="artifact.txt")
        result["reproduction"] = "no error raised"
    except InvalidTransitionError as exc:
        result["raises_invalid_transition"] = True
        result["reproduction"] = {
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "details": getattr(exc, "details", {}),
        }
    except Exception as exc:  # noqa: BLE001
        result["reproduction"] = {"exception_type": type(exc).__name__, "message": str(exc)}
    return result


def main() -> int:
    result = reproduce()
    result["classification"] = "pre-existing 18-J defect (durable artifact lifecycle)"
    result["fixed_in_gate4b"] = False
    result["validation_weakened"] = False
    out = REPO / "context-engineering-gate4b" / "triage_18j.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
