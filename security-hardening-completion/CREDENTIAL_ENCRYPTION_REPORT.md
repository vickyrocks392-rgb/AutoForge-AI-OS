# Credential Encryption Report (SHC-03 / SHC-04)

## Before

```python
key = hashlib.sha256(master_key.encode()).digest()   # master_key = "autoforge-local-default-key"
encrypted[i] = raw[i] ^ key[i % len(key)]
```

Obfuscation, not encryption: no integrity tag, universal hardcoded key, and the
same key on every installation.

## After

| Property | Implementation |
|---|---|
| Algorithm | AES-256-GCM (`cryptography.hazmat...AESGCM`) |
| Confidentiality | GCM |
| Integrity / authentication | GCM auth tag; `InvalidTag` → `DecryptionError` |
| Nonce | `os.urandom(12)` per encryption — 64/64 unique in test |
| AAD binding | `b"autoforge-credential:v2:" + credential_id` — record transplant fails |
| Versioning | Envelope `version: 2` written per record |
| Key separation | Per-credential-id AAD; single master key via provider abstraction |

No cryptography is hand-implemented; `cryptography` 50.0.1 is a declared
dependency of `autoforge-security`.

## Key source hierarchy

| Provider | Use | Fails closed? |
|---|---|---|
| `EnvironmentKeyProvider` | Production (`AUTOFORGE_CREDENTIAL_MASTER_KEY`, 32 bytes hex) | **Yes** — raises if unset/short/malformed |
| `FileKeyProvider` | Explicit key file | Yes — raises if missing |
| `GeneratedFileKeyProvider` | Single-operator local default; creates a random 0600 key file | Yes on read |
| `TestKeyProvider` | Tests/CI only | n/a |

`default_key_provider()` order: environment key → existing local key file →
generate-and-persist. **There is no hardcoded universal production secret.**

## Migration safety

Legacy v1 records have no `version` field. On load they are:

1. Detected by format (absence of `version`).
2. Queued, never decrypted on the read path.
3. Decrypted only inside `_migrate_legacy()`.
4. Immediately re-encrypted as v2 and the index atomically rewritten.
5. Counted in `migrated_legacy_count` (0 on subsequent loads — no repeat).

`allow_legacy_migration=False` makes the store **refuse to load** rather than
silently accept legacy ciphertext.

Verified: `test_legacy_record_migrates_to_aead`,
`test_legacy_migration_can_be_disabled`,
`test_migrated_record_is_readable_after_restart`,
`test_legacy_decryptor_matches_legacy_xor`.

## Backward-compatibility evidence

| Test | Asserts |
|---|---|
| `test_credentials_survive_restart` | value readable after reload |
| `test_migrated_record_is_readable_after_restart` | migrated value persists |
| `test_index_file_is_not_world_readable` | mode `0600` |
| `test_new_records_use_versioned_aead_envelope` | `"version": 2`, no plaintext |
| `test_tampered_ciphertext_is_detected` | store refuses tampered index |
| `test_wrong_key_cannot_decrypt` | wrong key fails closed |
| `test_nonce_is_unique_per_encryption` | no nonce reuse |
| `test_ciphertext_is_bound_to_credential_id` | AAD binding holds |

## Purpose binding (SHC-04)

`CredentialPurposeBinding` binds a credential to purpose, project, allowed action
classes, allowed destinations, issuing subject, and lifetime. Enforcement happens
in `CredentialManager.get_credential()`. A bound credential requested without
`action_class` fails closed.

A defect surfaced by the new tests: purpose binding initially broke
`rotate_credential` / `revoke_credential`. Fixed by
`_load_enforcing_lifecycle()` — revocation and expiry still apply; purpose
binding does not, because a bound credential must remain rotatable/revocable.
