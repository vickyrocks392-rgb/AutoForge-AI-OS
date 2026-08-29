"""
Unit tests for PackagingToolchainManager and ProjectSandboxManager.
"""

import os
import tempfile
import pytest
from autoforge_api.toolchain import PackagingToolchainManager, ProjectSandboxManager
from autoforge_api.models import PackagingToolchainStatus


def test_toolchain_discovery_host():
    mgr = PackagingToolchainManager()
    toolchains = mgr.discover_toolchains()
    assert len(toolchains) >= 3
    
    # Check tar
    tar_tool = next((t for t in toolchains if t.tool_name == "tar"), None)
    assert tar_tool is not None
    assert tar_tool.status == PackagingToolchainStatus.AVAILABLE

    # Check PyInstaller discovery
    pyinstaller_tool = next((t for t in toolchains if t.tool_name == "PyInstaller"), None)
    assert pyinstaller_tool is not None

    can_native, reason, tool = mgr.can_package_native_desktop()
    assert isinstance(can_native, bool)
    assert len(reason) > 5


def test_sandbox_creation_and_boundary_validation():
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox_mgr = ProjectSandboxManager(workspace_root=tmpdir)
        sbx = sandbox_mgr.create_sandbox("proj-test-123")
        
        assert os.path.isdir(sbx.root_directory)
        assert os.path.isdir(sbx.source_directory)
        assert os.path.isdir(sbx.build_directory)
        assert os.path.isdir(sbx.dist_directory)
        assert os.path.isdir(sbx.runtime_directory)

        # Valid child path
        valid_path = os.path.join(sbx.source_directory, "main.py")
        assert sandbox_mgr.validate_sandbox_path("proj-test-123", valid_path) is True

        # Invalid path outside sandbox
        fake_apps_path = os.path.join(tmpdir, "apps", "api", "server.py")
        assert sandbox_mgr.validate_sandbox_path("proj-test-123", fake_apps_path) is False
