"""Git connector tests — real temporary repositories, real subprocesses."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from autoforge_connectors.errors import (
    ConnectorAuthenticationError,
    ConnectorAuthorizationError,
    ConnectorConflictError,
    ConnectorNotFoundError,
    ConnectorOperationFailedError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
    ConnectorValidationError,
)
from autoforge_connectors.events import ConnectorEvents
from autoforge_connectors.git import GitConnector

from tests.helpers import RecordingEventSink, make_repository


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return make_repository(tmp_path)


@pytest.fixture()
def connector(repo: Path) -> GitConnector:
    return GitConnector(repo)


def _branch_list(connector: GitConnector) -> set[str]:
    raw = connector._run(["for-each-ref", "--format=%(refname:short)", "refs/heads"])
    return set(raw.stdout.split())


# ---------------------------------------------------------------------------
# Discovery and binding
# ---------------------------------------------------------------------------


def test_discover_finds_repository_from_subdirectory(repo: Path):
    nested = repo / "pkg" / "deep"
    nested.mkdir(parents=True)
    found = GitConnector.discover(nested)
    assert found.repository == repo.resolve()


def test_discover_without_repository_raises(tmp_path: Path):
    empty = tmp_path / "plain"
    empty.mkdir()
    with pytest.raises(ConnectorNotFoundError):
        GitConnector.discover(empty)


def test_constructor_rejects_missing_or_file_paths(tmp_path: Path):
    with pytest.raises(ConnectorNotFoundError):
        GitConnector(tmp_path / "absent")
    target_file = tmp_path / "file"
    target_file.write_text("x")
    with pytest.raises(ConnectorValidationError):
        GitConnector(target_file)


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def test_is_repository_and_current_branch(connector: GitConnector):
    assert connector.is_repository() is True
    assert connector.current_branch() == "main"


def test_clean_status_is_empty(connector: GitConnector):
    status = connector.status()
    assert status.branch == "main"
    assert status.staged == ()
    assert status.modified == ()
    assert status.untracked == ()
    assert status.conflicts == ()


def test_status_reflects_untracked_and_staged_changes(repo: Path, connector):
    (repo / "notes.txt").write_text("draft")
    dirty = connector.status()
    assert dirty.untracked == ("notes.txt",)
    connector.stage(["notes.txt"])
    after_stage = connector.status()
    assert "notes.txt" in after_stage.staged
    assert after_stage.modified == ()


def test_head_commit_and_log_parsing(connector: GitConnector):
    head = connector.head_commit()
    assert head.subject == "initial commit"
    assert len(head.hash) == 40
    assert head.author_email == "worker@example.invalid"
    assert connector.log(limit=10) == [head]


def test_log_limit_bounds_are_validated(connector: GitConnector):
    with pytest.raises(ConnectorValidationError):
        connector.log(limit=0)
    with pytest.raises(ConnectorValidationError):
        connector.log(limit=1001)


def test_empty_repository_has_no_history(tmp_path: Path):
    empty_repo = tmp_path / "unborn"
    empty_repo.mkdir()
    subprocess.run(
        ["git", "init"], cwd=empty_repo, check=True, capture_output=True
    )
    connector = GitConnector(empty_repo)
    assert connector.head_commit() is None
    assert connector.log() == []


def test_diff_unstaged_output(repo: Path, connector: GitConnector):
    (repo / "README.md").write_text("# demo\n# changed line\n")
    diff_text = connector.diff()
    assert "changed line" in diff_text
    assert "+# changed line" in diff_text


def test_detached_head_returns_none_branch(repo: Path, connector: GitConnector):
    sha = connector.commit(message="marker", allow_empty=True)
    connector.checkout(sha)
    assert connector.current_branch() is None
    connector.checkout("main")


# ---------------------------------------------------------------------------
# Mutation flows (real repository lifecycle)
# ---------------------------------------------------------------------------


def test_stage_commit_cycle_produces_hash_and_history(repo: Path, connector):
    (repo / "app.py").write_text("print('v1')\n")
    assert connector.stage(["app.py"]) == 1
    sha1 = connector.commit("implement app v1")
    assert len(sha1) == 40
    (repo / "app.py").write_text("print('v2')\n")
    sha2 = connector.commit("fix app", stage_all=True)
    history = connector.log(limit=5)
    assert [c.subject for c in history] == [
        "fix app",
        "implement app v1",
        "initial commit",
    ]
    assert {c.hash for c in history} >= {sha1, sha2}
    clean = connector.status()
    assert clean.modified == () and clean.staged == ()


def test_commit_requires_nonempty_message(connector: GitConnector):
    with pytest.raises(ConnectorValidationError):
        connector.commit("   ")


def test_stage_requires_paths(connector: GitConnector):
    with pytest.raises(ConnectorValidationError):
        connector.stage([])


def test_branch_create_checkout_delete_lifecycle(connector: GitConnector):
    assert connector.create_branch("feature/autoforge") == "feature/autoforge"
    assert "feature/autoforge" in _branch_list(connector)
    connector.checkout("feature/autoforge")
    assert connector.current_branch() == "feature/autoforge"
    connector.checkout("main")
    connector.delete_branch("feature/autoforge")
    assert "feature/autoforge" not in _branch_list(connector)


def test_duplicate_branch_conflicts(connector: GitConnector):
    connector.create_branch("dup")
    with pytest.raises(ConnectorConflictError):
        connector.create_branch("dup")


def test_checkout_missing_revision_not_found(connector: GitConnector):
    with pytest.raises(ConnectorNotFoundError):
        connector.checkout("deadbeef" * 5)


def test_reset_hard_restores_tracked_tree(repo: Path, connector: GitConnector):
    (repo / "tracked.txt").write_text("version one\n")
    connector.stage(["tracked.txt"])
    connector.commit("track file", allow_empty=True)
    (repo / "tracked.txt").write_text("corrupted working copy\n")
    assert "tracked.txt" in connector.status().modified
    connector.reset("hard")
    status = connector.status()
    assert status.modified == ()
    assert (repo / "tracked.txt").read_text() == "version one\n"


# ---------------------------------------------------------------------------
# Security and reliability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_ref", ["-rf", "--exec=evil", "a..b", ".lock", ""]
)
def test_dangerous_refs_rejected_before_subprocess(connector: GitConnector, bad_ref):
    with pytest.raises(ConnectorValidationError):
        connector.checkout(bad_ref)


def test_pathspec_option_injection_blocked(connector: GitConnector):
    with pytest.raises(ConnectorValidationError):
        connector.stage(["--all"])


def test_timeout_is_classified(repo: Path):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nsleep 5\n")
    hook.chmod(0o755)
    (repo / "staged.txt").write_text("x")
    slow = GitConnector(repo, default_timeout_seconds=0.5)
    slow.stage(["staged.txt"])
    started = time.perf_counter()
    with pytest.raises(ConnectorTimeoutError):
        slow.commit("should never finish")
    assert time.perf_counter() - started < 3


def test_missing_binary_maps_to_unavailable(tmp_path: Path):
    sink = RecordingEventSink()
    ghost = tmp_path / "not-a-repo-but-dir"
    ghost.mkdir()
    subprocess.run(["git", "init"], cwd=ghost, check=True, capture_output=True)
    connector = GitConnector(
        ghost,
        binary="definitely-not-a-real-git-binary",
        events=ConnectorEvents(sink=sink),
    )
    with pytest.raises(ConnectorUnavailableError):
        connector.is_repository()
    assert len(sink.events) == 1
    degraded = sink.events[0]
    assert degraded.event_type.value == "service.degraded"


def test_failures_publish_canonical_failure_events(repo: Path):
    sink = RecordingEventSink()
    connector = GitConnector(repo, events=ConnectorEvents(sink=sink))
    with pytest.raises(ConnectorNotFoundError):
        connector.checkout("does-not-exist-here")
    failed = [e for e in sink.events if e.event_type.value == "failure.detected"]
    assert len(failed) == 1
    meta = failed[0].metadata
    assert meta["component"] == "connectors"
    assert meta["connector"] == "git"
    assert meta["operation"] == "checkout"
    assert meta["error_category"] == "connector.not_found"


class _FakeCompletion:
    """Minimal stand-in carrying only what the classifier consumes."""

    def __init__(self, stderr: str, returncode: int = 128):
        self.stderr = stderr
        self.returncode = returncode


@pytest.mark.parametrize(
    ("stderr", "expected_type"),
    [
        (
            "fatal: Authentication failed for 'https://example.invalid/repo.git'",
            ConnectorAuthenticationError,
        ),
        ("error: Permission denied to update branch 'main'.", ConnectorAuthorizationError),
        (
            "error: pathspec 'ghost.py' did not match any file(s) known to git",
            ConnectorNotFoundError,
        ),
        (
            "error: Your local changes to the following files would be overwritten by checkout:",
            ConnectorConflictError,
        ),
        ("usage: git [--version] [<command>]", ConnectorValidationError),
    ],
)
def test_stderr_classification_matrix(stderr: str, expected_type):
    """Deterministic stderr vocabulary mapping (git drives the same paths in
    the integration tests above)."""
    with pytest.raises(expected_type):
        GitConnector._raise_for_failure("checkout", _FakeCompletion(stderr))


def test_unclassified_stderr_becomes_operation_failed():
    with pytest.raises(ConnectorOperationFailedError) as excinfo:
        GitConnector._raise_for_failure(
            "pack-objects", _FakeCompletion("fatal: exploded mysteriously", 137)
        )
    assert excinfo.value.details["exit_code"] == 137
