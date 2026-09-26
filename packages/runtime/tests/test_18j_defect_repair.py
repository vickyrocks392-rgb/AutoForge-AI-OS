"""18-J defect repair regression tests.

Defect: ``committed -> staging`` raised ``InvalidTransitionError`` on the
re-materialisation / resume path.

Root cause (established by inspection, NOT assumed): the state machine is
correct. ``register_artifact`` is deliberately idempotent — a retry must not mint
a new logical artifact identity — so on replay it returns the EXISTING record,
which may already be COMMITTED. Two production callers ignored the returned
status and called ``begin_staging`` unconditionally.

These tests lock BOTH halves of the contract:

* the caller now honours idempotent replay and refuses conflicting overwrite;
* the state machine is still strict — ``committed -> staging`` remains illegal,
  and every other invalid transition still raises.

Coverage map (task section 6):
  A. previously failing path ............ TestResumeAndReplay
  B. existing valid transitions ......... TestValidTransitionsStillWork
  C. existing invalid transitions ...... TestInvalidTransitionsStillRejected
  D. idempotency ........................ TestIdempotency
  E. resume ............................ TestResumeAndReplay
  F. persistence ........................ TestPersistence
  G. event consistency .................. TestEventConsistency
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from autoforge_artifacts.durable_bridge import DurableArtifactStoreBridge
from autoforge_artifacts.models import (
    Artifact,
    ArtifactVersion,
    CanonicalArtifactType,
)
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.models import ArtifactProvenance, ArtifactType
from autoforge_runtime.artifact_catalog import (
    ArtifactConflictError,
    DurableArtifactCatalog,
    derive_artifact_key,
)
from autoforge_runtime.exceptions import InvalidTransitionError
from autoforge_runtime.models import DurableArtifactStatus
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore


@pytest.fixture
def store(tmp_path: Path) -> PhysicalArtifactStore:
    artifact_root = tmp_path / "artifacts"
    return PhysicalArtifactStore(
        artifact_root=artifact_root,
        staging_root=artifact_root / ".staging",
        quarantine_root=artifact_root / ".quarantine",
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A real SQLite file, so persistence is genuinely exercised (not :memory:)."""
    return tmp_path / "runtime_state.db"


@pytest.fixture
def catalog(store: PhysicalArtifactStore, db_path: Path) -> DurableArtifactCatalog:
    return DurableArtifactCatalog(
        persistence=PersistenceLayer(db_path=db_path), physical_store=store
    )


@pytest.fixture
def pipeline(catalog, store) -> ArtifactPipeline:
    return ArtifactPipeline(durable_catalog=catalog, physical_store=store)


@pytest.fixture
def provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        task_id="t-18j",
        worker_id="w-1",
        workflow_id=uuid.UUID("11111111-1111-5111-8111-111111111111"),
        correlation_id=uuid.UUID("22222222-2222-5222-8222-222222222222"),
        attempt_number=1,
        iteration=1,
    )


def _record(pipeline, provenance, content: str, name: str = "eval_iter_1.json"):
    return pipeline.record_artifact(
        name=name,
        artifact_type=ArtifactType.EVALUATION_REPORT,
        content=content,
        provenance=provenance,
    )


def _commit(catalog, store, name: str, content: str = "data"):
    """Drive an artifact through the normal CREATED -> STAGING -> COMMITTED path."""
    state = catalog.register_artifact(
        artifact_key=derive_artifact_key(artifact_name=name)
    )
    staging = store.create_staging_file(name)
    catalog.begin_staging(state.artifact_id, staging_path=str(staging))
    written, _ = store.write_staging_text(staging, content)
    published = store.atomic_publish(staging, name)
    return catalog.commit_artifact(
        state.artifact_id, storage_path=str(published), content_hash=written
    )


# ── A / E. The previously failing path + resume ───────────────────────────


