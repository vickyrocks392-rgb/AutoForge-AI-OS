"""
Test fixtures for AutoForge Observability Platform.
"""

from __future__ import annotations
import pytest
from autoforge_event_platform import EventPlatform
from autoforge_observability import ObservabilityPlatform


@pytest.fixture
def event_platform() -> EventPlatform:
    """Create an EventPlatform instance for testing."""
    return EventPlatform()


@pytest.fixture
def observability_platform(event_platform) -> ObservabilityPlatform:
    """Create an ObservabilityPlatform attached to EventPlatform."""
    platform = ObservabilityPlatform(event_platform)
    yield platform
    platform.detach()
