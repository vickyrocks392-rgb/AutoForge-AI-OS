"""
Pytest configuration for apps/api tests.
"""

import pytest
from autoforge_composition.composition_root import build_autoforge_system
from autoforge_observability.engine import ObservabilityPlatform
from autoforge_api.service import AutoForgeApiService


@pytest.fixture
def autoforge_service():
    system = build_autoforge_system()
    obs = ObservabilityPlatform(system.event_platform)
    return AutoForgeApiService(system=system, observability=obs)
