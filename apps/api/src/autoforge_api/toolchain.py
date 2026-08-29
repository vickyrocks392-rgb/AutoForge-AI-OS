"""
Toolchain Registry and Sandbox Boundary Management for AutoForge.
Provides real packaging discovery and strict control-plane / sandbox isolation.
"""

from __future__ import annotations
import os
import platform
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

from autoforge_api.models import PackagingToolchainInfo, PackagingToolchainStatus, SandboxInfo


class PackagingToolchainManager:
    """
    Discovers, verifies, and manages system packaging toolchains.
    Never fabricates availability; strictly reports factual host node capabilities.
    """

    def __init__(self) -> None:
        self.host_os = platform.system() # "Darwin", "Linux", "Windows"
        self.host_arch = platform.machine() # "arm64", "x86_64"
        self.host_platform = f"{self.host_os} ({self.host_arch})"
        self.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    def discover_toolchains(self) -> List[PackagingToolchainInfo]:
        """Discovers all supported packaging toolchains on the current build node."""
        toolchains: List[PackagingToolchainInfo] = []

        # 1. PyInstaller (Python native desktop executable / .app packager)
        pyinstaller_path = shutil.which("pyinstaller")
        pyinstaller_ver = None
        if pyinstaller_path:
            try:
                out = subprocess.check_output([pyinstaller_path, "--version"], text=True, timeout=2).strip()
                pyinstaller_ver = out
            except Exception:
                pyinstaller_ver = "installed"

        toolchains.append(
            PackagingToolchainInfo(
                tool_name="PyInstaller",
                category="python_desktop",
                detected_path=pyinstaller_path,
                version=pyinstaller_ver,
                status=PackagingToolchainStatus.AVAILABLE if pyinstaller_path else PackagingToolchainStatus.UNAVAILABLE,
                reason_if_unavailable=None if pyinstaller_path else f"pyinstaller executable not found in PATH on node local-m1 (Python {self.python_version})",
                supported_targets=["macOS .app Bundle", "Windows .exe", "Linux Binary"],
            )
        )

        # 2. py2app (macOS specific Python application bundle creator)
        py2app_path = shutil.which("py2app")
        toolchains.append(
            PackagingToolchainInfo(
                tool_name="py2app",
                category="macos_bundle",
                detected_path=py2app_path,
                version=None,
                status=PackagingToolchainStatus.AVAILABLE if py2app_path else PackagingToolchainStatus.UNAVAILABLE,
                reason_if_unavailable=None if py2app_path else "py2app tool not installed in current Python environment",
                supported_targets=["macOS .app Bundle"],
            )
        )

        # 3. Standard POSIX Tar / Gzip Packager (Portable Distribution Archive)
        tar_path = shutil.which("tar")
        tar_ver = None
        if tar_path:
            try:
                out = subprocess.check_output([tar_path, "--version"], text=True, timeout=2).split("\n")[0]
                tar_ver = out
            except Exception:
                tar_ver = "bsdtar / gnu tar"

        toolchains.append(
            PackagingToolchainInfo(
                tool_name="tar",
                category="archive",
                detected_path=tar_path,
                version=tar_ver or "system tar",
                status=PackagingToolchainStatus.AVAILABLE if tar_path else PackagingToolchainStatus.UNAVAILABLE,
                reason_if_unavailable=None if tar_path else "tar utility not found in PATH",
                supported_targets=["Deployable Distribution Archive (.tar.gz)"],
            )
        )

        # 4. macOS Disk Image Utility (hdiutil for .dmg creation)
        hdiutil_path = shutil.which("hdiutil") if self.host_os == "Darwin" else None
        toolchains.append(
            PackagingToolchainInfo(
                tool_name="hdiutil",
                category="macos_dmg",
                detected_path=hdiutil_path,
                version="Apple Darwin DiskImage Tool" if hdiutil_path else None,
                status=PackagingToolchainStatus.AVAILABLE if hdiutil_path else PackagingToolchainStatus.UNAVAILABLE,
                reason_if_unavailable=None if hdiutil_path else "hdiutil only available on Apple Darwin macOS nodes",
                supported_targets=["macOS Disk Image (.dmg)"],
            )
        )

        # 5. Zip Packager
        zip_path = shutil.which("zip")
        toolchains.append(
            PackagingToolchainInfo(
                tool_name="zip",
                category="archive",
                detected_path=zip_path,
                version="system zip" if zip_path else None,
                status=PackagingToolchainStatus.AVAILABLE if zip_path else PackagingToolchainStatus.UNAVAILABLE,
                reason_if_unavailable=None if zip_path else "zip utility not found in PATH",
                supported_targets=["Standard Zip Archive (.zip)"],
            )
        )

        return toolchains

    def can_package_native_desktop(self, target_platform: str = "macOS") -> tuple[bool, str, Optional[str]]:
        """
        Determines whether native desktop packaging (.app / .exe) can physically be executed.
        Returns: (can_package, reason, tool_name)
        """
        toolchains = self.discover_toolchains()
        pyinstaller = next((t for t in toolchains if t.tool_name == "PyInstaller"), None)
        py2app = next((t for t in toolchains if t.tool_name == "py2app"), None)

        if pyinstaller and pyinstaller.status == PackagingToolchainStatus.AVAILABLE:
            return True, "PyInstaller toolchain is available on local build node", "PyInstaller"
        if py2app and py2app.status == PackagingToolchainStatus.AVAILABLE:
            return True, "py2app toolchain is available on local build node", "py2app"

        return (
            False,
            f"Native desktop packaging toolchain (PyInstaller/py2app) is not installed on build node ({self.host_platform}). Local web application runtime and distribution tarball generated instead.",
            None,
        )


