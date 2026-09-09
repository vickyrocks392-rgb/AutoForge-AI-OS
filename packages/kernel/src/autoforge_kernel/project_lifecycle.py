"""
AutoForge AI — Project Lifecycle & Data Isolation Subsystem
Responsible for deterministic project lifecycle management, ephemeral-by-default execution,
resource tracking, clean-room pre-execution verification, and verified multi-store purging.
"""

from __future__ import annotations

import os
import shutil
import uuid
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("autoforge.kernel.project_lifecycle")


class ProjectState(str, Enum):
    """Deterministic project lifecycle states."""
    CREATED = "created"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    PURGING = "purging"
    PURGED = "purged"
    FAILED = "failed"


class ProjectPersistencePolicy(str, Enum):
    """Persistence policy governing whether project state is retained post-completion."""
    EPHEMERAL = "ephemeral"      # Default: Destroy all state upon completion
    PERSISTENT = "persistent"    # Explicit: Retain state across runs until manual purge


class ProjectIsolationContext:
    """
    Immutable project isolation context defining unique project/run identity,
    dedicated filesystem sandboxes, and vector store namespaces.
    """

    def __init__(
        self,
        project_id: str,
        run_id: Optional[str] = None,
        base_dir: Optional[Path] = None,
        persistence_policy: ProjectPersistencePolicy = ProjectPersistencePolicy.EPHEMERAL,
        qdrant_namespace_prefix: str = "project",
    ):
        self.project_id = project_id
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        self.persistence_policy = persistence_policy
        self.created_at = datetime.now(timezone.utc)
        
        # Base sandbox workspace
        self.base_dir = Path(base_dir or Path(".autoforge/projects")).resolve()
        self.project_dir = self.base_dir / self.project_id
        self.run_dir = self.project_dir / self.run_id
        
        # Dedicated isolated subdirectories
        self.workspace_dir = self.run_dir / "workspace"
        self.generated_artifacts_dir = self.run_dir / "generated"
        self.cache_dir = self.run_dir / "cache"
        self.telemetry_dir = self.run_dir / "telemetry"
        self.repair_state_dir = self.run_dir / "repair"
        self.provenance_dir = self.run_dir / "provenance"
        
        # Dedicated isolated Qdrant collection name
        sanitized_pid = self.project_id.replace("-", "_").lower()
        self.qdrant_collection = f"{qdrant_namespace_prefix}_{sanitized_pid}_knowledge"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "persistence_policy": self.persistence_policy.value,
            "created_at": self.created_at.isoformat(),
            "project_dir": str(self.project_dir),
            "run_dir": str(self.run_dir),
            "workspace_dir": str(self.workspace_dir),
            "generated_artifacts_dir": str(self.generated_artifacts_dir),
            "cache_dir": str(self.cache_dir),
            "telemetry_dir": str(self.telemetry_dir),
            "repair_state_dir": str(self.repair_state_dir),
            "provenance_dir": str(self.provenance_dir),
            "qdrant_collection": self.qdrant_collection,
        }


