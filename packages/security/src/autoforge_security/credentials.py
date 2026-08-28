"""
Credential Storage & Lifecycle Management for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import abc
import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoforge_security.errors import (
    CredentialNotFoundError,
    CredentialStoreError,
    InsufficientPrivilegesError,
)
from autoforge_security.models import (
    CredentialMetadata,
    CredentialType,
    SecretScope,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import Permissions
from autoforge_security.secrets import SecretValue


class CredentialStore(abc.ABC):
    """Abstract storage adapter for encrypted credentials."""

    @abc.abstractmethod
    def save(self, metadata: CredentialMetadata, secret_value: SecretValue) -> None:
        """Persist credential metadata and secret value."""
        ...

    @abc.abstractmethod
    def retrieve(self, credential_id: str) -> tuple[CredentialMetadata, SecretValue] | None:
        """Retrieve credential by ID."""
        ...

    @abc.abstractmethod
    def delete(self, credential_id: str) -> bool:
        """Delete credential by ID."""
        ...

    @abc.abstractmethod
    def list_all(self) -> list[CredentialMetadata]:
        """List all non-sensitive metadata entries."""
        ...


class InMemoryCredentialStore(CredentialStore):
    """In-memory transient credential store for tests and fast runtime execution."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[CredentialMetadata, SecretValue]] = {}

    def save(self, metadata: CredentialMetadata, secret_value: SecretValue) -> None:
        self._entries[metadata.credential_id] = (metadata, secret_value)

    def retrieve(self, credential_id: str) -> tuple[CredentialMetadata, SecretValue] | None:
        return self._entries.get(credential_id)

    def delete(self, credential_id: str) -> bool:
        return self._entries.pop(credential_id, None) is not None

    def list_all(self) -> list[CredentialMetadata]:
        return [meta for meta, _ in self._entries.values()]


class LocalEncryptedStore(CredentialStore):
    """
    Local-first file-backed encrypted credential store.
    Encrypts stored values using derived local key.
    """

    def __init__(self, storage_dir: str | Path, master_key: str = "autoforge-local-default-key") -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._key = hashlib.sha256(master_key.encode("utf-8")).digest()
        self._index_file = self._dir / "credentials_index.json"
        self._store: dict[str, tuple[CredentialMetadata, SecretValue]] = {}
        self._load()

    def _encrypt(self, raw: str) -> str:
        # Simple XOR keystream for portable local storage without external C-extensions
        raw_bytes = raw.encode("utf-8")
        key_bytes = self._key
        encrypted = bytearray(len(raw_bytes))
        for i, b in enumerate(raw_bytes):
            encrypted[i] = b ^ key_bytes[i % len(key_bytes)]
        return base64.b64encode(encrypted).decode("ascii")

    def _decrypt(self, encoded: str) -> str:
        encrypted = base64.b64decode(encoded.encode("ascii"))
        key_bytes = self._key
        decrypted = bytearray(len(encrypted))
        for i, b in enumerate(encrypted):
            decrypted[i] = b ^ key_bytes[i % len(key_bytes)]
        return decrypted.decode("utf-8")

    def _load(self) -> None:
        if not self._index_file.exists():
            return
        try:
            with open(self._index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                meta = CredentialMetadata.model_validate(item["metadata"])
                raw_val = self._decrypt(item["encrypted_value"])
                self._store[meta.credential_id] = (meta, SecretValue(raw_val))
        except Exception as err:
            raise CredentialStoreError(f"Failed to load credentials index: {err}") from err

    def _persist(self) -> None:
        data = []
        for meta, sec in self._store.values():
            data.append({
                "metadata": meta.model_dump(mode="json"),
                "encrypted_value": self._encrypt(sec.raw_value),
            })
        with open(self._index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def save(self, metadata: CredentialMetadata, secret_value: SecretValue) -> None:
        self._store[metadata.credential_id] = (metadata, secret_value)
        self._persist()

    def retrieve(self, credential_id: str) -> tuple[CredentialMetadata, SecretValue] | None:
        return self._store.get(credential_id)

    def delete(self, credential_id: str) -> bool:
        if credential_id in self._store:
            del self._store[credential_id]
            self._persist()
            return True
        return False

    def list_all(self) -> list[CredentialMetadata]:
        return [meta for meta, _ in self._store.values()]


class CredentialManager:
    """
    Centralized manager for credential lifecycle, storage, rotation, and revocation.
    """

    def __init__(self, store: CredentialStore | None = None) -> None:
        self._store = store or InMemoryCredentialStore()

    def register_credential(
        self,
        name: str,
        credential_type: CredentialType,
        provider: str,
        secret_value: str | SecretValue,
        *,
        scope: SecretScope = SecretScope.SYSTEM,
        credential_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CredentialMetadata:
        """Register a new managed credential."""
        cid = credential_id or f"cred_{provider}_{name}_{secrets.token_hex(4)}"
        meta = CredentialMetadata(
            credential_id=cid,
            name=name,
            credential_type=credential_type,
            provider=provider,
            scope=scope,
            metadata=metadata or {},
        )
        sec_val = secret_value if isinstance(secret_value, SecretValue) else SecretValue(secret_value)
        self._store.save(meta, sec_val)
        return meta

    def get_credential(self, credential_id: str) -> tuple[CredentialMetadata, SecretValue]:
        """Retrieve a credential by ID."""
        result = self._store.retrieve(credential_id)
        if not result:
            raise CredentialNotFoundError(f"Credential '{credential_id}' not found.")
        meta, sec = result
        if meta.is_revoked:
            raise CredentialStoreError(f"Credential '{credential_id}' has been revoked.")
        return meta, sec

    def rotate_credential(self, credential_id: str, new_secret_value: str | SecretValue) -> CredentialMetadata:
        """Rotate the secret value of an existing credential."""
        meta, _ = self.get_credential(credential_id)
        now = datetime.now(timezone.utc)
        updated_meta = CredentialMetadata(
            credential_id=meta.credential_id,
            name=meta.name,
            credential_type=meta.credential_type,
            provider=meta.provider,
            scope=meta.scope,
            created_at=meta.created_at,
            expires_at=meta.expires_at,
            last_rotated_at=now,
            is_revoked=False,
            metadata=meta.metadata,
        )
        sec_val = new_secret_value if isinstance(new_secret_value, SecretValue) else SecretValue(new_secret_value)
        self._store.save(updated_meta, sec_val)
        return updated_meta

    def revoke_credential(self, credential_id: str) -> CredentialMetadata:
        """Revoke a credential."""
        meta, sec = self.get_credential(credential_id)
        revoked_meta = CredentialMetadata(
            credential_id=meta.credential_id,
            name=meta.name,
            credential_type=meta.credential_type,
            provider=meta.provider,
            scope=meta.scope,
            created_at=meta.created_at,
            expires_at=meta.expires_at,
            last_rotated_at=meta.last_rotated_at,
            is_revoked=True,
            metadata=meta.metadata,
        )
        self._store.save(revoked_meta, sec)
        return revoked_meta

    def list_credentials(self) -> list[CredentialMetadata]:
        """List metadata of all stored credentials."""
        return self._store.list_all()
