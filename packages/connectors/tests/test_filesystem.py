"""Filesystem connector tests — real workspace, real confinement."""

from __future__ import annotations

from pathlib import Path

import pytest

from autoforge_connectors.errors import (
    ConnectorConflictError,
    ConnectorNotFoundError,
    ConnectorOperationFailedError,
    ConnectorValidationError,
)
from autoforge_connectors.events import ConnectorEvents
from autoforge_connectors.filesystem import WorkspaceFilesystem

from tests.helpers import RecordingEventSink


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_missing_root_is_not_found(tmp_path: Path):
    with pytest.raises(ConnectorNotFoundError):
        WorkspaceFilesystem(tmp_path / "nope")


def test_file_root_is_validation_error(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("x")
    with pytest.raises(ConnectorValidationError):
        WorkspaceFilesystem(target)


def test_root_is_resolved_to_absolute(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    assert fs.root.is_absolute()


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def test_write_then_read_roundtrip(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    written = fs.write_text("src/app.py", "print('hi')\n")
    assert written == "src/app.py"
    assert fs.read_text("src/app.py") == "print('hi')\n"
    assert fs.read_bytes("src/app.py") == b"print('hi')\n"


def test_bytes_roundtrip(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    fs.write_bytes("data/blob.bin", bytes(range(256)))
    assert fs.read_bytes("data/blob.bin") == bytes(range(256))


def test_exists_metadata_and_list_dir(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    fs.write_text("a.txt", "alpha", parents=True)
    fs.write_text("sub/nested/b.txt", "beta", parents=True)
    assert fs.exists("a.txt")
    info = fs.metadata("a.txt")
    assert (info.name, info.is_dir, info.is_symlink) == ("a.txt", False, False)
    assert info.size_bytes == 5
    entries = {e.relative_path: e for e in fs.list_dir("sub")}
    assert set(entries) == {"sub/nested"}  # workspace-relative identity
    assert entries["sub/nested"].is_dir
    nested_files = {e.name for e in fs.list_dir("sub/nested")}
    assert nested_files == {"b.txt"}


def test_read_missing_file_is_not_found(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    with pytest.raises(ConnectorNotFoundError) as excinfo:
        fs.read_text("ghost.txt")
    assert excinfo.value.details["path"] == "ghost.txt"


def test_invalid_encoding_is_validation_error(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    fs.write_bytes("bin.dat", b"\xff\xfe\xfa")
    with pytest.raises(ConnectorValidationError):
        fs.read_text("bin.dat")


# ---------------------------------------------------------------------------
# Write semantics
# ---------------------------------------------------------------------------


def test_overwrite_requires_explicit_flag(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    fs.write_text("f.txt", "one")
    with pytest.raises(ConnectorConflictError):
        fs.write_text("f.txt", "two")
    assert fs.read_text("f.txt") == "one"
    fs.write_text("f.txt", "two", overwrite=True)
    assert fs.read_text("f.txt") == "two"


def test_parents_false_when_directory_absent(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    with pytest.raises(ConnectorNotFoundError):
        fs.write_text("absent/f.txt", "x", parents=False)


def test_mkdir_conflict_and_exist_ok(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    created = fs.mkdir("pkg/subpkg")
    assert created == "pkg/subpkg"
    with pytest.raises(ConnectorConflictError):
        fs.mkdir("pkg/subpkg", exist_ok=False)
    assert fs.mkdir("pkg/subpkg") == "pkg/subpkg"


def test_move_within_workspace(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    fs.write_text("old/notes.md", "content", parents=True)
    moved = fs.move("old/notes.md", "new/dir/renamed.md")
    assert moved == "new/dir/renamed.md"
    assert not fs.exists("old/notes.md")
    assert fs.read_text(moved) == "content"
    # Moving onto an occupied destination without overwrite conflicts.
    with pytest.raises(ConnectorConflictError):
        fs.move("new/dir/renamed.md", "old")


def test_delete_semantics(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    fs.write_text("dir/a.txt", "1", parents=True)
    fs.write_text("dir/b.txt", "2")
    with pytest.raises(ConnectorOperationFailedError):
        fs.delete("dir")  # non-empty without recursive
    fs.delete("dir", recursive=True)
    assert not fs.exists("dir")
    fs.write_text("gone_soon.txt", "bye")
    fs.delete("gone_soon.txt")
    with pytest.raises(ConnectorNotFoundError):
        fs.delete("gone_soon.txt")


# ---------------------------------------------------------------------------
# Security — workspace confinement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("evil", ["../outside.txt", "sub/../../escape.txt"])
def test_traversal_is_rejected(workspace: Path, evil: str):
    fs = WorkspaceFilesystem(workspace)
    with pytest.raises(ConnectorValidationError) as excinfo:
        fs.read_text(evil)
    assert "traversal" in str(excinfo.value) or "escapes" in str(excinfo.value)


def test_absolute_path_is_rejected(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    with pytest.raises(ConnectorValidationError):
        fs.read_text("/etc/passwd")


def test_backslash_segments_cannot_smuggle_dotdot(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    with pytest.raises(ConnectorValidationError):
        fs.read_text("sub\\..\\..\\secrets.txt")


def test_symlink_escape_is_rejected(tmp_path: Path, workspace: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret")
    link = workspace / "portal"
    link.symlink_to(outside, target_is_directory=True)
    fs = WorkspaceFilesystem(workspace)
    with pytest.raises(ConnectorValidationError) as excinfo:
        fs.read_text("portal/secret.txt")
    assert excinfo.value.category == "connector.validation"


def test_write_through_nonexistent_parents_stays_inside(workspace: Path, tmp_path):
    fs = WorkspaceFilesystem(workspace)
    written = fs.write_text("deep/nested/dir/file.txt", "safe", parents=True)
    target = workspace / written
    assert target.exists()
    assert tmp_path not in [target]  # no accidental sibling creation
    assert (workspace / "deep/nested/dir/file.txt").read_text() == "safe"


# ---------------------------------------------------------------------------
# Instrumentation and canonical failure events
# ---------------------------------------------------------------------------


def test_last_operation_records_latency_and_status(workspace: Path):
    fs = WorkspaceFilesystem(workspace)
    fs.write_text("x.txt", "hello")
    obs = fs.last_operation
    assert obs.connector == "filesystem"
    assert obs.operation == "write_text"
    assert obs.status == "ok"
    assert obs.duration_ms >= 0.0
    assert obs.summary()["detail"]["bytes"] == 5


def test_failed_operation_publishes_canonical_failure_event(workspace: Path):
    sink = RecordingEventSink()
    fs = WorkspaceFilesystem(workspace, events=ConnectorEvents(sink=sink))
    with pytest.raises(ConnectorNotFoundError):
        fs.read_text("missing.txt")
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.event_type.value == "failure.detected"
    meta = event.metadata
    assert meta["component"] == "connectors"
    assert meta["connector"] == "filesystem"
    assert meta["error_category"] == "connector.not_found"


def test_successful_operations_emit_no_events(workspace: Path):
    from autoforge_events.event_types import EventType

    sink = RecordingEventSink()
    fs = WorkspaceFilesystem(workspace, events=ConnectorEvents(sink=sink))
    fs.write_text("a.txt", "a")
    fs.read_text("a.txt")
    fs.exists("a.txt")
    assert sink.events == []
    _ = EventType.FAILURE_DETECTED  # vocabulary reference stays importable