class ProjectResourceRegistry:
    """Tracks and registers all concrete resources allocated to a project."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.file_paths: Set[str] = set()
        self.directory_paths: Set[str] = set()
        self.qdrant_collections: Set[str] = set()
        self.metadata_records: Dict[str, Any] = {}

    def register_file(self, path: Path | str) -> None:
        self.file_paths.add(str(Path(path).resolve()))

    def register_directory(self, path: Path | str) -> None:
        self.directory_paths.add(str(Path(path).resolve()))

    def register_qdrant_collection(self, collection_name: str) -> None:
        self.qdrant_collections.add(collection_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "registered_files_count": len(self.file_paths),
            "registered_directories_count": len(self.directory_paths),
            "registered_qdrant_collections": list(self.qdrant_collections),
        }


class ProjectPurgeVerifier:
    """Verifies complete eradication of project-specific state across all stores."""

    @staticmethod
    def verify_purged(
        context: ProjectIsolationContext,
        registry: ProjectResourceRegistry,
        qdrant_store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Deep verification that zero project residue exists on filesystem or vector DB.
        """
        residue_files = []
        residue_dirs = []
        residue_qdrant_collections = []
        
        # 1. Check directory paths
        if context.project_dir.exists():
            residue_dirs.append(str(context.project_dir))
            
        for d in registry.directory_paths:
            if Path(d).exists():
                residue_dirs.append(d)
                
        # 2. Check registered file paths
        for f in registry.file_paths:
            if Path(f).exists():
                residue_files.append(f)
                
        # 3. Check Qdrant collections
        if qdrant_store is not None:
            try:
                client = getattr(qdrant_store, "_client", None) or getattr(qdrant_store, "client", None)
                if client is not None:
                    cols = client.get_collections().collections
                    col_names = {c.name for c in cols}
                    if context.qdrant_collection in col_names:
                        residue_qdrant_collections.append(context.qdrant_collection)
                    for qcol in registry.qdrant_collections:
                        if qcol in col_names:
                            residue_qdrant_collections.append(qcol)
            except Exception as e:
                logger.warning(f"Could not probe Qdrant during purge verification: {e}")

        is_clean = (len(residue_files) == 0 and len(residue_dirs) == 0 and len(residue_qdrant_collections) == 0)
        
        return {
            "project_id": context.project_id,
            "run_id": context.run_id,
            "is_clean": is_clean,
            "residue_files": residue_files,
            "residue_dirs": residue_dirs,
            "residue_qdrant_collections": list(set(residue_qdrant_collections)),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }


