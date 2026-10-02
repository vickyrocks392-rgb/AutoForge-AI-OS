"""
Pytest configuration for apps/api tests.
"""

import os

import pytest

# SHC-02: the existing Phase 16 behavioral suite drives the API without tokens.
# Authentication is therefore explicitly disabled *for the test run only* — an
# opt-in via environment, never a production default. Dedicated auth tests in
# test_api_security_auth.py re-enable enforcement and assert the negative cases.
os.environ.setdefault("AUTOFORGE_API_AUTH_DISABLED", "1")

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_observability.engine import ObservabilityPlatform
from autoforge_api.service import AutoForgeApiService


@pytest.fixture
def autoforge_service():
    system = build_autoforge_system()
    obs = ObservabilityPlatform(system.event_platform)
    return AutoForgeApiService(system=system, observability=obs)
