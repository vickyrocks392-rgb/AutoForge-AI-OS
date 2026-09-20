"""Cross-Process Concurrency Tests for Phase 18-K Durable Artifact Catalog.

Verifies:
- Two processes register same logical artifact key -> Single logical identity
- Two processes stage same artifact -> Exactly one succeeds, second gets conflict
- Two processes attempt conflicting commit -> Exactly one succeeds, second gets conflict
- Stale OCC commit across processes
- Concurrent repeated reconciliation across supervisor processes
- Concurrent distinct artifacts across worker processes
- Concurrent queries during writes without corruption
"""

from __future__ import annotations

import multiprocessing as mp
import os
import uuid
import hashlib
from pathlib import Path
import pytest

from autoforge_runtime.persistence import PersistenceLayer, SQLiteStorage
from autoforge_runtime.models import EntityType
from autoforge_runtime.exceptions import VersionConflictError, InvalidTransitionError
from autoforge_runtime.artifact_catalog import (
    DurableArtifactCatalog,
    derive_artifact_key,
    DurableArtifactStatus,
)
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore


# Helper worker functions for multiprocessing
def _worker_register(db_path: str, art_key: str, queue: mp.Queue) -> None:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    persistence = PersistenceLayer(storage=storage)
    cat = DurableArtifactCatalog(persistence=persistence, owner_id=f"worker:{os.getpid()}")
    try:
        state = cat.register_artifact(artifact_key=art_key)
        queue.put(("SUCCESS", str(state.artifact_id), state.state_version))
    except Exception as e:
        queue.put(("ERROR", type(e).__name__, str(e)))
    finally:
        storage.close()


def _worker_stage(
    db_path: str,
    art_id_str: str,
    staging_file: str,
    expected_version: int,
    queue: mp.Queue,
) -> None:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    persistence = PersistenceLayer(storage=storage)
    cat = DurableArtifactCatalog(persistence=persistence, owner_id=f"worker:{os.getpid()}")
    try:
        state = cat.begin_staging(
            uuid.UUID(art_id_str),
            staging_path=staging_file,
            expected_version=expected_version,
        )
        queue.put(("SUCCESS", str(state.artifact_id), state.state_version))
    except Exception as e:
        queue.put(("ERROR", type(e).__name__, str(e)))
    finally:
        storage.close()


def _worker_commit(
    db_path: str,
    art_id_str: str,
    file_path: str,
    expected_version: int,
    queue: mp.Queue,
) -> None:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    persistence = PersistenceLayer(storage=storage)
    cat = DurableArtifactCatalog(persistence=persistence, owner_id=f"worker:{os.getpid()}")
    try:
        state = cat.commit_artifact(
            uuid.UUID(art_id_str),
            storage_path=file_path,
            expected_version=expected_version,
        )
        queue.put(("SUCCESS", str(state.artifact_id), state.state_version))
    except Exception as e:
        queue.put(("ERROR", type(e).__name__, str(e)))
    finally:
        storage.close()


def _worker_create_and_commit(
    db_path: str,
    art_root: str,
    staging_root: str,
    name: str,
    queue: mp.Queue,
) -> None:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    persistence = PersistenceLayer(storage=storage)
    p_store = PhysicalArtifactStore(artifact_root=art_root, staging_root=staging_root)
    cat = DurableArtifactCatalog(
        persistence=persistence,
        owner_id=f"worker:{os.getpid()}",
        physical_store=p_store,
    )
    try:
        key = derive_artifact_key(artifact_name=name)
        state = cat.register_artifact(artifact_key=key, artifact_name=name)
        staged_file = Path(staging_root) / f"{name}.tmp"
        content = f"content of {name}".encode("utf-8")
        p_store.write_staging_bytes(staged_file, content)
        cat.begin_staging(state.artifact_id, staging_path=str(staged_file))
        committed = cat.commit_artifact(state.artifact_id, storage_path=str(staged_file))
        queue.put(("SUCCESS", str(committed.artifact_id), name))
    except Exception as e:
        queue.put(("ERROR", type(e).__name__, str(e)))
    finally:
        storage.close()


def _worker_reconcile(db_path: str, queue: mp.Queue) -> None:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    persistence = PersistenceLayer(storage=storage)
    cat = DurableArtifactCatalog(persistence=persistence, owner_id=f"supervisor:{os.getpid()}")
    try:
        res = cat.reconcile_on_startup(assume_all_dead=True)
        queue.put(("SUCCESS", res.recovered_count, res.failed_count))
    except Exception as e:
        queue.put(("ERROR", type(e).__name__, str(e)))
    finally:
        storage.close()


