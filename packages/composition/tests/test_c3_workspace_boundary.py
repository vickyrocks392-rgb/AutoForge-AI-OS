"""
18-L C-3: Context Engineering workspace-boundary isolation.

The invariant under test:

    Context Compaction persistence must not feed its own durable bookkeeping
    artifacts back into the canonical Context Engineering candidate-discovery
    path — while ordinary engineering artifacts stay fully discoverable.

Every test drives the REAL production composition root
(``build_autoforge_system``) and the REAL globally-enabled Context Engineering
path. Context Compaction stays OFF by default and is opted into explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.compaction.storage import (
    COMPACTION_ARTIFACT_PREFIX,
    is_compaction_bookkeeping_artifact,
)
from autoforge_execution.models import (
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_workflows.models import TaskDefinition

# ── Ordinary engineering artifacts that MUST remain discoverable ────────────
ORDINARY_ARTIFACTS = {
    "src/service.py": "X = 1\n",                       # source file
    "README.md": "# Project\n",                          # documentation artifact
    "tests/evidence.json": '{"result": "pass"}\n',       # test/evidence artifact
    "artifacts/build_report.json": '{"built": true}\n',  # normal durable artifact
}


def _seed_workspace(ws: Path) -> None:
    for rel, content in ORDINARY_ARTIFACTS.items():
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _task(tid: str = "c3-task") -> TaskDefinition:
    return TaskDefinition(
        task_id=tid, name="C-3 probe", task_type="coding",
        description="Workspace boundary probe.", input_data={},
    )


def _history(n: int = 8) -> list[LoopIterationRecord]:
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


def _build(ws: Path, *, enable_compaction: bool = True):
    return build_autoforge_system(
        workspace_root=str(ws),
        config={"enable_context_compaction": enable_compaction},
    )


async def _assemble(system, ws: Path, task_id: str = "c3-task"):
    history = _history()
    return await system.context_builder.assemble_context(
        task_def=_task(task_id),
        workspace_root=ws,
        prior_iterations=history,
        last_evaluation=history[-1].evaluation,
        context_window_tokens=32768,
    )


def _workspace_item(ctx):
    for item in getattr(ctx, "selected_context_items", []) or []:
        if item.source.kind == "workspace":
            return item
    return None


async def _produce_context(system, ws: Path, task=None):
    """Drive the production builder; returns the assembled ExecutionContext."""
    history = _history()
    return await system.context_builder.assemble_context(
        task_def=task or _task(),
        workspace_root=ws,
        prior_iterations=history,
        last_evaluation=history[-1].evaluation,
        context_window_tokens=32768,
    )


async def _produce(system, task, ws: Path):
    """Drive the production builder; returns the compaction record."""
    await _produce_context(system, ws, task)
    return system.context_builder.last_compaction_record


# ── §5 the predicate is narrow and exact ───────────────────────────────────


def test_predicate_matches_only_compaction_records():
    assert is_compaction_bookkeeping_artifact("compaction_cmp_abc123")
    assert not is_compaction_bookkeeping_artifact("compaction_policy.py")
    assert not is_compaction_bookkeeping_artifact("build_report.json")
    assert not is_compaction_bookkeeping_artifact("service.py")
    assert not is_compaction_bookkeeping_artifact("compaction_cmp")


def test_predicate_matches_the_real_store_artifact_name():
    """The predicate must agree with what CompactionRecordStore actually writes."""
    from autoforge_execution.compaction import (
        CompactionPolicy,
        CompactionRecordStore,
        ContextCompactor,
    )

    record = ContextCompactor(CompactionPolicy(enabled=True)).compact(
        task_id="t", prior_iterations=_history()
    )
    name = CompactionRecordStore.artifact_name(record)
    assert name.startswith(COMPACTION_ARTIFACT_PREFIX)
    assert is_compaction_bookkeeping_artifact(name)


# ── §8 ordinary engineering artifacts remain discoverable ─────────────────


@pytest.mark.asyncio
async def test_ordinary_artifacts_are_discoverable_without_compaction(
    tmp_path: Path,
):
    """Source, documentation, test/evidence, and a normal durable artifact."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path, enable_compaction=False)
    ctx = await _assemble(system, tmp_path)

    for rel in ORDINARY_ARTIFACTS:
        assert rel in ctx.project_files, f"{rel} became invisible"


@pytest.mark.asyncio
async def test_normal_artifact_inside_artifacts_dir_stays_discoverable(
    tmp_path: Path,
):
    """C-3 must not exclude the artifacts DIRECTORY.

    The compaction store writes into `<workspace>/artifacts`, and so do normal
    durable engineering artifacts. Only compaction bookkeeping files may be
    filtered.
    """
    _seed_workspace(tmp_path)
    system = _build(tmp_path)
    ctx = await _assemble(system, tmp_path)

    assert "artifacts/build_report.json" in ctx.project_files
    assert any(p.startswith("artifacts/") for p in ctx.project_files)
    assert not any("compaction_cmp_" in p for p in ctx.project_files)


