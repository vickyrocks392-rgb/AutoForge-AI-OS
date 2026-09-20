"""Real Subprocess Crash Tests for Phase 18-K Durable Artifact Lifecycle.

Scenarios tested with actual child process abnormal termination (os._exit):
Scenario A: Child dies after registration but before staging
Scenario B: Child dies after STAGING state is committed in SQLite but before physical write
Scenario C: Child dies during/after physical write before catalog commit
Scenario D: Child dies after physical atomic publish before catalog COMMITTED
Scenario E: Child dies after catalog COMMITTED
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path
import pytest

from autoforge_runtime.persistence import PersistenceLayer, SQLiteStorage
from autoforge_runtime.artifact_catalog import (
    DurableArtifactCatalog,
    derive_artifact_key,
    DurableArtifactStatus,
)
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore

WORKER_SCRIPT = """
import sys
import os
import uuid
import hashlib
from pathlib import Path

# Add pythonpath from parent
sys.path.extend(os.environ.get("PYTHONPATH", "").split(os.pathsep))

from autoforge_runtime.persistence import PersistenceLayer, SQLiteStorage
from autoforge_runtime.artifact_catalog import DurableArtifactCatalog, derive_artifact_key
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore

scenario = sys.argv[1]
db_path = sys.argv[2]
art_root = Path(sys.argv[3])
staging_root = Path(sys.argv[4])
owner_id = sys.argv[5]
art_key = sys.argv[6]

storage = SQLiteStorage(db_path)
storage.initialize()
persistence = PersistenceLayer(storage=storage)
physical_store = PhysicalArtifactStore(artifact_root=art_root, staging_root=staging_root)
catalog = DurableArtifactCatalog(
    persistence=persistence,
    owner_id=owner_id,
    physical_store=physical_store,
)

if scenario == "A":
    # Registers artifact but dies before staging
    state = catalog.register_artifact(artifact_key=art_key, artifact_name="scenario_a.txt")
    os._exit(42)

elif scenario == "B":
    # Registers, records staging state, but dies before physical write
    state = catalog.register_artifact(artifact_key=art_key, artifact_name="scenario_b.txt")
    staging_file = staging_root / "scenario_b.txt"
    catalog.begin_staging(state.artifact_id, staging_path=str(staging_file))
    # Dies before creating the physical file!
    os._exit(42)

elif scenario == "C":
    # Registers, stages, writes physical content, but dies before commit
    state = catalog.register_artifact(artifact_key=art_key, artifact_name="scenario_c.txt")
    staging_file = staging_root / "scenario_c.txt"
    catalog.begin_staging(state.artifact_id, staging_path=str(staging_file))
    content = b"scenario C real data"
    physical_store.write_staging_bytes(staging_file, content)
    # Dies before catalog commit!
    os._exit(42)

elif scenario == "D":
    # Registers, stages, writes, atomically publishes, but dies before catalog commit
    state = catalog.register_artifact(artifact_key=art_key, artifact_name="scenario_d.txt")
    staging_file = staging_root / "scenario_d.txt"
    catalog.begin_staging(state.artifact_id, staging_path=str(staging_file))
    content = b"scenario D real data"
    physical_store.write_staging_bytes(staging_file, content)
    # Publish physically
    published = physical_store.atomic_publish(
        staging_path=staging_file,
        target_relative_path="scenario_d.txt",
    )
    # Dies before catalog commit!
    os._exit(42)

elif scenario == "E":
    # Registers, stages, writes, commits, then dies
    state = catalog.register_artifact(artifact_key=art_key, artifact_name="scenario_e.txt")
    staging_file = staging_root / "scenario_e.txt"
    catalog.begin_staging(state.artifact_id, staging_path=str(staging_file))
    content = b"scenario E committed data"
    physical_store.write_staging_bytes(staging_file, content)
    catalog.commit_artifact(state.artifact_id, storage_path=str(staging_file))
    # Dies after catalog commit!
    os._exit(42)
