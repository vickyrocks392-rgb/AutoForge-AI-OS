"""AutoForge Connector Platform — standardised access to external systems.

Phase 8 shared-platform-service providing uniform, replaceable boundaries for
external systems used by engineering workers:

- :class:`WorkspaceFilesystem` — sandboxed workspace read/write operations
- :class:`GitConnector` — controlled git repository operations
- :class:`GitHubConnector` — GitHub API operations behind a replaceable
  transport with credential isolation

Design documents: ``docs/subsystems/CONNECTOR_PLATFORM_SPECIFICATION.md`` and
``docs/adr/ADR-007-connector-platform.md``.

Boundary note: ``knowledge_platform.connectors`` are knowledge-source
retrieval connectors — a different concern; they are NOT part of the
Connector Platform.
"""

from autoforge_connectors.errors import (
    ConnectorAuthenticationError,
    ConnectorAuthorizationError,
    ConnectorConflictError,
    ConnectorError,
    ConnectorNotFoundError,
    ConnectorOperationFailedError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorTransportError,
    ConnectorUnavailableError,
    ConnectorUnsupportedError,
    ConnectorValidationError,
)
from autoforge_connectors.events import ConnectorEvents
from autoforge_connectors.filesystem import PathInfo, WorkspaceFilesystem
from autoforge_connectors.git import CommitInfo, GitConnector, GitStatus
from autoforge_connectors.github import (
    ContentItem,
    GitHubConnector,
    GitHubResponse,
    GitHubTransport,
    IssueInfo,
    PullRequestInfo,
    RepoSummary,
    UrllibGitHubTransport,
)
from autoforge_connectors.github import GitRef as GitHubGitRef
from autoforge_connectors.interfaces import (
    ConnectorEventSink,
    OperationObservation,
    current_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from autoforge_connectors.security import SecretValue, redact

__version__ = "0.1.0"

__all__ = [
    "CommitInfo",
    "ContentItem",
    "ConnectorAuthenticationError",
    "ConnectorAuthorizationError",
    "ConnectorConflictError",
    "ConnectorError",
    "ConnectorEventSink",
    "ConnectorEvents",
    "ConnectorNotFoundError",
    "ConnectorOperationFailedError",
    "ConnectorRateLimitError",
    "ConnectorTimeoutError",
    "ConnectorTransportError",
    "ConnectorUnavailableError",
    "ConnectorUnsupportedError",
    "ConnectorValidationError",
    "GitHubConnector",
    "GitHubGitRef",
    "GitHubResponse",
    "GitHubTransport",
    "GitConnector",
    "GitStatus",
    "IssueInfo",
    "OperationObservation",
    "PathInfo",
    "PullRequestInfo",
    "RepoSummary",
    "SecretValue",
    "UrllibGitHubTransport",
    "WorkspaceFilesystem",
    "__version__",
    "current_correlation_id",
    "redact",
    "reset_correlation_id",
    "set_correlation_id",
]