# ── §9 compaction artifact exclusion (real production artifact) ───────────


@pytest.mark.asyncio
async def test_real_compaction_artifact_is_excluded_from_candidates(
    tmp_path: Path,
):
    """A genuine production CompactionRecordStore artifact, then re-scanned."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path)

    ctx = await _assemble(system, tmp_path)
    record = system.context_builder.last_compaction_record
    assert record is not None, "compaction did not run"
    assert system.context_builder.last_compaction_artifact_id, "not persisted"

    name = f"compaction_{record.compaction_id}"
    artifact = next(p for p in tmp_path.rglob(name) if p.is_file())
    assert artifact.exists()

    # A fresh root re-scans the workspace: the artifact must be invisible.
    restarted = _build(tmp_path)
    ctx2 = await _assemble(restarted, tmp_path)
    assert name not in ctx2.project_files
    assert not any("compaction_cmp_" in p for p in ctx2.project_files)


@pytest.mark.asyncio
async def test_compaction_artifact_remains_fully_available_for_recovery(
    tmp_path: Path,
):
    """Excluding it from CE candidates must NOT impair compaction recovery."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path)
    await _assemble(system, tmp_path)
    record = system.context_builder.last_compaction_record

    restarted = _build(tmp_path)
    reloaded = restarted.compaction_store.load(record.compaction_id)

    assert reloaded is not None, "record unavailable after C-3"
    assert reloaded.compaction_id == record.compaction_id
    assert reloaded.content_digest() == record.content_digest()
    assert reloaded.validation_status in {"valid", "partial_unresolvable"}


# ── §10 / §11 fingerprint stability and repeatability ─────────────────────


@pytest.mark.asyncio
async def test_candidate_set_and_fingerprint_are_stable_across_cycles(
    tmp_path: Path,
):
    """Persist repeatedly; the CE candidate inputs must not move."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path)

    snapshots = []
    for _ in range(4):
        ctx = await _assemble(system, tmp_path)
        rec = system.context_builder.last_compaction_record
        item = _workspace_item(ctx)
        snapshots.append({
            "project_files": sorted(ctx.project_files),
            "workspace_context_id": item.context_id if item else None,
            "candidate_ids": sorted(i.context_id for i in ctx.selected_context_items),
            "compaction_id": rec.compaction_id,
            "fingerprint": rec.request_fingerprint,
            "items": rec.item_count,
        })

    first = snapshots[0]
    for n, snap in enumerate(snapshots[1:], start=2):
        assert snap["project_files"] == first["project_files"], f"cycle {n}"
        assert snap["workspace_context_id"] == first["workspace_context_id"], f"cycle {n}"
        assert snap["candidate_ids"] == first["candidate_ids"], f"cycle {n}"
        assert snap["fingerprint"] == first["fingerprint"], f"cycle {n}"
        assert snap["compaction_id"] == first["compaction_id"], f"cycle {n}"


@pytest.mark.asyncio
async def test_no_candidate_accumulation_from_compaction_bookkeeping(
    tmp_path: Path,
):
    """Persisting many records must not grow the CE candidate set."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path)

    baseline = len((await _assemble(system, tmp_path)).project_files)
    for _ in range(5):
        await _assemble(system, tmp_path)
    final = len((await _assemble(system, tmp_path)).project_files)

    # Records were actually written, so the guard is meaningful.
    written = len(list((tmp_path / "artifacts").glob("compaction_cmp_*")))
    assert written >= 1, "no compaction record was persisted to observe"
    assert final == baseline


