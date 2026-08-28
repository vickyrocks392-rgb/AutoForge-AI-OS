"""
Test fixtures for autoforge-security test suite.
"""

from __future__ import annotations

import tempfile
import pytest
from pathlib import Path

from autoforge_event_platform import EventPlatform
from autoforge_event_platform.adapter import CanonicalEventBus
from autoforge_security.authentication import AuthenticationService
from autoforge_security.authorization import AuthorizationEngine
from autoforge_security.credentials import CredentialManager, InMemoryCredentialStore, LocalEncryptedStore
from autoforge_security.engine import SecurityPlatform
from autoforge_security.governance import GovernancePolicyEngine
from autoforge_security.hitl import HITLManager
from autoforge_security.identity import LocalIdentityProvider
from autoforge_security.models import (
    GovernancePolicy,
    SandboxPolicy,
    Subject,
    SubjectType,
)
from autoforge_security.roles import Roles
from autoforge_security.sandbox import SandboxPolicyEngine
from autoforge_security.secrets import SecretsManager


@pytest.fixture
def identity_provider() -> LocalIdentityProvider:
    return LocalIdentityProvider()


@pytest.fixture
def auth_service(identity_provider: LocalIdentityProvider) -> AuthenticationService:
    return AuthenticationService(identity_provider=identity_provider)


@pytest.fixture
def authz_engine() -> AuthorizationEngine:
    return AuthorizationEngine()


@pytest.fixture
def governance_engine() -> GovernancePolicyEngine:
    return GovernancePolicyEngine()


@pytest.fixture
def hitl_manager(governance_engine: GovernancePolicyEngine) -> HITLManager:
    return HITLManager(governance_engine=governance_engine)


@pytest.fixture
def secrets_manager() -> SecretsManager:
    return SecretsManager()


@pytest.fixture
def credential_manager() -> CredentialManager:
    return CredentialManager(store=InMemoryCredentialStore())


@pytest.fixture
def sandbox_engine() -> SandboxPolicyEngine:
    return SandboxPolicyEngine()


@pytest.fixture
def event_bus() -> CanonicalEventBus:
    platform = EventPlatform()
    return CanonicalEventBus(platform.event_bus)


@pytest.fixture
def security_platform(event_bus: CanonicalEventBus) -> SecurityPlatform:
    return SecurityPlatform(canonical_bus=event_bus)


@pytest.fixture
def sample_human_admin(identity_provider: LocalIdentityProvider) -> Subject:
    return identity_provider.get_subject("subject_admin_root")


@pytest.fixture
def sample_human_engineer(identity_provider: LocalIdentityProvider) -> Subject:
    return identity_provider.create_human_user(
        username="alice",
        display_name="Alice Engineer",
        roles={Roles.ENGINEER},
        password="correct-horse-battery-staple",
    )


@pytest.fixture
def sample_human_reviewer(identity_provider: LocalIdentityProvider) -> Subject:
    return identity_provider.create_human_user(
        username="bob_rev",
        display_name="Bob Reviewer",
        roles={Roles.REVIEWER},
        password="reviewer-secret-pass",
    )


@pytest.fixture
def sample_worker_subject(identity_provider: LocalIdentityProvider) -> Subject:
    return identity_provider.create_worker_identity(
        worker_id="w_backend_001",
        worker_type="backend_engineer",
        roles={Roles.ENGINEER},
    )


@pytest.fixture
def sample_legacy_archaeologist(identity_provider: LocalIdentityProvider) -> Subject:
    return identity_provider.create_worker_identity(
        worker_id="w_archaeologist_001",
        worker_type="legacy_codebase_archaeologist",
        roles={Roles.RESEARCHER},
    )


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "main.py").write_text("print('hello world')")
    return ws
