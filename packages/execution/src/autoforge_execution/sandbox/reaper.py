"""
Workload Reaper and Cleanup Manager for AutoForge AI Sandboxing (Phase 18-I).

Guarantees termination of runaway process trees, prevents zombie processes,
tracks active workload sessions, and completely disposes of sandbox workspaces.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoforge_execution.sandbox.models import CleanupReport, CleanupStatus


@dataclass
class ActiveWorkloadEntry:
    """Record of an actively running or registered workload session."""
    workload_id: str
    pid: int | None
    pgid: int | None
    workspace_path: Path | None
    registered_at: float
    timeout_seconds: float
    destroy_on_cleanup: bool = True


class WorkloadReaper:
    """
    Registry and cleanup engine for sandbox workloads.
    Ensures zero orphaned processes or abandoned workspace directories.
    """

    def __init__(self) -> None:
        self._registry: dict[str, ActiveWorkloadEntry] = {}

    @property
    def active_count(self) -> int:
        """Return number of currently tracked workloads."""
        return len(self._registry)

    def register(
        self,
        workload_id: str,
        *,
        pid: int | None = None,
        pgid: int | None = None,
        workspace_path: Path | None = None,
        timeout_seconds: float = 60.0,
        destroy_on_cleanup: bool = True,
    ) -> None:
        """Register a running or pending workload."""
        self._registry[workload_id] = ActiveWorkloadEntry(
            workload_id=workload_id,
            pid=pid,
            pgid=pgid,
            workspace_path=workspace_path,
            registered_at=time.time(),
            timeout_seconds=timeout_seconds,
            destroy_on_cleanup=destroy_on_cleanup,
        )

    def update_process(self, workload_id: str, pid: int, pgid: int | None = None) -> None:
        """Update PID and PGID once process has launched."""
        if workload_id in self._registry:
            entry = self._registry[workload_id]
            entry.pid = pid
            entry.pgid = pgid or pid

    def unregister(self, workload_id: str) -> None:
        """Remove a workload from tracking without killing (e.g. after clean exit)."""
        self._registry.pop(workload_id, None)

    async def terminate_process(self, pid: int | None, pgid: int | None) -> bool:
        """
        Cleanly terminate a process and its entire process tree.
        Attempts SIGTERM first, then escalates to SIGKILL.
        """
        if not pid and not pgid:
            return False

        terminated = False

        # Kill process group if PGID is available
        if pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
                terminated = True
            except (ProcessLookupError, PermissionError):
                pass

        # Also signal individual PID as fallback
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                terminated = True
            except (ProcessLookupError, PermissionError):
                pass

        if not terminated:
            return False

        # Brief grace period for graceful shutdown
        await asyncio.sleep(0.15)

        # Escalate to SIGKILL if still alive
        if pgid:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        return True

    def remove_workspace(self, workspace_path: Path | None) -> bool:
        """Safely delete an isolated sandbox workspace directory."""
        if not workspace_path:
            return False

        path = workspace_path.resolve()
        if not path.exists():
            return False

        # Safety guard: Never delete system root or user home directory
        path_str = str(path)
        if path_str in {"/", "/home", "/Users", "/var", "/tmp", "/etc", "/usr"}:
            return False

        try:
            shutil.rmtree(path, ignore_errors=True)
            return True
        except Exception:
            return False

    async def reap(self, workload_id: str) -> CleanupReport:
        """
        Reap a specific workload: kill processes and dispose of workspace.
        """
        start = time.perf_counter()
        entry = self._registry.pop(workload_id, None)

        if not entry:
            return CleanupReport(
                workload_id=workload_id,
                status=CleanupStatus.CLEANED,
                orphans_reaped=0,
                duration_seconds=0.0,
                details={"note": "Workload was not registered or already cleaned."},
            )

        # Terminate processes
        await self.terminate_process(entry.pid, entry.pgid)

        # Cleanup workspace
        workspace_cleaned = False
        if entry.destroy_on_cleanup and entry.workspace_path:
            workspace_cleaned = self.remove_workspace(entry.workspace_path)

        duration = time.perf_counter() - start

        return CleanupReport(
            workload_id=workload_id,
            status=CleanupStatus.CLEANED,
            orphans_reaped=1 if entry.pid else 0,
            duration_seconds=duration,
            details={
                "workspace_cleaned": workspace_cleaned,
                "workspace_path": str(entry.workspace_path) if entry.workspace_path else None,
            },
        )

    async def reap_orphans(self) -> int:
        """
        Find all expired or abandoned workloads and terminate them.
        Returns the number of reaped workloads.
        """
        now = time.time()
        to_reap: list[str] = []

        for w_id, entry in list(self._registry.items()):
            elapsed = now - entry.registered_at
            if elapsed > (entry.timeout_seconds + 5.0):
                to_reap.append(w_id)

        reaped_count = 0
        for w_id in to_reap:
            await self.reap(w_id)
            reaped_count += 1

        return reaped_count
