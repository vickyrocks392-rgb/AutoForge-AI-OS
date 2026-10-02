"""
Adversarial tests for the SHC-03/04/05/06 controls:

* SHC-03 — authenticated encryption (AEAD), key management, legacy migration
* SHC-04 — credential purpose binding
* SHC-05 — egress destination control (SSRF hardening)
* SHC-06 — egress content control (data-loss prevention)
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoforge_security.ai_guardrails import ActionClass
from autoforge_security.credentials import (
    CredentialManager,
    InMemoryCredentialStore,
    LocalEncryptedStore,
)
from autoforge_security.crypto import (
    CredentialCipher,
    DecryptionError,
    EnvironmentKeyProvider,
    FileKeyProvider,
    GeneratedFileKeyProvider,
    KeyProviderError,
    TestKeyProvider,
    legacy_xor_decrypt,
)
from autoforge_security.egress import (
    EgressDecision,
    EgressPolicy,
    inspect_payload,
    validate_egress_url,
)
from autoforge_security.errors import CredentialStoreError
from autoforge_security.models import (
    CredentialMetadata,
    CredentialPurposeBinding,
    CredentialType,
)
from autoforge_security.secrets import SecretValue


def _meta(cid: str = "c1") -> CredentialMetadata:
    return CredentialMetadata(
        credential_id=cid, name="n", credential_type=CredentialType.API_KEY, provider="p"
    )


# ═══ SHC-03 — Authenticated encryption ═══════════════════════════════════


def test_new_records_use_versioned_aead_envelope(tmp_path: Path) -> None:
    store = LocalEncryptedStore(tmp_path, TestKeyProvider("k"))
    store.save(_meta(), SecretValue("super-secret-value"))
    text = store.index_file.read_text()
    assert '"version": 2' in text
    assert "super-secret-value" not in text


def test_tampered_ciphertext_is_detected(tmp_path: Path) -> None:
    store = LocalEncryptedStore(tmp_path, TestKeyProvider("k"))
    store.save(_meta(), SecretValue("v"))
    data = json.loads(store.index_file.read_text())
    data[0]["ciphertext"] = data[0]["ciphertext"][:-6] + "AAAAAA"
    store.index_file.write_text(json.dumps(data))
    with pytest.raises(CredentialStoreError) as exc:
        LocalEncryptedStore(tmp_path, TestKeyProvider("k"))
    assert "integrity" in str(exc.value).lower()


def test_wrong_key_cannot_decrypt(tmp_path: Path) -> None:
    LocalEncryptedStore(tmp_path, TestKeyProvider("k1")).save(_meta(), SecretValue("v"))
    with pytest.raises(CredentialStoreError):
        LocalEncryptedStore(tmp_path, TestKeyProvider("k2"))



# ── Legacy migration ─────────────────────────────────────────────────────


def _write_legacy(dir_: Path, value: str) -> None:
    key = hashlib.sha256(b"autoforge-local-default-key").digest()
    raw = value.encode()
    blob = base64.b64encode(bytes(raw[i] ^ key[i % len(key)] for i in range(len(raw)))).decode()
    (dir_ / "credentials_index.json").write_text(
        json.dumps([{"metadata": _meta().model_dump(mode="json"), "encrypted_value": blob}])
    )


def test_legacy_record_migrates_to_aead(tmp_path: Path) -> None:
    _write_legacy(tmp_path, "legacy-secret")
    store = LocalEncryptedStore(tmp_path, TestKeyProvider("k"))
    assert store.migrated_legacy_count == 1
    assert store.retrieve("c1")[1].raw_value == "legacy-secret"
    text = store.index_file.read_text()
    assert '"version": 2' in text
    assert "encrypted_value" not in text
    assert "legacy-secret" not in text


def test_legacy_migration_can_be_disabled(tmp_path: Path) -> None:
    _write_legacy(tmp_path, "legacy-secret")
    with pytest.raises(CredentialStoreError) as exc:
        LocalEncryptedStore(tmp_path, TestKeyProvider("k"), allow_legacy_migration=False)
    assert "legacy" in str(exc.value).lower()


def test_migrated_record_is_readable_after_restart(tmp_path: Path) -> None:
    _write_legacy(tmp_path, "legacy-secret")
    LocalEncryptedStore(tmp_path, TestKeyProvider("k"))
    reloaded = LocalEncryptedStore(tmp_path, TestKeyProvider("k"))
    assert reloaded.migrated_legacy_count == 0, "migration must not repeat"
    assert reloaded.retrieve("c1")[1].raw_value == "legacy-secret"


def test_legacy_decryptor_matches_legacy_xor() -> None:
    key = hashlib.sha256(b"autoforge-local-default-key").digest()
    raw = b"hello-legacy"
    blob = base64.b64encode(bytes(raw[i] ^ key[i % len(key)] for i in range(len(raw)))).decode()
    assert legacy_xor_decrypt(blob, "autoforge-local-default-key") == "hello-legacy"


# ── Key providers ────────────────────────────────────────────────────────


def test_environment_key_provider_requires_material(monkeypatch) -> None:
    monkeypatch.delenv("AUTOFORGE_CREDENTIAL_MASTER_KEY", raising=False)
    with pytest.raises(KeyProviderError):
        EnvironmentKeyProvider().get_key()


def test_environment_key_provider_rejects_wrong_length(monkeypatch) -> None:
    monkeypatch.setenv("AUTOFORGE_CREDENTIAL_MASTER_KEY", "abcd")
    with pytest.raises(KeyProviderError):
        EnvironmentKeyProvider().get_key()


def test_environment_key_provider_accepts_valid_key(monkeypatch) -> None:
    monkeypatch.setenv("AUTOFORGE_CREDENTIAL_MASTER_KEY", "ab" * 32)
    assert len(EnvironmentKeyProvider().get_key()) == 32


def test_file_key_provider_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(KeyProviderError):
        FileKeyProvider(tmp_path / "absent.key").get_key()


def test_generated_key_provider_is_stable_and_private(tmp_path: Path) -> None:
    key_file = tmp_path / "master.key"
    provider = GeneratedFileKeyProvider(key_file)
    first = provider.get_key()
    assert provider.get_key() == first
    assert key_file.stat().st_mode & 0o077 == 0


# ═══ SHC-04 — Credential purpose binding ════════════════════════════════


def _bound_manager(**kw) -> tuple[CredentialManager, str]:
    mgr = CredentialManager(store=InMemoryCredentialStore())
    meta = mgr.register_credential(
        name="gh",
        credential_type=CredentialType.BEARER_TOKEN,
        provider="github",
        secret_value="gh-token",
        purpose_binding=CredentialPurposeBinding(purpose="github_read", **kw),
    )
    return mgr, meta.credential_id


def test_purpose_binding_permits_declared_use() -> None:
    mgr, cid = _bound_manager(
        project_id="p1", allowed_action_classes=frozenset({ActionClass.READ})
    )
    _, sec = mgr.get_credential(cid, action_class=ActionClass.READ, project_id="p1")
    assert sec.raw_value == "gh-token"


def test_purpose_binding_blocks_cross_project_use() -> None:
    mgr, cid = _bound_manager(project_id="p1")
    with pytest.raises(CredentialStoreError) as exc:
        mgr.get_credential(cid, action_class=ActionClass.READ, project_id="p2")
    assert "project" in str(exc.value).lower()


def test_purpose_binding_blocks_cross_purpose_use() -> None:
    """A GitHub-read credential must not authorize an arbitrary HTTP write."""
    mgr, cid = _bound_manager(allowed_action_classes=frozenset({ActionClass.READ}))
    with pytest.raises(CredentialStoreError):
        mgr.get_credential(cid, action_class=ActionClass.NETWORK)


def test_purpose_binding_blocks_unlisted_destination() -> None:
    mgr, cid = _bound_manager(allowed_destinations=frozenset({"api.github.com"}))
    mgr.get_credential(cid, action_class=ActionClass.NETWORK, destination="api.github.com")
    with pytest.raises(CredentialStoreError):
        mgr.get_credential(
            cid, action_class=ActionClass.NETWORK, destination="evil.example.com"
        )


def test_purpose_binding_requires_action_class() -> None:
    """A bound credential requested without use facts fails closed."""
    mgr, cid = _bound_manager(project_id="p1")
    with pytest.raises(CredentialStoreError) as exc:
        mgr.get_credential(cid)
    assert "action_class" in str(exc.value)


def test_purpose_binding_expires() -> None:
    mgr, cid = _bound_manager(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    with pytest.raises(CredentialStoreError) as exc:
        mgr.get_credential(cid, action_class=ActionClass.READ)
    assert "expired" in str(exc.value).lower()


def test_purpose_binding_survives_rotation() -> None:
    mgr, cid = _bound_manager(project_id="p1")
    mgr.rotate_credential(cid, "new-token")
    with pytest.raises(CredentialStoreError):
        mgr.get_credential(cid, action_class=ActionClass.READ, project_id="p2")
    _, sec = mgr.get_credential(cid, action_class=ActionClass.READ, project_id="p1")
    assert sec.raw_value == "new-token"


def test_unbound_credential_still_works() -> None:
    """Backward compatibility: credentials without a binding are unaffected."""
    mgr = CredentialManager(store=InMemoryCredentialStore())
    meta = mgr.register_credential(
        name="plain", credential_type=CredentialType.API_KEY, provider="p", secret_value="v"
    )
    assert mgr.get_credential(meta.credential_id)[1].raw_value == "v"


# ═══ SHC-05 — Egress destination control ═══════════════════════════════


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://[::1]/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "ftp://example.com/",
    ],
)
def test_blocked_destinations_are_denied(url: str) -> None:
    ok, _reason = validate_egress_url(url)
    assert ok is False, f"{url} should be denied"


@pytest.mark.parametrize("url", ["http://example.com:22/", "http://example.com:6379/"])
def test_blocked_ports_are_denied(url: str) -> None:
    ok, _ = validate_egress_url(url)
    assert ok is False


def test_public_https_is_allowed() -> None:
    ok, _ = validate_egress_url("https://example.com/resource")
    assert ok is True


def test_domain_allowlist_is_enforced() -> None:
    # A host outside the allowlist is refused without ever being resolved.
    ok, reason = validate_egress_url("https://evil.invalid/", allowed_domains=["example.com"])
    assert ok is False
    assert "allowed domain" in reason


def test_empty_url_is_rejected() -> None:
    assert validate_egress_url("")[0] is False


# ═══ SHC-06 — Egress content control ════════════════════════════════════

SECRET_PAYLOADS = [
    {"k": "AKIAIOSFODNN7EXAMPLE"},
    {"k": "ghp_" + "a" * 30},
    {"k": "sk-" + "b" * 30},
    {"k": "xoxb-1234567890-abcdefghij"},
    {"k": "AIza" + "c" * 35},
    {"k": "-----BEGIN RSA PRIVATE KEY-----\nabc"},
    {"nested": {"a": {"b": {"c": "AKIAIOSFODNN7EXAMPLE"}}}},
    {"list": ["ok", "AKIAIOSFODNN7EXAMPLE"]},
]


@pytest.mark.parametrize("payload", SECRET_PAYLOADS)
def test_secret_payloads_are_blocked(payload) -> None:
    result = EgressPolicy().enforce("https://example.com/x", body=payload)
    assert result.decision is EgressDecision.DENY
    assert "AKIAIOSFODNN7EXAMPLE" not in str(result.sanitized_payload)


def test_registered_secret_value_is_blocked() -> None:
    policy = EgressPolicy(registered_secrets=("my-private-token",))
    result = policy.enforce("https://example.com/x", body={"note": "my-private-token here"})
    assert result.decision is EgressDecision.DENY


def test_credential_header_is_denied() -> None:
    result = EgressPolicy().enforce(
        "https://example.com", headers={"Authorization": "Bearer " + "z" * 30}
    )
    assert result.decision is EgressDecision.DENY


def test_api_key_header_is_denied() -> None:
    result = EgressPolicy().enforce("https://example.com", headers={"X-API-Key": "abc123"})
    assert result.decision is EgressDecision.DENY


def test_benign_payload_is_allowed() -> None:
    result = EgressPolicy().enforce("https://example.com", body={"query": "hello", "limit": 10})
    assert result.decision is EgressDecision.ALLOW


def test_sensitive_field_is_redacted_not_dropped() -> None:
    result = EgressPolicy().enforce("https://example.com", body={"user": "bob", "password": "x"})
    assert result.decision is EgressDecision.REDACT
    body = result.sanitized_payload["body"]
    assert body["user"] == "bob"
    assert "REDACTED" in body["password"]


def test_query_params_are_inspected() -> None:
    result = EgressPolicy().enforce(
        "https://example.com/search", params={"q": "AKIAIOSFODNN7EXAMPLE"}
    )
    assert result.decision is EgressDecision.DENY


def test_destination_denied_before_content_check() -> None:
    """Destination control runs first, so a blocked host is never contacted."""
    result = EgressPolicy().enforce("http://127.0.0.1/x", body={"a": 1})
    assert result.decision is EgressDecision.DENY
    assert "127.0.0.1" in result.reason


def test_egress_audit_trail_is_recorded() -> None:
    policy = EgressPolicy()
    policy.enforce("https://example.com", body={"a": 1})
    policy.enforce("http://127.0.0.1/", body={"a": 1})
    policy.enforce("https://example.com", body={"k": "AKIAIOSFODNN7EXAMPLE"})
    events = {a["event"] for a in policy.audit}
    assert "egress.allowed" in events
    assert "egress.denied.destination" in events
    assert "egress.denied.secret" in events


def test_deeply_nested_payload_is_inspected() -> None:
    """Value-shape detection must work at depth, not only at the top level."""
    payload: dict = {"level": 1}
    node = payload
    for _ in range(6):
        node["child"] = {"level": node["level"] + 1}
        node = node["child"]
    # Field name is deliberately innocuous so the *value* is what triggers.
    node["note"] = "AKIAIOSFODNN7EXAMPLE"
    result = EgressPolicy().enforce("https://example.com", body=payload)
    assert result.decision is EgressDecision.DENY


def test_inspect_payload_handles_bytes_and_sets() -> None:
    findings, _ = inspect_payload(
        {"blob": b"AKIAIOSFODNN7EXAMPLE", "s": {"AKIAIOSFODNN7EXAMPLE"}}
    )
    assert any(f.startswith("secret_shape:") for f in findings)



def test_nonce_is_unique_per_encryption() -> None:
    cipher = CredentialCipher(TestKeyProvider("k"))
    nonces = {cipher.seal("same-plaintext", "c1").nonce for _ in range(64)}
    assert len(nonces) == 64, "nonce reuse would break GCM confidentiality"


def test_ciphertext_is_bound_to_credential_id() -> None:
    """A record copied to another credential must fail authentication."""
    cipher = CredentialCipher(TestKeyProvider("k"))
    rec = cipher.seal("secret", "cred-A")
    with pytest.raises(DecryptionError):
        cipher.open(rec, "cred-B")


def test_credentials_survive_restart(tmp_path: Path) -> None:
    LocalEncryptedStore(tmp_path, TestKeyProvider("k")).save(_meta(), SecretValue("persisted"))
    reloaded = LocalEncryptedStore(tmp_path, TestKeyProvider("k"))
    assert reloaded.retrieve("c1")[1].raw_value == "persisted"


def test_index_file_is_not_world_readable(tmp_path: Path) -> None:
    store = LocalEncryptedStore(tmp_path, TestKeyProvider("k"))
    store.save(_meta(), SecretValue("v"))
    assert store.index_file.stat().st_mode & 0o077 == 0
