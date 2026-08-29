"""
Application Runtime Manager for AutoForge AI OS.
Manages physical OS processes, ports, lifecycles, and delivery packaging for generated applications.
"""

from __future__ import annotations
import datetime
import json
import os
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
from typing import Any, Dict, List, Optional


class AppProcessInfo:
    def __init__(self, project_id: str, project_dir: str, entrypoint: str = "app.py") -> None:
        self.project_id = project_id
        self.project_dir = project_dir
        self.entrypoint = entrypoint
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.port: Optional[int] = None
        self.url: Optional[str] = None
        self.status: str = "STOPPED"  # STOPPED, STARTING, RUNNING, STOPPING, FAILED
        self.started_at: Optional[str] = None
        self.stopped_at: Optional[str] = None
        self.stdout_lines: List[str] = []
        self.stderr_lines: List[str] = []
        self.error_message: Optional[str] = None
        self.runtime_node: str = "local-m1"

    def to_dict(self) -> Dict[str, Any]:
        # Check if process is still alive if marked RUNNING
        if self.process is not None and self.status == "RUNNING":
            ret = self.process.poll()
            if ret is not None:
                self.status = "STOPPED" if ret == 0 else "FAILED"
                self.stopped_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                if ret != 0 and not self.error_message:
                    self.error_message = f"Process exited with non-zero exit code: {ret}"

        return {
            "project_id": self.project_id,
            "status": self.status,
            "pid": self.pid,
            "port": self.port,
            "url": self.url,
            "entrypoint": self.entrypoint,
            "runtime_node": self.runtime_node,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "error_message": self.error_message,
            "stdout_tail": self.stdout_lines[-20:] if self.stdout_lines else [],
            "stderr_tail": self.stderr_lines[-20:] if self.stderr_lines else [],
        }


