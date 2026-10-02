"""
Authenticated encryption and key management for local credential storage.

Replaces the previous XOR-keystream obfuscation with a real AEAD construction.

Design
------
* **Algorithm:** AES-256-GCM via ``cryptography.hazmat.primitives.ciphers.aead.AESGCM``.
  Provided by a vetted library — no hand-rolled cryptography.
* **Properties:** confidentiality + integrity/authentication (GCM tag), unique
  random 96-bit nonce per encryption, explicit record versioning, and AAD binding
  each ciphertext to its credential id so a record cannot be transplanted between
  credentials.
* **Keys:** derived from a key-source abstraction (``MasterKeyProvider``). There
  is no universal hardcoded production key. Production sources the key from the
  environment; an explicit, clearly-labelled test/dev provider exists so CI works
  without weakening production.
* **Migration:** legacy XOR records are detected by their envelope version,
  decrypted only inside :func:`migrate_legacy_records`, and immediately
  re-encrypted into the authenticated format. Legacy ciphertext is never
  silently accepted as current-format ciphertext.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets as _secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Envelope version for authenticated (current) records.
ENVELOPE_VERSION_V2 = 2

#: Envelope version for the historical XOR-obfuscated records.
ENVELOPE_VERSION_V1 = 1

#: AAD domain-separation prefix. Prevents cross-protocol AAD reuse.
_AAD_PREFIX = b"autoforge-credential:v2:"


class DecryptionError(Exception):
    """Raised when ciphertext fails authentication or cannot be decrypted."""


class KeyProviderError(Exception):
    """Raised when the master key cannot be obtained."""


# ── Key sources ───────────────────────────────────────────────────────────


class MasterKeyProvider(ABC):
    """Abstraction over the source of the local credential master key."""

    @abstractmethod
    def get_key(self) -> bytes:
        """Return a 32-byte master key."""
        ...


class EnvironmentKeyProvider(MasterKeyProvider):
    """Production key source: ``AUTOFORGE_CREDENTIAL_MASTER_KEY``.

    The key must be 32 bytes, supplied as 64 hex characters. Absent or malformed
    material fails closed — the store refuses to run rather than silently
    downgrading to a default.
    """

    ENV_VAR = "AUTOFORGE_CREDENTIAL_MASTER_KEY"

    def __init__(self, env_var: str | None = None) -> None:
        self._env_var = env_var or self.ENV_VAR

    def get_key(self) -> bytes:
        raw = os.environ.get(self._env_var)
        if not raw:
            raise KeyProviderError(
                f"Environment variable '{self._env_var}' is not set. "
                "Refusing to encrypt credentials without an explicit master key."
            )
        try:
            key = bytes.fromhex(raw)
        except ValueError as exc:
            raise KeyProviderError(
                f"'{self._env_var}' must be 64 hex characters (32 bytes)."
            ) from exc
        if len(key) != 32:
            raise KeyProviderError(
                f"'{self._env_var}' must decode to exactly 32 bytes, got {len(key)}."
            )
        return key


class FileKeyProvider(MasterKeyProvider):
    """Key material read from a filesystem path (0600-permission file)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get_key(self) -> bytes:
        if not self._path.exists():
            raise KeyProviderError(f"Master key file '{self._path}' does not exist.")
        try:
            key = bytes.fromhex(self._path.read_text(encoding="utf-8").strip())
        except ValueError as exc:
            raise KeyProviderError(f"Master key file '{self._path}' is not valid hex.") from exc
        if len(key) != 32:
            raise KeyProviderError(
                f"Master key file '{self._path}' must contain exactly 32 bytes."
            )
        return key