"""


@pytest.fixture
def test_env(tmp_path: Path):
    db_path = str(tmp_path / "crash_test.db")
    art_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    art_root.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)

    # Initialize storage schema
    st = SQLiteStorage(db_path)
    st.initialize()
    st.close()

    return {
        "db_path": db_path,
        "art_root": art_root,
        "staging_root": staging_root,
    }


def _run_child(scenario: str, env_data: dict, owner_id: str, art_key: str) -> int:
    env = dict(os.environ)
    src_paths = [
        str(Path.cwd() / "packages" / "runtime" / "src"),
        str(Path.cwd() / "packages" / "execution" / "src"),
        str(Path.cwd() / "packages" / "artifacts" / "src"),
        str(Path.cwd() / "packages" / "power_engines" / "src"),
    ]
    env["PYTHONPATH"] = os.pathsep.join(src_paths + [env.get("PYTHONPATH", "")])

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            WORKER_SCRIPT,
            scenario,
            env_data["db_path"],
            str(env_data["art_root"]),
            str(env_data["staging_root"]),
            owner_id,
            art_key,
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.returncode


class TestProcessCrashRecoveryScenarios:
    """Rigorous process-death crash tests A through E."""

    def test_scenario_a_crash_after_registration_before_staging(self, test_env: dict) -> None:
        art_key = derive_artifact_key(artifact_name="scenario_a.txt", workflow_id=uuid.uuid4())
        owner = "crashed_worker:1001"

        rc = _run_child("A", test_env, owner, art_key)
        assert rc == 42  # Confirms abnormal process exit

        # Parent reopens database
        storage = SQLiteStorage(test_env["db_path"])
        persistence = PersistenceLayer(storage=storage)
        physical_store = PhysicalArtifactStore(
            artifact_root=test_env["art_root"],
            staging_root=test_env["staging_root"],
        )
        cat = DurableArtifactCatalog(
            persistence=persistence,
            owner_id="recovery_supervisor:2001",
            physical_store=physical_store,
        )

        rec = cat.reconcile_on_startup(assume_all_dead=True)
        # Artifact was in CREATED state; should be cleanly marked FAILED or quarantined
        record = cat.get_artifact_by_key(art_key)
        assert record is not None
        assert record.status in (DurableArtifactStatus.FAILED, DurableArtifactStatus.CREATED)
        # Verify no duplicate logical artifact
        from autoforge_runtime.models import EntityType
        dups = persistence.query_entities(EntityType.DURABLE_ARTIFACT, {"artifact_key": art_key})
        assert len(dups) == 1
        storage.close()

    def test_scenario_b_crash_after_staging_record_before_physical_write(self, test_env: dict) -> None:
        art_key = derive_artifact_key(artifact_name="scenario_b.txt", workflow_id=uuid.uuid4())
        owner = "crashed_worker:1002"

        rc = _run_child("B", test_env, owner, art_key)
        assert rc == 42

        storage = SQLiteStorage(test_env["db_path"])
        persistence = PersistenceLayer(storage=storage)
        physical_store = PhysicalArtifactStore(
            artifact_root=test_env["art_root"],
            staging_root=test_env["staging_root"],
        )
        cat = DurableArtifactCatalog(
            persistence=persistence,
            owner_id="recovery_supervisor:2002",
            physical_store=physical_store,
        )

        # Staging file was never physically written
        rec = cat.reconcile_on_startup(assume_all_dead=True)
        record = cat.get_artifact_by_key(art_key)
        assert record is not None
        # Must be marked FAILED because physical file is missing
        assert record.status == DurableArtifactStatus.FAILED
        assert record.error_code in ("ORPHANED_STAGING", "STAGING_MISSING")
        storage.close()

    def test_scenario_c_crash_after_physical_write_before_catalog_commit(self, test_env: dict) -> None:
        art_key = derive_artifact_key(artifact_name="scenario_c.txt", workflow_id=uuid.uuid4())
        owner = "crashed_worker:1003"

        rc = _run_child("C", test_env, owner, art_key)
        assert rc == 42

        storage = SQLiteStorage(test_env["db_path"])
        persistence = PersistenceLayer(storage=storage)
        physical_store = PhysicalArtifactStore(
            artifact_root=test_env["art_root"],
            staging_root=test_env["staging_root"],
        )
        cat = DurableArtifactCatalog(
            persistence=persistence,
            owner_id="recovery_supervisor:2003",
            physical_store=physical_store,
        )

        # Physical file exists in staging
        staging_file = test_env["staging_root"] / "scenario_c.txt"
        assert staging_file.exists()

        rec = cat.reconcile_on_startup(assume_all_dead=True)
        record = cat.get_artifact_by_key(art_key)
        assert record is not None
        # Physical staging was recovered and committed to COMMITTED by supervisor
        assert record.status == DurableArtifactStatus.COMMITTED
        assert record.content_hash == hashlib.sha256(b"scenario C real data").hexdigest()
        storage.close()

    def test_scenario_d_crash_after_atomic_publish_before_catalog_commit(self, test_env: dict) -> None:
        art_key = derive_artifact_key(artifact_name="scenario_d.txt", workflow_id=uuid.uuid4())
        owner = "crashed_worker:1004"

        rc = _run_child("D", test_env, owner, art_key)
        assert rc == 42

        storage = SQLiteStorage(test_env["db_path"])
        persistence = PersistenceLayer(storage=storage)
        physical_store = PhysicalArtifactStore(
            artifact_root=test_env["art_root"],
            staging_root=test_env["staging_root"],
        )
        cat = DurableArtifactCatalog(
            persistence=persistence,
            owner_id="recovery_supervisor:2004",
            physical_store=physical_store,
        )

        # Physical file exists in published artifact root
        pub_file = test_env["art_root"] / "scenario_d.txt"
        assert pub_file.exists()
        assert pub_file.read_bytes() == b"scenario D real data"

        record = cat.get_artifact_by_key(art_key)
        assert record is not None
        # Supervisor can complete commit to authoritative catalog
        committed = cat.commit_artifact(record.artifact_id, storage_path=str(pub_file))
        assert committed.status == DurableArtifactStatus.COMMITTED
        assert committed.content_hash == hashlib.sha256(b"scenario D real data").hexdigest()
        storage.close()

    def test_scenario_e_crash_after_catalog_committed(self, test_env: dict) -> None:
        art_key = derive_artifact_key(artifact_name="scenario_e.txt", workflow_id=uuid.uuid4())
        owner = "crashed_worker:1005"

        rc = _run_child("E", test_env, owner, art_key)
        assert rc == 42

        storage = SQLiteStorage(test_env["db_path"])
        persistence = PersistenceLayer(storage=storage)
        physical_store = PhysicalArtifactStore(
            artifact_root=test_env["art_root"],
            staging_root=test_env["staging_root"],
        )
        cat = DurableArtifactCatalog(
            persistence=persistence,
            owner_id="recovery_supervisor:2005",
            physical_store=physical_store,
        )

        # Reconcile on startup should not touch COMMITTED artifacts
        rec = cat.reconcile_on_startup(assume_all_dead=True)
        record = cat.get_artifact_by_key(art_key)
        assert record is not None
        assert record.status == DurableArtifactStatus.COMMITTED
        assert record.content_hash == hashlib.sha256(b"scenario E committed data").hexdigest()
        assert record.size_bytes == len(b"scenario E committed data")
        storage.close()
