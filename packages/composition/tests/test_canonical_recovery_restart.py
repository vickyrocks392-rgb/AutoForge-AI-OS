"""
Composition Regression Tests: Canonical System Restart & Subprocess Crash Recovery (Part 14 & 15).

Demonstrates true durability across genuine OS process boundaries:
1. Subprocess executes a canonical AutoForge task, producing durable runtime state & artifacts.
2. Subprocess terminates abruptly via hard OS crash (os._exit(42)).
3. Fresh system is reconstructed in a completely isolated process/instance pointing to the same workspace & SQLite database.
4. State, durable catalog metadata, physical file integrity, and artifact platform resolution are verified without any in-memory object reuse.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import pytest

from autoforge_composition.composition_root import build_autoforge_system


SUBPROCESS_CRASH_RUNNER = """
import asyncio
import os
import sys
from pathlib import Path
import uuid

# Set pythonpath
sys.path.extend(os.environ.get("PYTHONPATH", "").split(os.pathsep))

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_workflows.models import TaskDefinition, WorkflowDefinition

async def run_and_crash(ws_path: str):
    system = build_autoforge_system(workspace_root=ws_path)
    await system.initialize()

    task_def = TaskDefinition(
        task_id="task-crash-durability",
        name="Crash Durability Task",
        task_type="coding",
        input_data={
            "files": [{"path": "recovered.py", "content": "print('resurrected')\\n"}],
            "commands": [[sys.executable, "recovered.py"]],
        },
    )
    workflow_def = WorkflowDefinition(
        name="Durability Crash Workflow",
        tasks=[task_def],
    )
    handle = system.workflow_engine.submit(workflow_def)
    completed = await system.execution_engine.run_workflow_to_completion(handle)

    # Hard crash via os._exit to bypass normal exit handlers and prevent in-memory cleanup
    os._exit(42)

if __name__ == "__main__":
    asyncio.run(run_and_crash(sys.argv[1]))
"""


@pytest.mark.asyncio
async def test_canonical_system_restart_after_hard_crash(tmp_path: Path):
    ws_path = str(tmp_path)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    package_srcs = [
        str(p / "src") for p in (repo_root / "packages").iterdir()
        if (p / "src").is_dir()
    ]
    env = dict(os.environ)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(package_srcs + ([existing_pp] if existing_pp else []))
    env["AUTOFORGE_ALLOW_DETERMINISTIC_FALLBACK"] = "1"

    # 1. Run canonical task in child process and simulate hard crash (os._exit(42))
    cmd = [sys.executable, "-c", SUBPROCESS_CRASH_RUNNER, ws_path]

    proc = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    # Verify that child process terminated via hard crash (exit code 42)
    assert proc.returncode == 42, f"Expected child to terminate with exit code 42, got {proc.returncode}. Stderr: {proc.stderr}"

    # 2. In a completely fresh Python instance, reconstruct the system from the durable workspace
    recovered_system = build_autoforge_system(workspace_root=ws_path)
    await recovered_system.initialize()

    try:
        # 3. Verify physical artifact store contains the produced file
        art_files = list((tmp_path / "artifacts").glob("*"))
        # Exclude internal folders .staging and .quarantine
        valid_files = [f for f in art_files if f.is_file() and not f.name.startswith(".")]
        assert len(valid_files) >= 1, "Physical artifact store must contain the persisted artifact file"

        # 4. Verify durable catalog recovery
        artifacts_in_catalog = recovered_system.durable_catalog.find_by_task("task-crash-durability")
        assert len(artifacts_in_catalog) >= 1, "Durable catalog must have reconstructed artifacts from SQLite storage"

        recovered_art_meta = artifacts_in_catalog[0]
        art_id = recovered_art_meta.artifact_id
        assert recovered_art_meta.storage_path is not None
        assert Path(recovered_art_meta.storage_path).exists()
        assert recovered_art_meta.status.value == "committed"

        # 5. Verify physical hash and size match recovered catalog metadata
        file_hash, file_size = recovered_system.physical_store.inspect_file(Path(recovered_art_meta.storage_path))
        assert file_hash == recovered_art_meta.content_hash
        assert file_size == recovered_art_meta.size_bytes

        # 6. Verify ArtifactPlatform resolves the recovered durable artifact
        platform_art = recovered_system.artifact_platform.manager.get_artifact(art_id)
        assert platform_art is not None
        assert platform_art.artifact_id == art_id

        # 7. Verify execution engine pipeline can retrieve artifact by ID
        pipeline_art = recovered_system.execution_engine._artifacts.get_artifact(art_id)
        assert pipeline_art is not None
        assert pipeline_art.artifact_id == art_id
        assert pipeline_art.checksum == recovered_art_meta.content_hash

    finally:
        await recovered_system.shutdown()
