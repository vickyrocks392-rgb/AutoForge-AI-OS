"""Error taxonomy for the Connector Platform.

Connectors normalise third-party/external failures at the boundary — arbitrary
exceptions (OSError variants, git exit codes, HTTP errors, socket faults) NEVER
escape the connector layer. Every public connector operation either succeeds or
raises a :class:`ConnectorError` subclass carrying a stable ``category``
(dotted classification string suitable for events/telemetry) and a ``retryable``
flag consumed by future resilience layers.

Design rules (mirroring the certified AI Infrastructure taxonomy):

- Each subsystem owns its taxonomy; there is NO global platform error hierarchy.
- Structured context lives in ``details`` (dict), never interpolated into
  messages, so messages remain log-safe and single-line.
- Secrets are never placed in messages or details (see ``security.redact``).
"""

from __future__ import annotations

from typing import Any


class ConnectorError(Exception):
    """Base class for every Connector Platform failure."""

    #: Stable dotted classification (e.g. ``"connector.not_found"``).
    category: str = "connector.error"
    #: Whether retrying the same operation may plausibly succeed.
    retryable: bool = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = dict(details or {})

    @property
    def summary(self) -> dict[str, Any]:
        """Structured, log-safe summary (message + details, no traceback)."""
        return {
            "category": self.category,
            "retryable": self.retryable,
            "message": str(self),
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# Deterministic failures (non-retryable)
# ---------------------------------------------------------------------------


class ConnectorValidationError(ConnectorError):
    """Arguments violate the connector contract (bad paths, bad refs...)."""

    category = "connector.validation"


class ConnectorNotFoundError(ConnectorError):
    """A referenced entity (path, repository, ref, issue...) does not exist."""

    category = "connector.not_found"


class ConnectorConflictError(ConnectorError):
    """The target state conflicts with the requested operation."""

    category = "connector.conflict"


class ConnectorAuthenticationError(ConnectorError):
    """Credentials were rejected or are missing (retrying unchanged fails)."""

    category = "connector.authentication"


class ConnectorAuthorizationError(ConnectorError):
    """Credentials are valid but lack permission for the operation."""

    category = "connector.authorization"


class ConnectorUnsupportedError(ConnectorError):
    """The connector does not support the requested operation."""

    category = "connector.unsupported"


class ConnectorOperationFailedError(ConnectorError):
    """The operation failed for an unclassified, deterministic reason."""

    category = "connector.operation_failed"


# ---------------------------------------------------------------------------
# Transient failures (retryable)
# ---------------------------------------------------------------------------


class ConnectorUnavailableError(ConnectorError):
    """The external system cannot currently accept work (binary missing,
    service down, upstream 5xx)."""

    category = "connector.unavailable"
    retryable = True


class ConnectorTimeoutError(ConnectorError):
    """The operation exceeded its time budget."""

    category = "connector.timeout"
    retryable = True


class ConnectorRateLimitError(ConnectorError):
    """The external system throttled the request."""

    category = "connector.rate_limit"
    retryable = True


class ConnectorTransportError(ConnectorError):
    """A network/transport fault occurred (DNS, connection refused, reset)."""

    category = "connector.transport"
    retryable = True
