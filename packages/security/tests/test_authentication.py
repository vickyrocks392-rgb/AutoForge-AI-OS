"""
Unit tests for AuthenticationService and IdentityProvider.
"""

from __future__ import annotations

import pytest

from autoforge_security.authentication import AuthenticationService
from autoforge_security.errors import IdentityNotFoundError
from autoforge_security.identity import LocalIdentityProvider
from autoforge_security.models import Subject, SubjectType
from autoforge_security.roles import Roles


def test_default_identities(identity_provider: LocalIdentityProvider) -> None:
    admin = identity_provider.get_subject("subject_admin_root")
    assert admin is not None
    assert admin.is_human
    assert Roles.ADMINISTRATOR in admin.roles

    anon = identity_provider.get_subject("subject_anonymous")
    assert anon is not None
    assert anon.subject_type == SubjectType.ANONYMOUS


def test_password_authentication_flow(
    auth_service: AuthenticationService,
    identity_provider: LocalIdentityProvider,
) -> None:
    identity_provider.create_human_user(
        username="carol",
        display_name="Carol Dev",
        roles={Roles.ENGINEER},
        password="securePassword123!",
    )

    # Correct credentials
    res = auth_service.authenticate_password("user_carol", "securePassword123!")
    assert res.authenticated is True
    assert res.subject is not None
    assert res.subject.subject_id == "user_carol"
    assert res.token is not None

    # Verify session token
    tok_res = auth_service.authenticate_token(res.token)
    assert tok_res.authenticated is True
    assert tok_res.subject.subject_id == "user_carol"

    # Wrong password
    wrong_res = auth_service.authenticate_password("user_carol", "wrongpass")
    assert wrong_res.authenticated is False
    assert "Invalid credentials" in (wrong_res.error_message or "")


def test_api_key_authentication(
    auth_service: AuthenticationService,
    identity_provider: LocalIdentityProvider,
) -> None:
    user = identity_provider.create_human_user(
        username="dave",
        display_name="Dave Ops",
        roles={Roles.OPERATOR},
    )
    api_key = identity_provider.issue_api_key(user.subject_id)
    assert api_key.startswith("afg_")

    res = auth_service.authenticate_api_key(api_key)
    assert res.authenticated is True
    assert res.subject is not None
    assert res.subject.subject_id == "user_dave"

    # Invalid key
    bad_res = auth_service.authenticate_api_key("afg_invalid_key_xyz")
    assert bad_res.authenticated is False


def test_token_revocation(
    auth_service: AuthenticationService,
    sample_human_engineer: Subject,
) -> None:
    res = auth_service.authenticate_password(sample_human_engineer.subject_id, "correct-horse-battery-staple")
    assert res.token is not None

    # Active token verification
    assert auth_service.authenticate_token(res.token).authenticated is True

    # Revoke session
    revoked = auth_service.revoke_session(res.token)
    assert revoked is True

    # Verification should now fail
    verify_res = auth_service.authenticate_token(res.token)
    assert verify_res.authenticated is False
    assert "revoked" in (verify_res.error_message or "")


def test_brute_force_lockout(
    auth_service: AuthenticationService,
    identity_provider: LocalIdentityProvider,
) -> None:
    identity_provider.create_human_user(
        username="eve",
        display_name="Eve",
        roles={Roles.ENGINEER},
        password="secretPassword",
    )

    # 5 failed attempts
    for _ in range(5):
        auth_service.authenticate_password("user_eve", "bad_pass")

    # 6th attempt should be locked out
    locked_res = auth_service.authenticate_password("user_eve", "secretPassword")
    assert locked_res.authenticated is False
    assert "temporarily locked" in (locked_res.error_message or "")