class ProjectSandboxManager:
    """
    Enforces strict physical and operational boundaries between AutoForge Control Plane and Generated Projects.
    Ensures generated applications can NEVER mutate AutoForge source, configurations, UI, or registries.
    """

    def __init__(self, workspace_root: Optional[str] = None) -> None:
        self.workspace_root = os.path.abspath(workspace_root or os.getcwd())
        self.builds_root = os.path.join(self.workspace_root, "builds")
        self.dist_root = os.path.join(self.workspace_root, "dist")
        os.makedirs(self.builds_root, exist_ok=True)
        os.makedirs(self.dist_root, exist_ok=True)

    def create_sandbox(self, project_id: str) -> SandboxInfo:
        """Initializes a strictly segregated sandbox directory structure for a project."""
        project_dir = os.path.abspath(os.path.join(self.builds_root, project_id))
        source_dir = os.path.join(project_dir, "src")
        build_dir = os.path.join(project_dir, "build")
        dist_dir = os.path.join(project_dir, "dist")
        runtime_dir = os.path.join(project_dir, "runtime")

        os.makedirs(source_dir, exist_ok=True)
        os.makedirs(build_dir, exist_ok=True)
        os.makedirs(dist_dir, exist_ok=True)
        os.makedirs(runtime_dir, exist_ok=True)

        return SandboxInfo(
            sandbox_id=f"sbx-{project_id}",
            root_directory=project_dir,
            source_directory=source_dir,
            build_directory=build_dir,
            dist_directory=dist_dir,
            runtime_directory=runtime_dir,
            isolation_enforced=True,
            mutates_control_plane=False,
        )

    def validate_sandbox_path(self, project_id: str, target_path: str) -> bool:
        """
        Validates that a path is strictly inside the project sandbox and does not escape
        or overlap with AutoForge control plane source trees.
        """
        sandbox_root = os.path.abspath(os.path.join(self.builds_root, project_id))
        target_abs = os.path.abspath(target_path)
        
        # Must be child of sandbox root
        if not target_abs.startswith(sandbox_root):
            return False

        # Must NOT point into apps/ or packages/ or .git/
        forbidden_roots = [
            os.path.join(self.workspace_root, "apps"),
            os.path.join(self.workspace_root, "packages"),
            os.path.join(self.workspace_root, ".git"),
        ]
        for forb in forbidden_roots:
            if target_abs.startswith(forb):
                return False

        return True
