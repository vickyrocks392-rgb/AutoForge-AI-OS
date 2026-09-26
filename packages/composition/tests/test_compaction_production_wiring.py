"""
18-L C-1: production composition-root wiring for Context Compaction storage.

Gate 4 proved the storage round-trip inside an isolated harness. C-1 closes the
remaining gap by proving the **production composition root owns the store and
the actual Context Compaction path consumes that same dependency**.

These tests deliberately build the system through ``build_autoforge_system`` and
drive ``system.context_builder.assemble_context``. They never construct a
``CompactionRecordStore`` themselves — a store built by hand would prove nothing
about production wiring.

Context Compaction remains **OFF by default**; these tests opt in explicitly via
``config={"enable_context_compaction": True}``.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.compaction import CompactionRecordStore
from autoforge_execution.models import (
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_workflows.models import TaskDefinition

#: Enough iterations to cross the Gate 3 retention window and force compaction.
ITERATIONS = 8


def _task(task_id: str | None = None) -> TaskDefinition:
    # TaskDefinition is frozen, so identity must be set at construction.
    return TaskDefinition(
        task_id=task_id or f"c1-{uuid.uuid4().hex[:8]}",
        name="C-1 production wiring probe",
        task_type="coding",
        description="Exercise the production compaction store wiring.",
        input_data={},
    )


def _history(n: int = ITERATIONS) -> list[LoopIterationRecord]:
    return [
        LoopIterationRecord(
            iteration=i,
            action_plan=f"iteration {i}: investigate the connection pool timeout",
            changed_files=[f"src/pool_{i}.py"],
            passed=False,
            evaluation=EvaluationResult(
                status=EvaluationStatus.FAILED,
                failures=[f"test_pool_timeout::FAILED at iteration {i}"],
            ),
        )
        for i in range(1, n + 1)
    ]


def _build(tmp_path: Path, *, enable_compaction: bool = True):
    config = {"enable_context_compaction": enable_compaction}
    return build_autoforge_system(
        workspace_root=str(tmp_path), config=config
    )


def _artifact_file(system, compaction_id: str) -> Path:
    name = f"compaction_{compaction_id}"
    matches = [p for p in system.physical_store.artifact_root.rglob(name) if p.is_file()]
    assert matches, f"no persisted artifact found for {name}"
    return matches[0]


# ── C-1: the production root owns the store ────────────────────────────────


def test_production_root_owns_a_real_compaction_store(tmp_path: Path):
    """C-1 acceptance: the composition root itself owns the store."""
    system = _build(tmp_path)
    assert isinstance(system.compaction_store, CompactionRecordStore)


def test_context_builder_consumes_the_root_owned_store(tmp_path: Path):
    """The compaction path must use the root's object, not a private copy."""
    system = _build(tmp_path)
    assert system.context_builder.compaction_store is system.compaction_store


def test_store_is_built_over_the_canonical_artifact_substrate(tmp_path: Path):
    """No second storage architecture: the same catalog/store the system uses."""
    system = _build(tmp_path)
    assert system.compaction_store._catalog is system.durable_catalog
    assert system.compaction_store._physical_store is system.physical_store


def test_compaction_is_off_by_default(tmp_path: Path):
    """Wiring the store must not enable the capability."""
    system = _build(tmp_path, enable_compaction=False)
    assert system.context_builder.compactor is None
    # The store is still owned — that is what C-1 required.
    assert isinstance(system.compaction_store, CompactionRecordStore)


def test_default_build_injects_an_enabled_compactor(tmp_path: Path):
    """18-L global enablement: compaction is now the production default.

    Updated from the pre-enable assertion. The test's *intent* is unchanged —
    the production posture is explicit and single-sourced at the composition root
    — only the certified value changed.
    """
    system = build_autoforge_system(workspace_root=str(tmp_path))
    assert system.context_builder.compactor is not None
    assert system.context_builder.compactor.enabled is True
    # Context Engineering stays ON alongside it.
    assert system.context_builder.enable_context_engineering is True
    # And the store is still owned, so the enabled path persists through it.
    assert system.context_builder.compaction_store is system.compaction_store


def test_rollback_leaver_disables_compaction_without_touching_ce(tmp_path: Path):
    """`config={'enable_context_compaction': False}` is a supported rollback."""
    system = build_autoforge_system(
        workspace_root=str(tmp_path),
        config={"enable_context_compaction": False},
    )
    assert system.context_builder.compactor is None
    assert system.context_builder.enable_context_engineering is True


# ── §5: production persistence + restart/recovery ─────────────────────────


