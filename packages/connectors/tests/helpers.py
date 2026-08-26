"""Shared fixtures/helpers for the connectors test-suite."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from autoforge_events.base import BaseEvent


class RecordingEventSink:
    """Structural ``ConnectorEventSink`` capturing published events."""

    def __init__(self) -> None:
        self.events: list[BaseEvent] = []

    def publish(self, event: BaseEvent) -> Any:
        self.events.append(event)


def _run(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def make_repository(tmp_path: Path, *, initial_branch: str = "main") -> Path:
    """Create a deterministic local git repository with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "init")
    normalised = _run(repo, "symbolic-ref", "--short", "HEAD").strip()
    if normalised != initial_branch:
        _run(repo, "branch", "-m", initial_branch)
    _run(repo, "config", "user.email", "worker@example.invalid")
    _run(repo, "config", "user.name", "AutoForge Test Worker")
    _run(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    _run(repo, "add", "README.md")
    _run(repo, "commit", "-m", "initial commit")
    return repo