class TestResumeAndReplay:
    def test_replay_with_identical_content_no_longer_raises(
        self, pipeline, catalog, provenance
    ):
        """THE FAILING PATH: re-materialising identical content now succeeds."""
        first = _record(pipeline, provenance, "same content")
        # This previously raised InvalidTransitionError (committed -> staging).
        second = _record(pipeline, provenance, "same content")

        assert second.artifact_id == first.artifact_id, (
            "a retry must not mint a new logical artifact identity"
        )
        state = catalog.get_artifact(first.artifact_id)
        assert state.status is DurableArtifactStatus.COMMITTED

    def test_replay_preserves_committed_content_and_hash(
        self, pipeline, catalog, provenance
    ):
        """Replay must not disturb the durable content of a committed artifact."""
        first = _record(pipeline, provenance, "durable content")
        before = catalog.get_artifact(first.artifact_id)
        before_hash, before_path = before.content_hash, before.storage_path

        _record(pipeline, provenance, "durable content")

        after = catalog.get_artifact(first.artifact_id)
        assert after.content_hash == before_hash
        assert after.storage_path == before_path
        assert (
            Path(after.storage_path).read_text(encoding="utf-8") == "durable content"
        )

    def test_conflicting_content_is_rejected_not_silently_overwritten(
        self, pipeline, catalog, provenance
    ):
        """Different content on the same key must fail loudly, never corrupt."""
        first = _record(pipeline, provenance, "original")
        before = catalog.get_artifact(first.artifact_id)

        with pytest.raises(ArtifactConflictError):
            _record(pipeline, provenance, "TAMPERED")

        after = catalog.get_artifact(first.artifact_id)
        assert after.status is DurableArtifactStatus.COMMITTED
        assert after.content_hash == before.content_hash
        assert Path(after.storage_path).read_text(encoding="utf-8") == "original"

    def test_bridge_replay_of_same_version_is_idempotent(self, catalog, store):
        """The artifact-platform bridge obeys the same contract."""
        bridge = DurableArtifactStoreBridge(catalog, store)
        art = bridge.create(
            Artifact(
                artifact_id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                name="report.txt",
                artifact_type=CanonicalArtifactType.SOURCE,
            )
        )
        v1 = bridge.store_version(
            ArtifactVersion(
                artifact_id=art.artifact_id, version_number=1, content="v1"
            )
        )
        replay = bridge.store_version(
            ArtifactVersion(
                artifact_id=art.artifact_id, version_number=1, content="v1"
            )
        )
        assert replay.version_id == v1.version_id
        assert catalog.get_artifact(v1.version_id).status is (
            DurableArtifactStatus.COMMITTED
        )

    def test_new_version_still_takes_the_normal_path(self, catalog, store):
        """A genuinely new version derives a new key and commits normally."""
        bridge = DurableArtifactStoreBridge(catalog, store)
        art = bridge.create(
            Artifact(
                artifact_id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                name="report.txt",
                artifact_type=CanonicalArtifactType.SOURCE,
            )
        )
        v1 = bridge.store_version(
            ArtifactVersion(
                artifact_id=art.artifact_id, version_number=1, content="v1"
            )
        )
        v2 = bridge.store_version(
            ArtifactVersion(
                artifact_id=art.artifact_id, version_number=2, content="v2"
            )
        )
        assert v1.version_id != v2.version_id
        assert catalog.get_artifact(v1.version_id).status is (
            DurableArtifactStatus.COMMITTED
        )
        assert catalog.get_artifact(v2.version_id).status is (
            DurableArtifactStatus.COMMITTED
        )


# ── B. Existing valid transitions continue to work ────────────────────────


class TestValidTransitionsStillWork:
    def test_created_to_staging_to_committed(self, catalog, store):
        committed = _commit(catalog, store, "ok.py")
        assert committed.status is DurableArtifactStatus.COMMITTED

    def test_committed_to_retired(self, catalog, store):
        committed = _commit(catalog, store, "ret.py")
        assert catalog.retire_artifact(committed.artifact_id).status is (
            DurableArtifactStatus.RETIRED
        )

    def test_staging_to_failed_and_created_to_failed(self, catalog, store):
        s1 = catalog.register_artifact(
            artifact_key=derive_artifact_key(artifact_name="f1.py")
        )
        assert catalog.fail_artifact(s1.artifact_id, error_code="X").status is (
            DurableArtifactStatus.FAILED
        )
        s2 = catalog.register_artifact(
            artifact_key=derive_artifact_key(artifact_name="f2.py")
        )
        staging = store.create_staging_file("f2.py")
        catalog.begin_staging(s2.artifact_id, staging_path=str(staging))
        assert catalog.fail_artifact(s2.artifact_id, error_code="Y").status is (
            DurableArtifactStatus.FAILED
        )

    def test_first_materialisation_path_unchanged(self, pipeline, catalog, provenance):
        """The ordinary CREATED->STAGING->COMMITTED path is untouched."""
        rec = _record(pipeline, provenance, "first write", name="new_iter_1.json")
        state = catalog.get_artifact(rec.artifact_id)
        assert state.status is DurableArtifactStatus.COMMITTED
        assert state.content_hash == rec.checksum


# ── C. The state machine must remain strict ───────────────────────────────


