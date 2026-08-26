"""Tests for the connector error taxonomy."""

from __future__ import annotations

import pytest

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

DETERMINISTIC = [
    ConnectorValidationError,
    ConnectorNotFoundError,
    ConnectorConflictError,
    ConnectorAuthenticationError,
    ConnectorAuthorizationError,
    ConnectorUnsupportedError,
    ConnectorOperationFailedError,
]
TRANSIENT = [
    ConnectorUnavailableError,
    ConnectorTimeoutError,
    ConnectorRateLimitError,
    ConnectorTransportError,
]


@pytest.mark.parametrize("exc_type", DETERMINISTIC)
def test_deterministic_failures_are_not_retryable(exc_type):
    exc = exc_type("boom")
    assert isinstance(exc, ConnectorError)
    assert exc.retryable is False


@pytest.mark.parametrize("exc_type", TRANSIENT)
def test_transient_failures_are_retryable(exc_type):
    exc = exc_type("boom")
    assert isinstance(exc, ConnectorError)
    assert exc.retryable is True


def test_categories_are_unique_and_stable():
    all_types = [*DETERMINISTIC, *TRANSIENT]
    categories = [t.category for t in all_types]
    assert len(categories) == len(set(categories))
    for category in categories:
        assert category.startswith("connector.")


def test_details_are_structured_and_exclude_str():
    exc = ConnectorNotFoundError(
        "missing entity", details={"path": "/workspace/app.py"}
    )
    assert "app.py" not in str(exc)
    assert exc.details["path"] == "/workspace/app.py"


def test_summary_is_log_safe_shape():
    exc = ConnectorConflictError("conflict happened", details={"path": "a.txt"})
    summary = exc.summary
    assert set(summary) == {"category", "retryable", "message", "details"}
    assert summary["message"] == "conflict happened"
