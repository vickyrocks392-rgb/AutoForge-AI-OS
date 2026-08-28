"""
Unit tests for CredentialManager and LocalEncryptedStore.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from autoforge_security.credentials import (
    CredentialManager,
    InMemoryCredentialStore,
    LocalEncryptedStore,
)
from autoforge_security.errors import CredentialNotFoundError, CredentialStoreError
from autoforge_security.models import CredentialType, SecretScope
from autoforge_security.secrets import SecretValue


def test_in_memory_credential_manager(credential_manager: CredentialManager) -> None:
    meta = credential_manager.register_credential(
        name="github_token",
        credential_type=CredentialType.BEARER_TOKEN,
        provider="github",
        secret_value="ghp_sampletoken123",
        scope=SecretScope.CONNECTOR,
    )
    assert meta.credential_id is not None
    assert meta.is_revoked is False

    # Retrieve
    ret_meta, ret_sec = credential_manager.get_credential(meta.credential_id)
    assert ret_meta.name == "github_token"
    assert ret_sec.raw_value == "ghp_sampletoken123"

    # Rotate
    rotated_meta = credential_manager.rotate_credential(meta.credential_id, "ghp_newtoken456")
    assert rotated_meta.last_rotated_at is not None
    _, updated_sec = credential_manager.get_credential(meta.credential_id)
    assert updated_sec.raw_value == "ghp_newtoken456"

    # Revoke
    revoked_meta = credential_manager.revoke_credential(meta.credential_id)
    assert revoked_meta.is_revoked is True

    # Retrieving revoked should raise CredentialStoreError
    with pytest.raises(CredentialStoreError):
        credential_manager.get_credential(meta.credential_id)


def test_local_encrypted_store(tmp_path: Path) -> None:
    store_dir = tmp_path / "creds"
    local_store = LocalEncryptedStore(storage_dir=store_dir, master_key="test-secure-master-key")
    mgr = CredentialManager(store=local_store)

    meta = mgr.register_credential(
        name="aws_key",
        credential_type=CredentialType.API_KEY,
        provider="aws",
        secret_value="AKIAIOSFODNN7EXAMPLE",
    )

    # Re-initialize store from disk to verify encryption & persistence round-trip
    reloaded_store = LocalEncryptedStore(storage_dir=store_dir, master_key="test-secure-master-key")
    reloaded_mgr = CredentialManager(store=reloaded_store)

    ret_meta, ret_sec = reloaded_mgr.get_credential(meta.credential_id)
    assert ret_meta.name == "aws_key"
    assert ret_sec.raw_value == "AKIAIOSFODNN7EXAMPLE"

    # Verify that stored file on disk does NOT contain plaintext secret
    raw_disk_content = (store_dir / "credentials_index.json").read_text()
    assert "AKIAIOSFODNN7EXAMPLE" not in raw_disk_content
