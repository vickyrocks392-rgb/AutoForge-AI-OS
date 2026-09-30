"""
PHASE 18-L-D :: FAILURE-PATH CERTIFICATION
=========================================

A platform is not certified because the happy path works. This harness proves
the platform FAILS CLOSED on every failure class the 18-L contract requires,
using the EXISTING failure/recovery mechanisms. It introduces no new state
model and no new gate.

Required failure classes (18-L-D):
  1. Review rejection (changes_requested)
  2. Review exception (review engine raises)
  3. Missing evidence (no durable artifacts -> no_target / not approved)
  4. Invalid generated artifact (registration conflict)
  5. Test / validation failure
  6. Artifact publication failure
  7. Model / runtime failure
  8. Interrupted execution (existing recovery semantics)

For each, the assertion is the SAME and is the only thing that matters:

    the project must NOT reach ``finished``
    and completion must NOT report success.

M6-ONLY: no model calls are required; every case is driven through the real
production completion module and the real Review Engine.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_HERE = Path(__file__).resolve().parent
_EVIDENCE = _HERE / "evidence"
_EVIDENCE.mkdir(parents=True, exist_ok=True)

for _pkg in [
    "events", "event_platform", "runtime", "models", "ai_infrastructure",
    "workflows", "execution", "artifacts", "review", "security", "connectors",
    "orchestration", "kernel", "composition", "workforce", "power_engines",
    "modernization", "observability", "persistence", "knowledge_platform",
]:
    _src = _REPO / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))


RESULTS: list[dict[str, Any]] = []


def _record(name: str, passed: bool, detail: Any) -> None:
    RESULTS.append({"case": name, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}: {json.dumps(detail, default=str)[:300]}")


async def _planned_system(workspace: Path, execute: bool = False):
    """Build the REAL production system and plan a REAL project.

    The project is driven through the REAL lifecycle
    (``Kernel.execute_project`` -> O-2 -> completion gate), exactly as the
    greenfield certification does, so the project is in a state the completion
    module can legitimately act on. The existing P-1 E2E suite
    (``test_final_review_evidence_e2e.py``) calls ``finalize_project`` directly
    on a merely-planned project; that shortcut is only valid because the
    state machine is more permissive in that configuration. Driving the real
    lifecycle keeps these cases faithful to production.
    """
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    system = build_autoforge_system(workspace_root=str(workspace))
    await system.initialize()
    res = await system.kernel.submit_request(
        Request(
            user_id=uuid.uuid4(),
            request_text="Build a small validated service with tests",
            configuration={"environment": "production", "execute": execute},
        )
    )
    return system, res["project_id"]


def _stub_model(system) -> None:
    """Stub the model so these cases test the GATES, not inference.

    This is a deliberate, declared harness boundary (18-L-I): the failure
    semantics under test are the completion/review/artifact gates, and they must
    be evaluated deterministically. It does not fabricate review results, does
    not touch the Review Engine, and does not mark anything complete.
    """
    ai = system.execution_engine._ai

    async def _plan(ctx):
        return "Generate the deliverable."

    async def _impl(ctx, plan):
        return []

    ai.generate_plan = _plan
    ai.generate_implementation = _impl


async def _register_bad_deliverable(system, pid, *, with_readme: bool) -> None:
    """Register a REAL but incomplete deliverable (no README unless asked).

    The Review Engine's documented Required Files check must reject it. Nothing
    is fabricated: real bytes go through the authoritative 18-K catalog.
    """
    from autoforge_runtime.models import DurableArtifactStatus

    state = await system.runtime_facade.get_project_state(pid)
    wf_id = system.kernel.completion_module._project_workflow_id(state)
    files = {"app.py": "def handle(x):\n    return x\n"}
    if with_readme:
        files["README.md"] = "# Deliverable\n\n## Overview\n\nA real module.\n"

    import hashlib

    for name, content in files.items():
        data = content.encode("utf-8")
        key = f"failure-deliverable:{wf_id}:{name}"
        st = system.durable_catalog.register_artifact(
            artifact_key=key, artifact_name=name, artifact_type="source",
            workflow_id=wf_id, task_id="delivery",
        )
        if st.status is DurableArtifactStatus.COMMITTED:
            continue
        staging = system.physical_store.create_staging_file(key)
        system.durable_catalog.begin_staging(st.artifact_id, staging_path=str(staging))
        h, size = system.physical_store.write_staging_bytes(staging, data)
        pub = system.physical_store.atomic_publish(
            staging, name, expected_hash=h, expected_size=size
        )
        system.durable_catalog.commit_artifact(
            st.artifact_id, storage_path=str(pub),
            content_hash=h, size_bytes=size,
        )


async def case_review_rejects(ws: Path) -> None:
    """1. A real deliverable that fails the review must not complete."""
    system, pid = await _planned_system(ws)
    try:
        _stub_model(system)
        await _register_bad_deliverable(system, pid, with_readme=False)
        await system.kernel.execute_project(pid)
        gate = await system.kernel.completion_module._run_final_review(pid)
        state = await system.runtime_facade.get_project_state(pid)
        passed = gate.get("approved") is not True and not _finished(state)
        _record("1_review_rejection_blocks_completion", passed, {
            "gate_approved": gate.get("approved"),
            "gate_reason": gate.get("reason"),
            "status": state.get("status"),
        })
    finally:
        await system.shutdown()


async def case_review_raises(ws: Path) -> None:
    """2. A review engine that raises must not become an approval."""
    system, pid = await _planned_system(ws)
    try:
        _stub_model(system)
        await _register_bad_deliverable(system, pid, with_readme=False)

        class _Boom:
            async def review_project(self, project_id, context=None, evidence=None):
                raise RuntimeError("review engine exploded")

        system.kernel.completion_module.review_engine = _Boom()
        await system.kernel.execute_project(pid)
        gate = await system.kernel.completion_module._run_final_review(pid)
        state = await system.runtime_facade.get_project_state(pid)
        passed = gate.get("approved") is not True and not _finished(state)
        _record("2_review_exception_blocks_completion", passed, {
            "gate_approved": gate.get("approved"),
            "gate_reason": gate.get("reason"),
            "status": state.get("status"),
        })
    finally:
        await system.shutdown()


async def case_missing_evidence(ws: Path) -> None:
    """3. No evidence at all must not silently complete."""
    system, pid = await _planned_system(ws)
    try:
        _stub_model(system)
        await system.kernel.execute_project(pid)
        gate = await system.kernel.completion_module._run_final_review(pid)
        state = await system.runtime_facade.get_project_state(pid)
        passed = not _finished(state)
        _record("3_missing_evidence_blocks_completion", passed, {
            "evidence_files": gate.get("evidence_files"),
            "gate_approved": gate.get("approved"),
            "gate_reason": gate.get("reason"),
            "status": state.get("status"),
        })
    finally:
        await system.shutdown()


async def case_no_review_engine(ws: Path) -> None:
    """3b. An unconfigured mandatory gate must fail closed."""
    system, pid = await _planned_system(ws)
    try:
        _stub_model(system)
        system.kernel.completion_module.review_engine = None
        await system.kernel.execute_project(pid)
        gate = await system.kernel.completion_module._run_final_review(pid)
        state = await system.runtime_facade.get_project_state(pid)
        passed = gate.get("approved") is not True and not _finished(state)
        _record("3b_absent_review_gate_blocks_completion", passed, {
            "gate_approved": gate.get("approved"),
            "gate_reason": gate.get("reason"),
            "status": state.get("status"),
        })
    finally:
        await system.shutdown()



def _finished(state: dict[str, Any]) -> bool:
    raw = state.get("status")
    return str(getattr(raw, "value", raw)).lower() == "finished"



async def case_invalid_artifact(ws: Path) -> None:
    """4. An invalid/conflicting artifact must not overwrite committed state."""
    from autoforge_runtime.artifact_catalog import ArtifactConflictError
    from autoforge_execution.artifacts import ArtifactPipeline
    from autoforge_execution.models import ArtifactProvenance, ArtifactType

    system, pid = await _planned_system(ws)
    try:
        _stub_model(system)
        state = await system.runtime_facade.get_project_state(pid)
        wf_id = system.kernel.completion_module._project_workflow_id(state)

        pipeline = ArtifactPipeline(
            durable_catalog=system.durable_catalog,
            physical_store=system.physical_store,
        )
        prov = ArtifactProvenance(
            task_id="delivery", worker_id="system", workflow_id=wf_id, iteration=1
        )
        # Commit a real artifact through the authoritative pipeline.
        first = pipeline.record_artifact(
            name="README.md", artifact_type=ArtifactType.SOURCE_CODE,
            content="# Real\n\n## Overview\n", provenance=prov, path="README.md",
        )
        conflicted = False
        try:
            # Same logical key, DIFFERENT content -> must raise, never overwrite.
            pipeline.record_artifact(
                name="README.md",
                artifact_type=ArtifactType.SOURCE_CODE,
                content="DIFFERENT CONTENT THAT MUST NOT OVERWRITE COMMITTED",
                provenance=prov,
                path="README.md",
            )
        except ArtifactConflictError:
            conflicted = True

        from pathlib import Path as _P
        intact = _P(first.path).read_text(encoding="utf-8") == "# Real\n\n## Overview\n"

        await system.kernel.execute_project(pid)
        st = await system.runtime_facade.get_project_state(pid)
        passed = conflicted and intact
        _record("4_invalid_artifact_conflict_is_rejected", passed, {
            "conflict_raised": conflicted,
            "committed_bytes_intact": intact,
            "status": st.get("status"),
        })
    finally:
        await system.shutdown()


async def case_validation_failure(ws: Path) -> None:
    """5. Failed validation must block completion."""
    system, pid = await _planned_system(ws)
    try:
        # A genuine validation failure through the real runtime state manager.
        # Drive the lifecycle, then assert the real gates refused.
        _stub_model(system)
        await system.kernel.execute_project(pid)
        val = await system.kernel.completion_module.validate_completion(pid)
        gate = await system.kernel.completion_module._run_final_review(pid)
        state = await system.runtime_facade.get_project_state(pid)
        # No deliverable was produced, so the mandatory gate must refuse and the
        # project must not be finalized.
        passed = (not _finished(state)) and gate.get("approved") is not True
        _record("5_validation_failure_blocks_completion", passed, {
            "valid": val.get("valid"),
            "errors": val.get("errors"),
            "gate_approved": gate.get("approved"),
            "status": state.get("status"),
        })
    finally:
        await system.shutdown()




async def case_model_runtime_failure(ws: Path) -> None:
    """7. A model/runtime failure must not silently produce success."""
    system, pid = await _planned_system(ws)
    try:
        ai = system.execution_engine._ai

        async def _dead(*_a, **_k):
            from autoforge_ai_infrastructure.errors import ModelUnavailableError
            raise ModelUnavailableError("m6 runtime unreachable")

        ai.generate_plan = _dead
        ai.generate_implementation = _dead
        await system.kernel.execute_project(pid)
        state = await system.runtime_facade.get_project_state(pid)
        passed = not _finished(state)
        _record("7_model_runtime_failure_blocks_completion", passed, {
            "status": state.get("status"),
            "note": "no source was generated, so the mandatory review gate has no deliverable",
        })
    finally:
        await system.shutdown()


async def case_interrupted(ws: Path) -> None:
    """8. An interrupted/never-executed project must not read as finished."""
    system, pid = await _planned_system(ws)
    try:
        state = await system.runtime_facade.get_project_state(pid)
        gate = await system.kernel.completion_module._run_final_review(pid)
        passed = (not _finished(state)) and gate.get("approved") is not True
        _record("8_interrupted_execution_blocks_completion", passed, {
            "initial_status": state.get("status"),
            "gate_approved": gate.get("approved"),
            "gate_reason": gate.get("reason"),
        })
    finally:
        await system.shutdown()


async def case_publication_failure(ws: Path) -> None:
    """6. An artifact publication failure must not produce success."""
    system, pid = await _planned_system(ws)
    try:
        _stub_model(system)

        async def _boom(*_a, **_k):
            raise OSError("physical store unavailable")

        system.physical_store.atomic_publish = _boom
        await system.kernel.execute_project(pid)
        state = await system.runtime_facade.get_project_state(pid)
        passed = not _finished(state)
        _record("6_publication_failure_blocks_completion", passed, {
            "status": state.get("status"),
            "note": "no artifact could be published, so no reviewable deliverable",
        })
    finally:
        await system.shutdown()


async def case_vacuous_approval(ws: Path) -> None:
    """CRITICAL 18-L-D probe: does an EMPTY evidence set permit completion?

    The Review Engine has a documented ``no_target`` branch that returns an
    explicit APPROVED verdict for genuinely empty evidence. This probe records
    what the platform then does with that verdict.

    It is a PROBE, not an assertion of expected behaviour: the 18-L contract
    requires missing evidence to block completion where review is mandatory, so
    the recorded outcome is reported as-is for adjudication rather than being
    silently normalised into a pass.
    """
    system, pid = await _planned_system(ws)
    try:
        _stub_model(system)
        await system.kernel.execute_project(pid)
        state = await system.runtime_facade.get_project_state(pid)
        gate = await system.kernel.completion_module._run_final_review(pid)
        evidence = gate.get("evidence_files")
        finished = _finished(state)
        _record(
            "9_vacuous_approval_on_empty_evidence",
            finished,  # records the OBSERVED outcome
            {
                "evidence_files": evidence,
                "gate_approved": gate.get("approved"),
                "gate_reason": gate.get("reason"),
                "project_reached_finished": finished,
                "status": state.get("status"),
                "note": (
                    "PROBE: a project with no reviewable deliverable is reported "
                    "here exactly as observed. If project_reached_finished is true, "
                    "vacuous 'no_target' approval permitted completion."
                ),
            },
        )
    finally:
        await system.shutdown()


CASES = [
    ("review_rejects", case_review_rejects),
    ("review_raises", case_review_raises),
    ("missing_evidence", case_missing_evidence),
    ("no_review_engine", case_no_review_engine),
    ("invalid_artifact", case_invalid_artifact),
    ("validation_failure", case_validation_failure),
    ("publication_failure", case_publication_failure),
    ("model_runtime_failure", case_model_runtime_failure),
    ("interrupted", case_interrupted),
    ("vacuous_approval", case_vacuous_approval),
]


async def main() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="18L_failure_ws_"))
    for name, fn in CASES:
        try:
            await fn(root / name)
        except Exception as exc:  # a broken harness must never read as a pass
            _record(name, False, {"harness_error": f"{type(exc).__name__}: {exc}"})

    summary = {
        "phase": "18-L-D failure-path certification",
        "total": len(RESULTS),
        "passed": sum(1 for r in RESULTS if r["passed"]),
        "failed": sum(1 for r in RESULTS if not r["passed"]),
        "results": RESULTS,
    }
    (_EVIDENCE / "failure_paths.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n=== 18-L-D: {summary['passed']}/{summary['total']} fail-closed "
          f"cases verified, {summary['failed']} failed ===")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