async def _produce_context(system, task, tmp_path: Path):
    """Drive the production builder and return the assembled ExecutionContext."""
    history = _history()
    return await system.context_builder.assemble_context(
        task_def=task,
        workspace_root=tmp_path,
        prior_iterations=history,
        last_evaluation=history[-1].evaluation,
        context_window_tokens=32768,
    )


async def _produce(system, task, tmp_path: Path):
    """Drive the production builder and return the compaction record."""
    await _produce_context(system, task, tmp_path)
    return system.context_builder.last_compaction_record


@pytest.mark.asyncio
async def test_production_path_persists_a_compaction_record(tmp_path: Path):
    """The full production chain: root -> builder -> compaction -> persist."""
    system = _build(tmp_path)
    task = _task()

    record = await _produce(system, task, tmp_path)

    assert record is not None, "compaction did not run through production wiring"
    assert system.context_builder.last_compaction_artifact_id, "not persisted"

    # Present on disk under the canonical artifact name.
    artifact = _artifact_file(system, record.compaction_id)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["compaction_id"] == record.compaction_id


@pytest.mark.asyncio
async def test_restart_reconstruction_recovers_the_record(tmp_path: Path):
    """Persist -> process restart -> reconstruct root -> load -> validate."""
    first = _build(tmp_path)
    record = await _produce(first, _task(), tmp_path)
    assert record is not None
    original_digest = record.content_digest()

    # A brand-new composition root over the same on-disk state == restart.
    second = _build(tmp_path)
    reloaded = second.compaction_store.load(record.compaction_id)

    assert reloaded is not None, "record did not survive a restart"
    assert reloaded.compaction_id == record.compaction_id
    assert reloaded.content_digest() == original_digest
    assert reloaded.validation_status in {"valid", "partial_unresolvable"}


# ── §6: negative tests, all through production wiring ─────────────────────


@pytest.mark.asyncio
async def test_corrupted_bytes_are_never_authoritative(tmp_path: Path):
    """Corrupt the persisted artifact; load must refuse it (no silent substitution)."""
    system = _build(tmp_path)
    record = await _produce(system, _task(), tmp_path)
    artifact = _artifact_file(system, record.compaction_id)

    raw = artifact.read_text(encoding="utf-8")
    artifact.write_text(raw.replace("iteration", "TAMPERED", 1), encoding="utf-8")

    restarted = _build(tmp_path)
    assert restarted.compaction_store.load(record.compaction_id) is None


@pytest.mark.asyncio
async def test_missing_record_returns_none(tmp_path: Path):
    """Absent record -> explicit miss, never a substituted one."""
    system = _build(tmp_path)
    assert system.compaction_store.load("cmp_does_not_exist") is None


@pytest.mark.asyncio
async def test_truncated_record_is_refused(tmp_path: Path):
    system = _build(tmp_path)
    record = await _produce(system, _task(), tmp_path)
    artifact = _artifact_file(system, record.compaction_id)
    artifact.write_text(artifact.read_text(encoding="utf-8")[:200], encoding="utf-8")

    restarted = _build(tmp_path)
    assert restarted.compaction_store.load(record.compaction_id) is None


@pytest.mark.asyncio
async def test_resaving_the_same_record_is_idempotent(tmp_path: Path):
    """The real 18-J contract, exercised through production wiring.

    Re-saving the SAME record must reuse the committed artifact rather than
    creating a duplicate. (Note: running `assemble_context` twice is *not* an
    idempotency probe — the first persist places an artifact inside the scanned
    workspace, so the candidate pool genuinely differs on the second call and a
    different, equally valid, id is derived. That determinism is asserted
    separately below.)
    """
    from autoforge_runtime.models import DurableArtifactStatus

    system = _build(tmp_path)
    record = await _produce(system, _task(), tmp_path)
    assert record is not None

    first_id = system.compaction_store.save(record)
    second_id = system.compaction_store.save(record)
    assert first_id == second_id

    committed = [
        s
        for s in system.durable_catalog.find_by_status(DurableArtifactStatus.COMMITTED)
        if str(getattr(s, "artifact_name", "")).startswith("compaction_")
    ]
    assert len(committed) == 1, f"expected one artifact, found {len(committed)}"