# ── §12 negative control (mandatory) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_negative_control_normal_included_compaction_excluded(
    tmp_path: Path,
):
    """Both present: the ordinary artifact MUST be included."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path)

    ctx = await _assemble(system, tmp_path)
    record = system.context_builder.last_compaction_record
    compaction_path = f"artifacts/compaction_{record.compaction_id}"
    normal_path = "artifacts/build_report.json"

    artifact = next(
        p for p in tmp_path.rglob(f"compaction_{record.compaction_id}")
        if p.is_file()
    )
    assert artifact.exists(), "compaction artifact not on disk"
    assert (tmp_path / normal_path).exists(), "normal artifact not on disk"

    files = ctx.project_files
    assert normal_path in files, "NEGATIVE CONTROL FAILED: normal artifact excluded"
    assert compaction_path not in files, "compaction artifact leaked into candidates"


@pytest.mark.asyncio
async def test_exclusion_is_not_a_blanket_artifact_blackout(tmp_path: Path):
    """Guards against a future 'disable artifact discovery' regression."""
    for i in range(5):
        path = tmp_path / "artifacts" / f"module_{i}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"module": true}\n', encoding="utf-8")

    system = _build(tmp_path, enable_compaction=False)
    ctx = await _assemble(system, tmp_path)

    discovered = [p for p in ctx.project_files if p.startswith("artifacts/")]
    assert len(discovered) == 5


# ── §13 provenance is untouched for legitimate candidates ─────────────────


@pytest.mark.asyncio
async def test_legitimate_candidate_provenance_is_unchanged(tmp_path: Path):
    """C-3 changes eligibility, not the meaning of legitimate candidates."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path)
    ctx = await _assemble(system, tmp_path)

    item = _workspace_item(ctx)
    assert item is not None
    assert item.source.kind == "workspace"
    assert item.source.ref == str(tmp_path)
    assert item.category.value == "project"
    assert item.provenance is not None
    assert item.provenance.acquired_from == "workspace_filesystem"
    assert item.provenance.provider == "workspace"
    assert item.provenance.inferred is False
    assert item.context_id.startswith("ctx_")
    assert item.relevance == 0.5
    for rel in ORDINARY_ARTIFACTS:
        assert rel in item.content


# ── §19 / §20 global posture must be preserved ───────────────────────────


@pytest.mark.asyncio
async def test_context_engineering_on_and_compaction_off_by_default(
    tmp_path: Path,
):
    system = _build(tmp_path, enable_compaction=False)
    assert system.context_builder.enable_context_engineering is True
    assert system.context_builder.compactor is None


@pytest.mark.asyncio
async def test_workspace_candidate_present_when_compaction_disabled(
    tmp_path: Path,
):
    """The globally enabled CE path still produces workspace candidates."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path, enable_compaction=False)
    ctx = await _assemble(system, tmp_path)
    assert _workspace_item(ctx) is not None


# ── 18-L P1: persistence determinism through the PRODUCTION wiring ────────


@pytest.mark.asyncio
async def test_p1_repeated_production_compaction_does_not_conflict(
    tmp_path: Path,
):
    """The P1 symptom, driven end-to-end through build_autoforge_system().

    Before the repair this logged an ArtifactConflictError on every cycle after
    the first, because runtime-only fields (duration_ms, acquired_at) made the
    persisted bytes differ on every identical replay.
    """
    _seed_workspace(tmp_path)
    system = _build(tmp_path)

    ids = []
    for cycle in range(5):
        await _produce(system, _task(), tmp_path)
        rec = system.context_builder.last_compaction_record
        assert rec is not None
        # Before the repair the builder contained the conflict and left the
        # artifact id unset; after it, the replay is recognised every time.
        assert system.context_builder.last_compaction_artifact_id, (
            f"replay was not recognised on cycle {cycle + 1}"
        )
        ids.append(system.context_builder.last_compaction_artifact_id)

    assert len(set(ids)) == 1, "identical compaction produced multiple artifacts"


@pytest.mark.asyncio
async def test_p1_production_record_survives_restart_with_same_identity(
    tmp_path: Path,
):
    _seed_workspace(tmp_path)
    system = _build(tmp_path)
    await _produce(system, _task(), tmp_path)
    record = system.context_builder.last_compaction_record

    restarted = _build(tmp_path)
    reloaded = restarted.compaction_store.load(record.compaction_id)

    assert reloaded is not None
    assert reloaded.logical_identity() == record.logical_identity()
    assert reloaded.content_digest() == record.content_digest()


@pytest.mark.asyncio
async def test_p1_production_path_uses_the_root_owned_store(tmp_path: Path):
    """Object identity, preserved from C-1: no private store, no bypass."""
    system = _build(tmp_path)
    assert system.context_builder.compaction_store is system.compaction_store
    assert system.compaction_store._catalog is system.durable_catalog  # noqa: SLF001
    assert system.compaction_store._physical_store is system.physical_store  # noqa: SLF001


@pytest.mark.asyncio
async def test_p1_c3_boundary_still_holds_after_repair(tmp_path: Path):
    """C-3 must not regress: bookkeeping stays out of the candidate set."""
    _seed_workspace(tmp_path)
    system = _build(tmp_path)

    counts = []
    for _ in range(4):
        ctx = await _produce_context(system, tmp_path)
        counts.append(len(ctx.project_files))
        assert not any("compaction_cmp_" in p for p in ctx.project_files)

    assert len(set(counts)) == 1, f"candidate count drifted across cycles: {counts}"

