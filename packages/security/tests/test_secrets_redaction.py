"""
Unit tests for SecretsManager and deep redaction of sensitive credentials.
"""

from __future__ import annotations

import pytest

from autoforge_security.errors import SecretAccessError
from autoforge_security.models import SecretScope, Subject, SubjectType
from autoforge_security.roles import Roles
from autoforge_security.secrets import SecretValue, SecretsManager


def test_secret_value_wrapper_redaction() -> None:
    sec = SecretValue("super_secret_password_12345")
    assert repr(sec) == "SecretValue(***)"
    assert str(sec) == "***"
    assert sec.raw_value == "super_secret_password_12345"
    assert sec.value == "super_secret_password_12345"


def test_secrets_manager_scoped_access(
    secrets_manager: SecretsManager,
    sample_human_admin: Subject,
    sample_worker_subject: Subject,
) -> None:
    secrets_manager.register_secret("system_db_pass", "postgres_master_pass", scope=SecretScope.SYSTEM)
    secrets_manager.register_secret("connector_gh_token", "ghp_1234567890abcdef", scope=SecretScope.CONNECTOR)

    # Admin accesses system secret -> OK
    admin_sec = secrets_manager.get_secret("system_db_pass", sample_human_admin, scope=SecretScope.SYSTEM)
    assert admin_sec.raw_value == "postgres_master_pass"

    # Worker attempts system secret -> Blocked
    with pytest.raises(SecretAccessError):
        secrets_manager.get_secret("system_db_pass", sample_worker_subject, scope=SecretScope.SYSTEM)

    # Worker accesses connector secret -> OK
    worker_sec = secrets_manager.get_secret("connector_gh_token", sample_worker_subject, scope=SecretScope.CONNECTOR)
    assert worker_sec.raw_value == "ghp_1234567890abcdef"


def test_deep_redaction(secrets_manager: SecretsManager) -> None:
    secrets_manager.register_secret("api_token", "secret_token_val_998877")

    # Text redaction
    log_msg = "Error connecting with token secret_token_val_998877 to server."
    redacted_msg = secrets_manager.redact_text(log_msg)
    assert "secret_token_val_998877" not in redacted_msg
    assert "***" in redacted_msg

    # Structure redaction
    payload = {
        "user": "alice",
        "api_key": "raw_exposed_key",
        "nested": {
            "auth_token": "bearer_raw",
            "message": "Connected using secret_token_val_998877 successfully",
        },
        "tags": ["prod", "secret_token_val_998877"],
    }

    redacted_struct = secrets_manager.redact_structure(payload)
    assert redacted_struct["api_key"] == "***"
    assert redacted_struct["nested"]["auth_token"] == "***"
    assert "secret_token_val_998877" not in redacted_struct["nested"]["message"]
    assert "***" in redacted_struct["nested"]["message"]
    assert redacted_struct["tags"][1] == "***"