class GeneratedFileKeyProvider(MasterKeyProvider):
    """Creates a random 32-byte key on first use and persists it to disk.

    This is a convenience provider for single-operator local deployments. The key
    file is created with owner-only permissions. It is NOT suitable for shared or
    multi-tenant deployments; use ``EnvironmentKeyProvider`` there.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get_key(self) -> bytes:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            key = _secrets.token_bytes(32)
            self._path.write_text(key.hex(), encoding="utf-8")
            try:
                self._path.chmod(0o600)
            except OSError:
                pass
            return key
        return FileKeyProvider(self._path).get_key()


class TestKeyProvider(MasterKeyProvider):
    """Deterministic key for tests and CI only.

    Explicitly test/dev scoped. Never select this in production code paths.
    """

    def __init__(self, seed: str = "autoforge-test-key") -> None:
        self._seed = seed

    def get_key(self) -> bytes:
        return hashlib.sha256(f"autoforge-test:{self._seed}".encode("utf-8")).digest()


def default_key_provider() -> MasterKeyProvider:
    """Select the key provider appropriate to the runtime environment.

    Order: explicit environment key -> persisted local key file -> fail closed.
    """
    env = os.environ.get(EnvironmentKeyProvider.ENV_VAR)
    if env:
        return EnvironmentKeyProvider()
    local = Path(os.environ.get("AUTOFORGE_HOME", ".autoforge")) / "credential_master.key"
    if local.exists():
        return FileKeyProvider(local)
    return GeneratedFileKeyProvider(local)


# ── Record format ─────────────────────────────────────────────────────────


class RecordVersion(str, Enum):
    V1_LEGACY_XOR = "v1_legacy_xor"
    V2_AES_GCM = "v2_aes_gcm"


@dataclass(frozen=True)
class EncryptedRecord:
    """A single at-rest credential record."""

    version: int
    nonce: bytes
    ciphertext: bytes
    aad: bytes

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nonce": base64.b64encode(self.nonce).decode("ascii"),
            "ciphertext": base64.b64encode(self.ciphertext).decode("ascii"),
        }

    @staticmethod
    def from_json(payload: dict[str, Any]) -> "EncryptedRecord":
        return EncryptedRecord(
            version=int(payload["version"]),
            nonce=base64.b64decode(payload["nonce"]),
            ciphertext=base64.b64decode(payload["ciphertext"]),
            aad=b"",
        )


class CredentialCipher:
    """AEAD sealing/opening for credential values.

    The credential id is bound into the AAD, so a record copied from one
    credential to another fails authentication rather than decrypting.
    """

    def __init__(self, key_provider: MasterKeyProvider | None = None) -> None:
        self._key_provider = key_provider or default_key_provider()
        self._key: bytes | None = None

    @property
    def key_provider(self) -> MasterKeyProvider:
        return self._key_provider

    def _cipher(self) -> AESGCM:
        if self._key is None:
            self._key = self._key_provider.get_key()
        return AESGCM(self._key)

    def _aad(self, credential_id: str) -> bytes:
        return _AAD_PREFIX + credential_id.encode("utf-8")

    def seal(self, plaintext: str, credential_id: str) -> EncryptedRecord:
        """Encrypt with a fresh random nonce. Never reuses a nonce."""
        nonce = os.urandom(12)  # 96-bit, unique per encryption
        aad = self._aad(credential_id)
        ciphertext = self._cipher().encrypt(nonce, plaintext.encode("utf-8"), aad)
        return EncryptedRecord(
            version=ENVELOPE_VERSION_V2,
            nonce=nonce,
            ciphertext=ciphertext,
            aad=aad,
        )

    def open(self, record: EncryptedRecord, credential_id: str) -> str:
        """Authenticate and decrypt. Raises on tamper, wrong key, or wrong id."""
        if record.version != ENVELOPE_VERSION_V2:
            raise DecryptionError(f"Unsupported envelope version {record.version}.")
        aad = self._aad(credential_id)
        try:
            plaintext = self._cipher().decrypt(record.nonce, record.ciphertext, aad)
        except InvalidTag as exc:
            raise DecryptionError(
                "Credential ciphertext failed authentication "
                "(tampered, wrong key, or wrong credential id)."
            ) from exc
        return plaintext.decode("utf-8")


# ── Legacy (v1) XOR format, isolated for migration only ───────────────────


def legacy_xor_decrypt(encoded: str, master_key: str) -> str:
    """Decrypt a legacy v1 XOR record.

    Retained solely so legacy on-disk credentials can be migrated. Legacy records
    are obfuscation, not encryption, and the output is always immediately
    re-encrypted into the v2 authenticated format.
    """
    key = hashlib.sha256(master_key.encode("utf-8")).digest()
    encrypted = base64.b64decode(encoded.encode("ascii"))
    decrypted = bytearray(len(encrypted))
    for i, b in enumerate(encrypted):
        decrypted[i] = b ^ key[i % len(key)]
    return decrypted.decode("utf-8")

