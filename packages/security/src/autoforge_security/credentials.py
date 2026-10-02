"""
Credential Storage & Lifecycle Management for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import abc
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoforge_security.crypto import (
    CredentialCipher,
    DecryptionError,
    EncryptedRecord,
    MasterKeyProvider,
    legacy_xor_decrypt,
)
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
    """Local-first file-backed credential store using authenticated encryption.

    SECURITY (SHC-03): the previous implementation used a repeating-key XOR
    keystream derived from a hardcoded default master key. That is obfuscation,
    not encryption — it provides no integrity guarantee, and every installation
    shared the same key. This implementation uses AES-256-GCM via the vetted
    ``cryptography`` library, with a fresh random nonce per record and the
    credential id bound as AAD.

    Records written before this change are detected by the absence of a
    ``version`` field and migrated once, on load, into the authenticated format.
    Legacy XOR material is never treated as current-format ciphertext, and is
    only ever decrypted inside :meth:`_migrate_legacy`.
    """

    def __init__(
        self,
        storage_dir: str | Path,
        key_provider: MasterKeyProvider | None = None,
        *,
        legacy_master_key: str = "autoforge-local-default-key",
        allow_legacy_migration: bool = True,
    ) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cipher = CredentialCipher(key_provider)
        self._legacy_master_key = legacy_master_key
        self._allow_legacy_migration = allow_legacy_migration
        self._index_file = self._dir / "credentials_index.json"
        self._store: dict[str, tuple[CredentialMetadata, SecretValue]] = {}
        self._migrated_legacy_count = 0
        self._load()

    @property
    def migrated_legacy_count(self) -> int:
        """Number of legacy XOR records migrated into the authenticated format."""
        return self._migrated_legacy_count

    @property
    def index_file(self) -> Path:
        return self._index_file

    def _load(self) -> None:
        if not self._index_file.exists():
            return
        try:
            with open(self._index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as err:
            raise CredentialStoreError(f"Failed to read credentials index: {err}") from err

        legacy_pending: list[tuple[CredentialMetadata, str]] = []
        for item in data:
            try:
                meta = CredentialMetadata.model_validate(item["metadata"])
            except Exception as err:
                raise CredentialStoreError(
                    f"Malformed credential metadata in index: {err}"
                ) from err

            if "version" in item:
                # Current authenticated format — fail closed on tamper.
                record = EncryptedRecord.from_json(item)
                try:
                    raw_val = self._cipher.open(record, meta.credential_id)
                except DecryptionError as err:
                    raise CredentialStoreError(
                        f"Credential '{meta.credential_id}' failed integrity "
                        f"verification: {err}"
                    ) from err
                self._store[meta.credential_id] = (meta, SecretValue(raw_val))
            else:
                # Legacy v1 envelope. Never decrypted on the read path.
                legacy_pending.append((meta, item["encrypted_value"]))

        if legacy_pending:
            self._migrate_legacy(legacy_pending)
            self._persist()

    def _migrate_legacy(self, legacy_pending: list[tuple[CredentialMetadata, str]]) -> None:
        """Decrypt legacy XOR records once and immediately re-encrypt as AEAD."""
        if not self._allow_legacy_migration:
            raise CredentialStoreError(
                f"Found {len(legacy_pending)} legacy credential record(s) but legacy "
                "migration is disabled. Run the explicit migration path first."
            )
        for meta, encoded in legacy_pending:
            try:
                raw_val = legacy_xor_decrypt(encoded, self._legacy_master_key)
            except Exception as err:
                raise CredentialStoreError(
                    f"Failed to migrate legacy credential '{meta.credential_id}': {err}"
                ) from err
            self._store[meta.credential_id] = (meta, SecretValue(raw_val))
            self._migrated_legacy_count += 1

    def _persist(self) -> None:
        data = []
        for meta, sec in self._store.values():
            record = self._cipher.seal(sec.raw_value, meta.credential_id)
            data.append({"metadata": meta.model_dump(mode="json"), **record.to_json()})
        tmp = self._index_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        # Atomic replace so a crash cannot leave a truncated index.
        os.replace(tmp, self._index_file)
        try:
            self._index_file.chmod(0o600)
        except OSError:
            pass


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
        purpose_binding: Any | None = None,
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
            purpose_binding=purpose_binding,
        )
        sec_val = secret_value if isinstance(secret_value, SecretValue) else SecretValue(secret_value)
        self._store.save(meta, sec_val)
        return meta

    def get_credential(
        self,
        credential_id: str,
        *,
        action_class: Any | None = None,
        project_id: str | None = None,
        destination: str | None = None,
        subject_id: str | None = None,
    ) -> tuple[CredentialMetadata, SecretValue]:
        """Retrieve a credential by ID, enforcing lifecycle and purpose binding.

        SECURITY (SHG-02): expiry is now enforced. ``CredentialMetadata.expires_at``
        was previously recorded but never checked, so an expired credential
        continued to return its secret value indefinitely. Expiry is evaluated on
        every read so revocation-by-expiry is immediate and cannot be bypassed by
        holding a previously resolved reference.

        SECURITY (SHC-04): when the credential carries a
        ``purpose_binding``, the requested use must satisfy it. Supplying
        ``action_class`` / ``project_id`` / ``destination`` / ``subject_id``
        activates the binding check; a purpose-bound credential requested without
        those facts is refused rather than allowed by default.
        """
        result = self._store.retrieve(credential_id)
        if not result:
            raise CredentialNotFoundError(f"Credential '{credential_id}' not found.")
        meta, sec = result
        if meta.is_revoked:
            raise CredentialStoreError(f"Credential '{credential_id}' has been revoked.")
        if meta.expires_at is not None:
            expires_at = meta.expires_at
            # Normalize naive datetimes to UTC so comparison is always total.
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expires_at:
                raise CredentialStoreError(
                    f"Credential '{credential_id}' expired at {meta.expires_at.isoformat()}."
                )

        binding = getattr(meta, "purpose_binding", None)
        if binding is not None:
            if action_class is None:
                raise CredentialStoreError(
                    f"Credential '{credential_id}' is purpose-bound to "
                    f"'{binding.purpose}'; an action_class must be supplied to authorize use."
                )
            ok, reason = binding.permits(
                action_class=action_class,
                project_id=project_id,
                destination=destination,
                subject_id=subject_id,
            )
            if not ok:
                raise CredentialStoreError(
                    f"Credential '{credential_id}' purpose binding violated: {reason}"
                )
        return meta, sec

    def _load_enforcing_lifecycle(
        self, credential_id: str
    ) -> tuple[CredentialMetadata, SecretValue]:
        """Load a credential applying revocation + expiry but NOT purpose binding.

        Purpose binding governs *use* of a secret. Rotation and revocation are
        lifecycle operations that must keep working for a bound credential --
        otherwise a bound credential could never be rotated or revoked, which
        would be a security regression in the opposite direction.
        """
        result = self._store.retrieve(credential_id)
        if not result:
            raise CredentialNotFoundError(f"Credential '{credential_id}' not found.")
        meta, sec = result
        if meta.is_revoked:
            raise CredentialStoreError(f"Credential '{credential_id}' has been revoked.")
        if meta.expires_at is not None:
            expires_at = meta.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expires_at:
                raise CredentialStoreError(
                    f"Credential '{credential_id}' expired at {meta.expires_at.isoformat()}."
                )
        return meta, sec

    def rotate_credential(self, credential_id: str, new_secret_value: str | SecretValue) -> CredentialMetadata:
        """Rotate the secret value of an existing credential."""
        meta, _ = self._load_enforcing_lifecycle(credential_id)
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
            purpose_binding=meta.purpose_binding,
        )
        sec_val = new_secret_value if isinstance(new_secret_value, SecretValue) else SecretValue(new_secret_value)
        self._store.save(updated_meta, sec_val)
        return updated_meta

    def revoke_credential(self, credential_id: str) -> CredentialMetadata:
        """Revoke a credential."""
        meta, sec = self._load_enforcing_lifecycle(credential_id)
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
            purpose_binding=meta.purpose_binding,
        )
        self._store.save(revoked_meta, sec)
        return revoked_meta

    def list_credentials(self) -> list[CredentialMetadata]:
        """List metadata of all stored credentials."""
        return self._store.list_all()
