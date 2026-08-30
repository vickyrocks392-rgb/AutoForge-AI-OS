"""Durable execution state persistence (Phase 18).

Snapshots ``ProjectExecutionState`` to JSON files so that process restart
can resume from the last durable stage state. Uses only stdlib ``json``
and ``pathlib`` — no external dependencies beyond what the platform already
provides.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from autoforge_orchestration.errors import PersistenceError
from autoforge_orchestration.models import ProjectExecutionState


class StatePersistence:
    """Persists and restores :class:`ProjectExecutionState` snapshots.

    Snapshots are written atomically (temp-file + os.replace) to survive
    process crashes during writes. Each execution gets its own JSON file.
    """

    def __init__(self, state_dir: str | Path) -> None:
        self._dir = Path(state_dir).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def state_dir(self) -> Path:
        return self._dir

    def snapshot_path(self, execution_id: str) -> Path:
        """Return the filesystem path for an execution's snapshot."""
        safe = execution_id.replace("/", "_").replace("\\", "_")
        return self._dir / f"execution_{safe}.json"

    def save(self, state: ProjectExecutionState) -> None:
        """Atomically persist the full execution state snapshot."""
        try:
            snapshot = state.to_snapshot()
            path = self.snapshot_path(state.execution_id)
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception as exc:
            raise PersistenceError(
                f"Failed to persist execution state for {state.execution_id}: {exc}",
                details={"execution_id": state.execution_id, "error": str(exc)},
            ) from exc

    def load(self, execution_id: str) -> ProjectExecutionState | None:
        """Load a persisted execution state, or ``None`` if not found."""
        path = self.snapshot_path(execution_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                snapshot: dict[str, Any] = json.load(fh)
            return ProjectExecutionState.from_snapshot(snapshot)
        except Exception as exc:
            raise PersistenceError(
                f"Failed to load execution state for {execution_id}: {exc}",
                details={"execution_id": execution_id, "error": str(exc)},
            ) from exc

    def exists(self, execution_id: str) -> bool:
        """Check whether a snapshot exists for the given execution."""
        return self.snapshot_path(execution_id).exists()

    def delete(self, execution_id: str) -> bool:
        """Delete the snapshot for an execution. Returns True if it existed."""
        path = self.snapshot_path(execution_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_executions(self) -> list[str]:
        """List all persisted execution IDs."""
        results: list[str] = []
        for entry in self._dir.iterdir():
            if entry.is_file() and entry.name.startswith("execution_") and entry.suffix == ".json":
                execution_id = entry.name[len("execution_"):-len(".json")]
                results.append(execution_id)
        return sorted(results)


class SnapshotStore:
    """Thin adapter wrapping :class:`StatePersistence` for snapshot I/O.

    This class is provided for API symmetry — it exposes the same
    load/save/delete interface so callers can treat it as a generic
    snapshot store without depending on persistence internals directly.
    """

    def __init__(self, state_persistence: StatePersistence) -> None:
        self._persistence = state_persistence

    def save(self, state: ProjectExecutionState) -> None:
        self._persistence.save(state)

    def load(self, execution_id: str) -> ProjectExecutionState | None:
        return self._persistence.load(execution_id)

    def exists(self, execution_id: str) -> bool:
        return self._persistence.exists(execution_id)

    def delete(self, execution_id: str) -> bool:
        return self._persistence.delete(execution_id)

    def list_executions(self) -> list[str]:
        return self._persistence.list_executions()



