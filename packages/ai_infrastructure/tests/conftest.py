"""Pytest fixtures for the AI Infrastructure Platform test suite."""

from __future__ import annotations

import pytest

from autoforge_ai_infrastructure.execution import ExecutorRegistry
from tests.helpers import (
    FakeExecutor,
    RecordingEventSink,
    reference_registry,
    reference_router,
    noop_sleeper,
)


@pytest.fixture
def registry():
    """A Capability Registry populated with the reference catalog."""
    return reference_registry()


@pytest.fixture
def router(registry):
    """A Model Router over the reference registry."""
    return reference_router(registry)


@pytest.fixture
def event_sink():
    """A recording canonical-event sink."""
    return RecordingEventSink()


@pytest.fixture
def executor_registry():
    """An empty executor registry for binding doubles per test."""
    return ExecutorRegistry()


@pytest.fixture
def fake_executor():
    return FakeExecutor()