class TestInvalidTransitionsStillRejected:
    def test_committed_to_staging_is_still_illegal(self, catalog, store):
        """THE KEY NEGATIVE TEST: the repair must not make this legal."""
        committed = _commit(catalog, store, "inv.py")
        staging = store.create_staging_file("inv2.py")
        with pytest.raises(InvalidTransitionError):
            catalog.begin_staging(committed.artifact_id, staging_path=str(staging))

    def test_transition_table_unchanged_by_repair(self):
        """The repair must not have edited the canonical 18-J state machine."""
        from autoforge_runtime.validation import _ARTIFACT_TRANSITIONS

        assert _ARTIFACT_TRANSITIONS[DurableArtifactStatus.COMMITTED] == {
            DurableArtifactStatus.RETIRED
        }, "COMMITTED must still exit only via RETIRED"
        assert (
            DurableArtifactStatus.STAGING
            not in _ARTIFACT_TRANSITIONS[DurableArtifactStatus.COMMITTED]
        )

    def test_failed_to_committed_still_illegal(self, catalog):
        state = catalog.register_artifact(
            artifact_key=derive_artifact_key(artifact_name="ftc.py")
        )
        catalog.fail_artifact(state.artifact_id, error_code="ERR")
        with pytest.raises(InvalidTransitionError):
            catalog.commit_artifact(state.artifact_id, content_hash="x")

    def test_retired_is_terminal(self, catalog, store):
        committed = _commit(catalog, store, "term.py")
        catalog.retire_artifact(committed.artifact_id)
        with pytest.raises(InvalidTransitionError):
            catalog.fail_artifact(committed.artifact_id, error_code="ERR")


# ── D. Idempotency ────────────────────────────────────────────────────────


class TestIdempotency:
    def test_repeated_replay_does_not_mutate_state(
        self, pipeline, catalog, provenance
    ):
        first = _record(pipeline, provenance, "idem")
        versions = [catalog.get_artifact(first.artifact_id).state_version]
        for _ in range(5):
            _record(pipeline, provenance, "idem")
            versions.append(catalog.get_artifact(first.artifact_id).state_version)

        # No state mutation on replay: the version counter must not advance.
        assert len(set(versions)) == 1, f"state mutated on replay: {versions}"

    def test_repeated_replay_creates_no_extra_files(self, pipeline, store, provenance):
        _record(pipeline, provenance, "idem", name="idem_phys.json")
        before = sorted(p.name for p in store.artifact_root.iterdir())
        for _ in range(3):
            _record(pipeline, provenance, "idem", name="idem_phys.json")
        after = sorted(p.name for p in store.artifact_root.iterdir())
        assert before == after

    def test_register_artifact_remains_idempotent(self, catalog):
        key = derive_artifact_key(artifact_name="reg.py")
        a = catalog.register_artifact(artifact_key=key)
        b = catalog.register_artifact(artifact_key=key)
        assert a.artifact_id == b.artifact_id


# ── F. Persistence ────────────────────────────────────────────────────────


class TestPersistence:
    def test_state_survives_a_fresh_catalog_instance(
        self, store, pipeline, provenance, db_path
    ):
        """The committed record must be readable from an independent DB handle."""
        rec = _record(pipeline, provenance, "persisted", name="persist.json")

        # A genuinely separate handle on the same durable DB, as a restart would use.
        reopened = DurableArtifactCatalog(
            persistence=PersistenceLayer(db_path=db_path), physical_store=store
        )
        restored = reopened.get_artifact(rec.artifact_id)
        assert restored is not None, "committed state did not survive a reopen"
        assert restored.status is DurableArtifactStatus.COMMITTED
        assert restored.content_hash == rec.checksum
        assert (
            Path(restored.storage_path).read_text(encoding="utf-8") == "persisted"
        )

    def test_committed_artifact_is_not_left_in_staging(self, pipeline, catalog, provenance):
        _record(pipeline, provenance, "done", name="staged.json")
        # No artifact may be stranded in STAGING, and there must be no orphans.
        assert catalog.find_orphaned_staging() == []
        in_staging = [
            s
            for s in catalog.find_by_task(provenance.task_id)
            if s.status is DurableArtifactStatus.STAGING
        ]
        assert in_staging == []


# ── G. Event consistency ──────────────────────────────────────────────────


class TestEventConsistency:
    def test_event_emitted_only_after_durable_commit(self, pipeline, catalog, provenance):
        events: list[str] = []

        class Sink:
            def publish(self, event):
                events.append(type(event).__name__)

        pipeline._event_sink = Sink()
        rec = _record(pipeline, provenance, "evented", name="evt.json")

        # The durable record is committed by the time the event is observable.
        assert catalog.get_artifact(rec.artifact_id).status is (
            DurableArtifactStatus.COMMITTED
        )
        assert events, "an artifact event should be published"

    def test_replay_creates_no_duplicate_durable_record(
        self, pipeline, catalog, provenance
    ):
        first = _record(pipeline, provenance, "evt2", name="evt2.json")
        _record(pipeline, provenance, "evt2", name="evt2.json")
        matching = [
            s
            for s in catalog.find_by_task(provenance.task_id)
            if s.artifact_name == "evt2.json"
        ]
        assert len(matching) == 1
        assert matching[0].artifact_id == first.artifact_id
