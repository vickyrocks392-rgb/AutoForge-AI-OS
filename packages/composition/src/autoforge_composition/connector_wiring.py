"""Connector Platform wiring within the composition root.

Phase 8 counterpart of :mod:`autoforge_composition.ai_infrastructure_wiring`.
Constructs the Connector Platform (canonical connector events, sandboxed
workspace filesystem, git binding, GitHub boundary) and exposes it as an
injectable service bundle — WITHOUT forcing Kernel/Runtime/AI Infrastructure
to depend on concrete connector implementations.

Dependency direction (one-way, no cycles):

    autoforge-composition -> autoforge-connectors -> autoforge-events
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autoforge_connectors import (
    GitConnector,
    GitHubConnector,
    SecretValue,
    UrllibGitHubTransport,
    WorkspaceFilesystem,
)
from autoforge_connectors.errors import ConnectorNotFoundError
from autoforge_connectors.events import ConnectorEvents


@dataclass
class ConnectorPlatformServices:
    """Injectable Connector Platform components.

    ``git`` is ``None`` when no repository is discovered at/above the
    workspace root; ``github`` requires a transport (default: stdlib urllib)
    and is usable unauthenticated for public resources.
    """

    events: ConnectorEvents
    filesystem: WorkspaceFilesystem
    git: GitConnector | None
    github: GitHubConnector


def build_connector_platform(
    *,
    workspace_root: Path | str,
    event_sink: object | None = None,
    github_token: SecretValue | None = None,
    github_transport: object | None = None,
    git_binary: str = "git",
    git_default_timeout_seconds: float = 30.0,
) -> ConnectorPlatformServices:
    """Compose the Connector Platform over one workspace.

    Args:
        workspace_root: Confined filesystem root and git-discovery anchor.
        event_sink: Optional canonical sink (satisfied by the Event
            Platform's ``CanonicalEventBus``); failures/degradations are
            published there using the frozen canonical vocabulary.
        github_token: Optional pre-resolved credential from platform
            configuration. Credentials must NOT be read inside this package.
        github_transport: Optional custom transport (tests / proxies); when
            omitted, ``UrllibGitHubTransport`` is used.
        git_binary: Executable override (never a shell string).
        git_default_timeout_seconds: Hard wall-clock budget per git command.
    """
    if not Path(workspace_root).exists():
        raise FileNotFoundError(f"workspace root does not exist: {workspace_root}")

    events = ConnectorEvents(sink=event_sink)
    filesystem = WorkspaceFilesystem(workspace_root, events=events)

    git: GitConnector | None = None
    try:
        git = GitConnector.discover(
            workspace_root,
            binary=git_binary,
            default_timeout_seconds=git_default_timeout_seconds,
            events=events,
        )
    except ConnectorNotFoundError:
        # A non-repository workspace is valid: other connectors remain available.
        git = None

    github = GitHubConnector(
        transport=github_transport or UrllibGitHubTransport(),
        token=github_token,
        events=events,
    )

    return ConnectorPlatformServices(
        events=events,
        filesystem=filesystem,
        git=git,
        github=github,
    )
