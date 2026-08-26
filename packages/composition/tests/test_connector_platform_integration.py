"""Composition-root integration tests for the Connector Platform.

Exercises the real dependency-injection surface end-to-end against real
temporary workspaces/repositories, and verifies the canonical event wiring
(Phase 7 pattern) plus boundary invariants (Kernel/Runtime untouched).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from autoforge_composition.connector_wiring import (
    ConnectorPlatformServices,
    build_connector_platform,
)
from autoforge_connectors.errors import ConnectorNotFoundError
from autoforge_events.event_types import EventCategory, EventType

from tests.helpers import RecordingEventSink as CanonicalRecordingSink


@pytest.fixture()
def git_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    subprocess.run(
        ["git", "init"], cwd=root, check=True, capture_output=True
    )
    branch = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if branch != "main":
        subprocess.run(
            ["git", "branch", "-m", "main"], cwd=root, check=True, capture_output=True
        )
    subprocess.run(["git", "config", "user.email", "worker@example.invalid"],
                   cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "AutoForge Worker"],
                   cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"],
                   cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("# demo\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root,
                   check=True, capture_output=True)
    return root


# ---------------------------------------------------------------------------
# Construction & DI
# ---------------------------------------------------------------------------


def test_build_returns_full_bundle_over_git_workspace(git_workspace: Path):
    platform = build_connector_platform(workspace_root=git_workspace)
    assert isinstance(platform, ConnectorPlatformServices)
    assert platform.git is not None
    assert platform.filesystem.root == git_workspace.resolve()
    assert platform.github is not None


def test_workspace_without_repository_keeps_other_connectors(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    platform = build_connector_platform(workspace_root=plain)
    assert platform.git is None
    # Filesystem still fully operational:
    platform.filesystem.write_text("hello.txt", "hi", parents=True)
    assert platform.filesystem.read_text("hello.txt") == "hi"


def test_missing_workspace_root_is_rejected(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        build_connector_platform(workspace_root=tmp_path / "nope")


# ---------------------------------------------------------------------------
# End-to-end engineering-worker flow through injected services only
# ---------------------------------------------------------------------------


def test_worker_flow_write_then_commit_visible_in_history(git_workspace: Path):
    platform = build_connector_platform(
        workspace_root=git_workspace,
        github_transport=_NoNetworkTransport(),
    )
    fs, git = platform.filesystem, platform.git
    written = fs.write_text("src/autoforge_demo.py", 'print("hello")\n')
    git.stage([written])
    sha = git.commit("feat: add demo module")
    history = git.log(limit=2)
    assert history[0].hash == sha
    assert history[0].subject == "feat: add demo module"
    clean = git.status()
    assert clean.staged == () and clean.modified == () and clean.untracked == ()
    observations = [fs.last_operation.summary(), git.last_operation.summary()]
    assert {o["connector"] for o in observations} == {"filesystem", "git"}


class _NoNetworkTransport:
    """Guards that composition never performs network I/O implicitly."""

    def request(self, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("network transport must not be invoked in this test")


# ---------------------------------------------------------------------------
# Canonical event wiring through the platform bundle
# ---------------------------------------------------------------------------


def test_failures_surface_on_canonical_event_bus(git_workspace: Path):
    sink = CanonicalRecordingSink()
    platform = build_connector_platform(
        workspace_root=git_workspace,
        event_sink=sink,
        github_transport=_NoNetworkTransport(),
    )
    with pytest.raises(ConnectorNotFoundError):
        platform.git.checkout("missing-branch-xyz")
    events = [
        e for e in sink.events
        if e.metadata.get("component") == "connectors"
        and e.event_type == EventType.FAILURE_DETECTED
    ]
    assert len(events) == 1
    assert events[0].event_category == EventCategory.FAILURE
    assert events[0].metadata["connector"] == "git"
