"""
Security & Governance Platform wiring — Phase 15.

Constructs the Security Platform and bridges it to the composition root.
No business logic lives here — only construction and connection.
"""

from __future__ import annotations

from typing import Any

from autoforge_security.engine import SecurityPlatform
from autoforge_security.identity import IdentityProvider, LocalIdentityProvider
from autoforge_security.models import GovernancePolicy, SandboxPolicy
from autoforge_security.credentials import CredentialStore, InMemoryCredentialStore


def build_security_platform_from_bus(
    *,
    canonical_bus: Any | None = None,
    identity_provider: IdentityProvider | None = None,
    governance_policy: GovernancePolicy | None = None,
    sandbox_policy: SandboxPolicy | None = None,
    credential_store: CredentialStore | None = None,
) -> SecurityPlatform:
    """
    Construct the Security Platform wired to the canonical event bus and local identity provider.
    """
    return SecurityPlatform(
        identity_provider=identity_provider or LocalIdentityProvider(),
        governance_policy=governance_policy,
        sandbox_policy=sandbox_policy,
        credential_store=credential_store or InMemoryCredentialStore(),
        canonical_bus=canonical_bus,
    )