class ApplicationRuntimeManager:
    """
    Manages the lifecycle of generated applications: launch, health check, status tracking, termination, and packaging.
    """

    def __init__(self, workspace_root: Optional[str] = None) -> None:
        self.workspace_root = workspace_root or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
        )
        self.builds_dir = os.path.join(self.workspace_root, "builds")
        self.dist_dir = os.path.join(self.workspace_root, "dist")
        os.makedirs(self.builds_dir, exist_ok=True)
        os.makedirs(self.dist_dir, exist_ok=True)

        self._processes: Dict[str, AppProcessInfo] = {}
        self._lock = threading.Lock()

    def _find_free_port(self) -> int:
        """Find an available ephemeral TCP port on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return int(s.getsockname()[1])

    def _validate_project_dir(self, project_id: str) -> str:
        """Sanitize project_id and return absolute path, preventing path traversal."""
        clean_id = os.path.basename(project_id.strip())
        if not clean_id or ".." in project_id or clean_id != project_id:
            raise ValueError(f"Invalid project ID: {project_id}")

        proj_path = os.path.join(self.builds_dir, clean_id)
        if not os.path.isdir(proj_path):
            # Also check fallback legacy apps/builds/
            legacy_path = os.path.join(self.workspace_root, "apps", "builds", clean_id)
            if os.path.isdir(legacy_path):
                return legacy_path
            raise FileNotFoundError(f"Project directory not found for ID: {clean_id}")
        return proj_path

    def launch(self, project_id: str, timeout: float = 8.0) -> Dict[str, Any]:
        """
        Launches the generated application as a real, tracked OS process.
        """
        with self._lock:
            proj_dir = self._validate_project_dir(project_id)
            entrypoint = "app.py"
            entry_path = os.path.join(proj_dir, entrypoint)

            if not os.path.isfile(entry_path):
                raise FileNotFoundError(f"Application entrypoint '{entrypoint}' not found in {proj_dir}")

            # If already running, return current status
            if project_id in self._processes:
                existing = self._processes[project_id]
                if existing.status == "RUNNING" and existing.process and existing.process.poll() is None:
                    return existing.to_dict()

            port = self._find_free_port()
            app_info = AppProcessInfo(project_id=project_id, project_dir=proj_dir, entrypoint=entrypoint)
            app_info.status = "STARTING"
            app_info.port = port
            app_info.url = f"http://127.0.0.1:{port}"
            app_info.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

            try:
                proc = subprocess.Popen(
                    [sys.executable, entry_path, "--port", str(port)],
                    cwd=proj_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                app_info.process = proc
                app_info.pid = proc.pid
                self._processes[project_id] = app_info

                # Background stdout/stderr reader threads
                def _reader(stream, line_list):
                    try:
                        for line in iter(stream.readline, ""):
                            if line:
                                line_list.append(line.rstrip())
                    except Exception:
                        pass

                threading.Thread(target=_reader, args=(proc.stdout, app_info.stdout_lines), daemon=True).start()
                threading.Thread(target=_reader, args=(proc.stderr, app_info.stderr_lines), daemon=True).start()

            except Exception as e:
                app_info.status = "FAILED"
                app_info.error_message = f"Failed to spawn application process: {e}"
                self._processes[project_id] = app_info
                return app_info.to_dict()

        # Wait briefly and verify health
        start_wait = time.time()
        is_healthy = False
        import urllib.request

        while time.time() - start_wait < timeout:
            if proc.poll() is not None:
                app_info.status = "FAILED"
                err_tail = "\n".join(app_info.stderr_lines[-5:]) if app_info.stderr_lines else "Process exited prematurely"
                app_info.error_message = f"Application crashed immediately: {err_tail}"
                return app_info.to_dict()

            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as resp:
                    if resp.status == 200:
                        is_healthy = True
                        break
            except Exception:
                # Also try root URL
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5) as resp:
                        if resp.status == 200:
                            is_healthy = True
                            break
                except Exception:
                    pass
            time.sleep(0.15)

        if is_healthy or proc.poll() is None:
            app_info.status = "RUNNING"
        else:
            app_info.status = "FAILED"
            app_info.error_message = f"Application failed to respond on port {port} within {timeout}s"

        return app_info.to_dict()

    def get_status(self, project_id: str) -> Dict[str, Any]:
        """Returns the real-time runtime state of the application process."""
        with self._lock:
            if project_id in self._processes:
                return self._processes[project_id].to_dict()

            # If not yet launched in this manager session, check if directory exists
            try:
                proj_dir = self._validate_project_dir(project_id)
                return {
                    "project_id": project_id,
                    "status": "STOPPED",
                    "pid": None,
                    "port": None,
                    "url": None,
                    "entrypoint": "app.py",
                    "runtime_node": "local-m1",
                    "started_at": None,
                    "stopped_at": None,
                    "error_message": None,
                    "stdout_tail": [],
                    "stderr_tail": [],
                }
            except Exception:
                return {
                    "project_id": project_id,
                    "status": "STOPPED",
                    "pid": None,
                    "port": None,
                    "url": None,
                    "entrypoint": "app.py",
                    "runtime_node": "local-m1",
                    "started_at": None,
                    "stopped_at": None,
                    "error_message": "Project not found",
                    "stdout_tail": [],
                    "stderr_tail": [],
                }

    def stop(self, project_id: str, timeout: float = 3.0) -> Dict[str, Any]:
        """
        Terminates the application process cleanly.
        """
        with self._lock:
            if project_id not in self._processes:
                return {"project_id": project_id, "status": "STOPPED", "pid": None}

            app_info = self._processes[project_id]
            app_info.status = "STOPPING"
            proc = app_info.process

            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=1.0)
                except Exception as e:
                    app_info.error_message = f"Error terminating process: {e}"

            app_info.status = "STOPPED"
            app_info.stopped_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return app_info.to_dict()

    def export_archive(self, project_id: str) -> Dict[str, Any]:
        """
        Packages the generated project into a physical .tar.gz delivery artifact in dist/.
        """
        proj_dir = self._validate_project_dir(project_id)
        proj_dist_dir = os.path.join(self.dist_dir, project_id)
        os.makedirs(proj_dist_dir, exist_ok=True)

        archive_filename = f"autoforge-app-{project_id}.tar.gz"
        archive_path = os.path.join(proj_dist_dir, archive_filename)

        with tarfile.open(archive_path, "w:gz") as tar:
            for root, _, files in os.walk(proj_dir):
                for file in files:
                    if file.startswith(".pytest_cache") or file.endswith(".pyc") or "__pycache__" in root:
                        continue
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, proj_dir)
                    tar.add(full_path, arcname=rel_path)

        file_size = os.path.getsize(archive_path)
        return {
            "project_id": project_id,
            "filename": archive_filename,
            "absolute_path": archive_path,
            "size_bytes": file_size,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "download_url": f"/api/projects/{project_id}/download",
        }