def _worker_query(db_path: str, workflow_id_str: str, queue: mp.Queue) -> None:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    persistence = PersistenceLayer(storage=storage)
    cat = DurableArtifactCatalog(persistence=persistence, owner_id=f"reader:{os.getpid()}")
    try:
        found = cat.find_by_workflow(uuid.UUID(workflow_id_str))
        queue.put(("SUCCESS", len(found)))
    except Exception as e:
        queue.put(("ERROR", type(e).__name__, str(e)))
    finally:
        storage.close()


@pytest.fixture
def multiprocess_env(tmp_path: Path):
    db_path = str(tmp_path / "concurrent.db")
    art_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    art_root.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)

    # Pre-initialize schema in WAL mode
    st = SQLiteStorage(db_path)
    st.initialize()
    st.close()

    return {
        "db_path": db_path,
        "art_root": str(art_root),
        "staging_root": str(staging_root),
    }


class TestCrossProcessConcurrency:
    """Multiprocessing concurrency tests on file-backed SQLite with WAL."""

    def test_concurrent_registration_same_logical_key(self, multiprocess_env: dict) -> None:
        art_key = derive_artifact_key(artifact_name="shared.py", workflow_id=uuid.uuid4())
        ctx = mp.get_context("spawn")
        q = ctx.Queue()

        p1 = ctx.Process(target=_worker_register, args=(multiprocess_env["db_path"], art_key, q))
        p2 = ctx.Process(target=_worker_register, args=(multiprocess_env["db_path"], art_key, q))

        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        res1 = q.get(timeout=5)
        res2 = q.get(timeout=5)

        assert res1[0] == "SUCCESS"
        assert res2[0] == "SUCCESS"
        # Both processes MUST get the identical artifact_id
        assert res1[1] == res2[1]

        # Verify exactly one entity exists in database
        st = SQLiteStorage(multiprocess_env["db_path"])
        p = PersistenceLayer(storage=st)
        entities = p.query_entities(EntityType.DURABLE_ARTIFACT, {"artifact_key": art_key})
        assert len(entities) == 1
        st.close()

    def test_concurrent_stage_exclusivity(self, multiprocess_env: dict) -> None:
        # Pre-register an artifact
        st = SQLiteStorage(multiprocess_env["db_path"])
        p = PersistenceLayer(storage=st)
        cat = DurableArtifactCatalog(persistence=p, owner_id="init_worker")
        art_key = derive_artifact_key(artifact_name="stage_race.py")
        state = cat.register_artifact(artifact_key=art_key)
        art_id_str = str(state.artifact_id)
        st.close()

        ctx = mp.get_context("spawn")
        q = ctx.Queue()

        file1 = str(Path(multiprocess_env["staging_root"]) / "file1.tmp")
        file2 = str(Path(multiprocess_env["staging_root"]) / "file2.tmp")

        p1 = ctx.Process(
            target=_worker_stage,
            args=(multiprocess_env["db_path"], art_id_str, file1, 1, q),
        )
        p2 = ctx.Process(
            target=_worker_stage,
            args=(multiprocess_env["db_path"], art_id_str, file2, 1, q),
        )

        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        results = [q.get(timeout=5), q.get(timeout=5)]
        successes = [r for r in results if r[0] == "SUCCESS"]
        errors = [r for r in results if r[0] == "ERROR"]

        # Exactly one must succeed, the other must experience a conflict
        assert len(successes) == 1
        assert len(errors) == 1
        assert errors[0][1] in ("VersionConflictError", "InvalidTransitionError")

    def test_concurrent_conflicting_commit(self, multiprocess_env: dict) -> None:
        # Pre-register and stage an artifact with physical file
        st = SQLiteStorage(multiprocess_env["db_path"])
        p = PersistenceLayer(storage=st)
        p_store = PhysicalArtifactStore(
            artifact_root=multiprocess_env["art_root"],
            staging_root=multiprocess_env["staging_root"],
        )
        cat = DurableArtifactCatalog(persistence=p, owner_id="init_worker", physical_store=p_store)
        art_key = derive_artifact_key(artifact_name="commit_race.py")
        state = cat.register_artifact(artifact_key=art_key)
        staging_file = Path(multiprocess_env["staging_root"]) / "commit_race.tmp"
        p_store.write_staging_bytes(staging_file, b"data")
        staged = cat.begin_staging(state.artifact_id, staging_path=str(staging_file))
        st.close()

        ctx = mp.get_context("spawn")
        q = ctx.Queue()

        # Both processes attempt commit with expected_version = staged.state_version
        p1 = ctx.Process(
            target=_worker_commit,
            args=(multiprocess_env["db_path"], str(state.artifact_id), str(staging_file), staged.state_version, q),
        )
        p2 = ctx.Process(
            target=_worker_commit,
            args=(multiprocess_env["db_path"], str(state.artifact_id), str(staging_file), staged.state_version, q),
        )

        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        results = [q.get(timeout=5), q.get(timeout=5)]
        successes = [r for r in results if r[0] == "SUCCESS"]
        errors = [r for r in results if r[0] == "ERROR"]

        # Exactly one must succeed; second gets OCC or transition error
        assert len(successes) == 1
        assert len(errors) == 1
        assert errors[0][1] in ("VersionConflictError", "InvalidTransitionError")

    def test_concurrent_different_artifacts(self, multiprocess_env: dict) -> None:
        num_workers = 4
        ctx = mp.get_context("spawn")
        q = ctx.Queue()

        processes = []
        for i in range(num_workers):
            p = ctx.Process(
                target=_worker_create_and_commit,
                args=(
                    multiprocess_env["db_path"],
                    multiprocess_env["art_root"],
                    multiprocess_env["staging_root"],
                    f"artifact_{i}.dat",
                    q,
                ),
            )
            processes.append(p)
            p.start()

        for p in processes:
            p.join(timeout=10)

        results = [q.get(timeout=5) for _ in range(num_workers)]
        successes = [r for r in results if r[0] == "SUCCESS"]
        assert len(successes) == num_workers

        # Verify all are COMMITTED in database
        st = SQLiteStorage(multiprocess_env["db_path"])
        p = PersistenceLayer(storage=st)
        entities = p.query_entities(EntityType.DURABLE_ARTIFACT, {"status": DurableArtifactStatus.COMMITTED.value})
        assert len(entities) >= num_workers
        st.close()

    def test_concurrent_repeated_reconciliation(self, multiprocess_env: dict) -> None:
        ctx = mp.get_context("spawn")
        q = ctx.Queue()

        p1 = ctx.Process(target=_worker_reconcile, args=(multiprocess_env["db_path"], q))
        p2 = ctx.Process(target=_worker_reconcile, args=(multiprocess_env["db_path"], q))

        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        r1 = q.get(timeout=5)
        r2 = q.get(timeout=5)
        assert r1[0] == "SUCCESS"
        assert r2[0] == "SUCCESS"

    def test_concurrent_queries_during_writes(self, multiprocess_env: dict) -> None:
        wf_id = uuid.uuid4()
        # Pre-seed 2 artifacts for workflow
        st = SQLiteStorage(multiprocess_env["db_path"])
        p = PersistenceLayer(storage=st)
        cat = DurableArtifactCatalog(persistence=p, owner_id="init_worker")
        cat.register_artifact(artifact_key=derive_artifact_key(artifact_name="seed1", workflow_id=wf_id), workflow_id=wf_id)
        cat.register_artifact(artifact_key=derive_artifact_key(artifact_name="seed2", workflow_id=wf_id), workflow_id=wf_id)
        st.close()

        ctx = mp.get_context("spawn")
        q_write = ctx.Queue()
        q_read = ctx.Queue()

        # Run writer and reader concurrently
        p_write = ctx.Process(
            target=_worker_create_and_commit,
            args=(
                multiprocess_env["db_path"],
                multiprocess_env["art_root"],
                multiprocess_env["staging_root"],
                "bg_write.txt",
                q_write,
            ),
        )
        p_read = ctx.Process(
            target=_worker_query,
            args=(multiprocess_env["db_path"], str(wf_id), q_read),
        )

        p_write.start()
        p_read.start()
        p_write.join(timeout=10)
        p_read.join(timeout=10)

        res_write = q_write.get(timeout=5)
        res_read = q_read.get(timeout=5)

        assert res_write[0] == "SUCCESS"
        assert res_read[0] == "SUCCESS"
        assert res_read[1] >= 2