@pytest.mark.asyncio
async def test_compaction_content_is_stable_across_production_runs(
    tmp_path: Path,
):
    """The projected CONTENT is deterministic even as workspace state drifts.

    The store persists into the scanned workspace, so each run observes one more
    artifact file and therefore derives a different (equally valid) identity. The
    compaction projection itself must still be stable — that is the property that
    matters for semantic continuity.

    The FIRST run is excluded from the comparison because it runs against an
    empty workspace and therefore has no workspace-listing candidate at all; runs
    two onward share a settled workspace and are directly comparable.
    """
    task = _task()
    system = _build(tmp_path)

    await _produce(system, task, tmp_path)          # run 1: empty workspace
    second = await _produce(system, task, tmp_path)  # run 2: workspace settled
    third = await _produce(system, task, tmp_path)   # run 3: comparable

    assert second is not None and third is not None

    # The compaction projection proper — the structured `iter-N` items — is
    # byte-identical across runs. (Before 18-L C-3 the workspace-listing
    # candidate also drifted, because each run's persisted artifact was
    # rediscovered by the scan; C-3 removes that cause.)
    def _iteration_items(record):
        return sorted(
            i.content for i in record.items if i.source.kind == "iteration"
        )

    assert _iteration_items(second) == _iteration_items(third)
    assert _iteration_items(second), "no iteration items were compacted at all"
    assert second.item_count == third.item_count
    assert second.reduction_ratio == third.reduction_ratio
    # Workspace-listing stability across production runs is asserted directly in
    # test_c3_workspace_boundary.py, against the ExecutionContext candidate (the
    # compaction record itself carries only the projected iteration items).


@pytest.mark.asyncio
async def test_persisting_does_not_inflate_the_compacted_context(
    tmp_path: Path,
):
    """Repeated production compaction must NOT accumulate durable records.

    Updated by 18-L C-3. Before C-3, each run's persisted artifact was rediscovered
    by the Context Engineering workspace scan, which changed the candidate pool,
    changed the fingerprint, and produced a NEW compaction id — so every iteration
    wrote another file. This test previously pinned that buggy growth as "known
    behaviour"; C-3 removes the cause, so it now pins the corrected invariant.
    """
    task = _task()
    system = _build(tmp_path)

    def _records() -> list:
        return [p for p in (tmp_path / "artifacts").glob("compaction_cmp_*")
                if p.is_file()]

    first = await _produce(system, task, tmp_path)
    first_files = len(_records())
    first_id = first.compaction_id

    for _ in range(4):
        await _produce(system, task, tmp_path)
    final_files = len(_records())
    last = system.context_builder.last_compaction_record

    # A record was really written, so the guard is meaningful.
    assert first_files >= 1
    # C-3: the identity is stable, so retries map to the same artifact and the
    # durable record count does not grow.
    assert last.compaction_id == first_id
    assert final_files == first_files, (
        f"compaction bookkeeping accumulated: {first_files} -> {final_files}"
    )
    # And the compacted record does not grow with the artifact count.
    assert last.item_count == first.item_count


@pytest.mark.asyncio
async def test_different_tasks_do_not_collide(tmp_path: Path):
    """C-1 cross-task isolation: distinct tasks => distinct durable records."""
    system = _build(tmp_path)
    seen = {}

    for label in ("alpha", "beta"):
        task = _task(task_id=f"c1-collision-{label}")
        record = await _produce(system, task, tmp_path)
        assert record is not None
        seen[label] = (
            record.compaction_id,
            record.request_fingerprint,
            system.context_builder.last_compaction_artifact_id,
        )

    alpha, beta = seen["alpha"], seen["beta"]
    assert alpha[0] != beta[0], "compaction ids collided across tasks"
    assert alpha[1] != beta[1], "fingerprints collided across tasks"
    assert alpha[2] != beta[2], "durable artifacts collided across tasks"

    # Both remain independently loadable.
    for cid, _fp, _aid in seen.values():
        assert system.compaction_store.load(cid) is not None


@pytest.mark.asyncio
async def test_persistence_failure_does_not_fail_engineering(tmp_path: Path):
    """A store that always raises must not break context assembly."""

    class ExplodingStore:
        def save(self, record):  # noqa: ANN001, ANN201
            raise RuntimeError("durable store unavailable")

    system = _build(tmp_path)
    system.context_builder.compaction_store = ExplodingStore()

    context = await _produce_context(system, _task(), tmp_path)
    assert context is not None
    assert system.context_builder.last_compaction_record is not None
    assert system.context_builder.last_compaction_artifact_id is None


@pytest.mark.asyncio
async def test_context_engineering_stays_on_while_compaction_is_wired(
    tmp_path: Path,
):
    """Wiring compaction must not disturb the Context Engineering posture."""
    system = _build(tmp_path)
    assert system.context_builder.enable_context_engineering is True
    assert system.context_builder.compactor is not None  # opt-in in this test