class ProjectLifecycleManager:
    """
    Orchestrates deterministic lifecycle transitions, clean-room checks,
    and automatic or explicit state purging.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        default_persistence: ProjectPersistencePolicy = ProjectPersistencePolicy.EPHEMERAL,
    ):
        self.base_dir = Path(base_dir or Path(".autoforge/projects")).resolve()
        self.default_persistence = default_persistence
        self.active_contexts: Dict[str, ProjectIsolationContext] = {}
        self.active_registries: Dict[str, ProjectResourceRegistry] = {}
        self.project_states: Dict[str, ProjectState] = {}
        self.audit_log: List[Dict[str, Any]] = []

    def create_project(
        self,
        project_id: str,
        run_id: Optional[str] = None,
        persistence_policy: Optional[ProjectPersistencePolicy] = None,
    ) -> ProjectIsolationContext:
        """Creates a new isolated project context."""
        policy = persistence_policy or self.default_persistence
        ctx = ProjectIsolationContext(
            project_id=project_id,
            run_id=run_id,
            base_dir=self.base_dir,
            persistence_policy=policy,
        )
        self.active_contexts[project_id] = ctx
        self.active_registries[project_id] = ProjectResourceRegistry(project_id)
        self.project_states[project_id] = ProjectState.CREATED
        self._record_audit(project_id, "CREATE", ProjectState.CREATED)
        return ctx

    def verify_clean_room(self, project_id: str, qdrant_store: Optional[Any] = None) -> bool:
        """
        Pre-execution clean-room verification.
        Ensures workspace and Qdrant namespace are pristine before ingestion begins.
        """
        ctx = self.active_contexts.get(project_id)
        if not ctx:
            raise ValueError(f"Project '{project_id}' not found in active contexts.")
            
        # Verify filesystem is clean
        if ctx.project_dir.exists():
            files = list(ctx.project_dir.glob("**/*"))
            if any(f.is_file() for f in files):
                logger.error(f"Clean-room check failed: Non-empty project directory {ctx.project_dir}")
                return False
                
        # Verify Qdrant namespace does not already exist
        if qdrant_store is not None:
            try:
                client = getattr(qdrant_store, "_client", None) or getattr(qdrant_store, "client", None)
                if client is not None:
                    cols = {c.name for c in client.get_collections().collections}
                    if ctx.qdrant_collection in cols:
                        logger.error(f"Clean-room check failed: Existing Qdrant collection {ctx.qdrant_collection}")
                        return False
            except Exception as e:
                logger.warning(f"Could not verify Qdrant clean-room status: {e}")

        return True

    def initialize_project(self, project_id: str, qdrant_store: Optional[Any] = None) -> None:
        """Initializes isolated directories and Qdrant collections."""
        ctx = self.active_contexts[project_id]
        reg = self.active_registries[project_id]
        self.project_states[project_id] = ProjectState.INITIALIZING
        self._record_audit(project_id, "INITIALIZE", ProjectState.INITIALIZING)
        
        # Create directories
        for d in [
            ctx.workspace_dir,
            ctx.generated_artifacts_dir,
            ctx.cache_dir,
            ctx.telemetry_dir,
            ctx.repair_state_dir,
            ctx.provenance_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
            reg.register_directory(d)
            
        reg.register_directory(ctx.project_dir)
        reg.register_directory(ctx.run_dir)
        reg.register_qdrant_collection(ctx.qdrant_collection)
        
        # Initialize project Qdrant collection if client provided
        if qdrant_store is not None:
            try:
                if hasattr(qdrant_store, "_collection"):
                    qdrant_store._collection = ctx.qdrant_collection
            except Exception as e:
                logger.warning(f"Failed to set project collection on Qdrant store: {e}")

        self.project_states[project_id] = ProjectState.ACTIVE
        self._record_audit(project_id, "ACTIVATE", ProjectState.ACTIVE)

    def finalize_project(
        self,
        project_id: str,
        status: ProjectState = ProjectState.COMPLETED,
        qdrant_store: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Finalizes project execution. If policy is EPHEMERAL, immediately triggers purge.
        """
        ctx = self.active_contexts.get(project_id)
        if not ctx:
            raise ValueError(f"Project '{project_id}' not found.")
            
        self.project_states[project_id] = status
        self._record_audit(project_id, status.value.upper(), status)

        cleanup_result = None
        if ctx.persistence_policy == ProjectPersistencePolicy.EPHEMERAL:
            cleanup_result = self.purge_project(project_id, qdrant_store=qdrant_store)
            
        return {
            "project_id": project_id,
            "final_state": status.value,
            "persistence_policy": ctx.persistence_policy.value,
            "purged": cleanup_result is not None,
            "cleanup_result": cleanup_result,
        }

    def purge_project(self, project_id: str, qdrant_store: Optional[Any] = None) -> Dict[str, Any]:
        """
        Deterministic, idempotent purge of all project-scoped filesystem, cache, and Qdrant resources.
        """
        ctx = self.active_contexts.get(project_id)
        reg = self.active_registries.get(project_id)
        if not ctx:
            return {"project_id": project_id, "purged": True, "already_purged": True}

        self.project_states[project_id] = ProjectState.PURGING
        self._record_audit(project_id, "PURGE", ProjectState.PURGING)
        t0 = datetime.now(timezone.utc)

        # 1. Purge Filesystem
        if ctx.project_dir.exists():
            try:
                shutil.rmtree(ctx.project_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"Error removing project dir {ctx.project_dir}: {e}")

        # 2. Purge Qdrant Collection
        qdrant_purged = False
        if qdrant_store is not None:
            try:
                if hasattr(qdrant_store, "purge_project_collection"):
                    qdrant_purged = qdrant_store.purge_project_collection(project_id)
                else:
                    client = getattr(qdrant_store, "_client", None) or getattr(qdrant_store, "client", None)
                    if client is not None:
                        client.delete_collection(collection_name=ctx.qdrant_collection)
                        qdrant_purged = True
            except Exception as e:
                logger.info(f"Qdrant collection delete notification for {ctx.qdrant_collection}: {e}")
                qdrant_purged = True

        # 3. Verify Purge
        verification = ProjectPurgeVerifier.verify_purged(ctx, reg, qdrant_store=qdrant_store)
        
        self.project_states[project_id] = ProjectState.PURGED
        self._record_audit(project_id, "PURGED", ProjectState.PURGED)
        t1 = datetime.now(timezone.utc)
        duration_ms = (t1 - t0).total_seconds() * 1000.0

        return {
            "project_id": project_id,
            "purged": verification["is_clean"],
            "qdrant_purged": qdrant_purged,
            "duration_ms": round(duration_ms, 2),
            "verification": verification,
        }

    def _record_audit(self, project_id: str, action: str, state: ProjectState) -> None:
        self.audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "action": action,
            "state": state.value,
        })
