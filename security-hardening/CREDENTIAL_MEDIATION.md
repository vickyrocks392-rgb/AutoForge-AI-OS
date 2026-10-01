# Credential Mediation

How credentials reach side effects, and why a model request for a credential is
never itself authorization.

## 1. Existing Controls (preserved)

| Control | Location | Behaviour |
|---|---|---|
| Central credential manager | `credentials.py::CredentialManager` | Single choke point for registration/retrieval/rotation/revocation |
| Pluggable stores | `InMemoryCredentialStore`, `LocalEncryptedStore` | Test/transient vs local-first encrypted |
| Metadata separation | `CredentialMetadata` | Frozen, `extra="forbid"`, no secret material |
| Non-disclosure | `secrets.py::SecretValue` | `__str__`/`__repr__` permanently `***`; raw value only via explicit `raw_value` |
| Recursive redaction | `SecretsManager.redact_structure` | Applied to audit records and API payloads |
| Permission gate | `SecurityPlatform.retrieve_credential` | Requires `credential.read` **or** `credential.use` |
| Lifecycle | `rotate_credential`, `revoke_credential` | Rotation preserves metadata; revocation is sticky |

## 2. Defect Repaired — SHG-02 (Credential Expiry)

`CredentialMetadata.expires_at` was persisted and copied through rotation but
**never evaluated**. `get_credential` checked only `is_revoked`, so a time-bound
credential continued returning its secret indefinitely after expiry.

**Proven pre-fix:** a credential expired one day in the past still returned its
secret value.

**Repair.** Expiry is now checked on every read:

```python
if meta.is_revoked:                    # revocation keeps precedence
    raise CredentialStoreError(...)
if meta.expires_at is not None:
    expires_at = meta.expires_at
    if expires_at.tzinfo is None:      # naive → UTC, comparison always total
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expires_at:
        raise CredentialStoreError(...)
```

Design notes:
- Evaluated **per read**, not cached — a previously resolved reference cannot
  outlive expiry.
- Revocation is checked **first**, preserving existing precedence semantics.
- Credentials with `expires_at is None` are unaffected (no false-deny regression).

## 3. Capability-Mediated Access (new)

A credential is an authority, so it is gated by the guardrail layer:

| Requirement | Effect |
|---|---|
| `credentials.use` capability | Worker must hold it explicitly |
| `ActionClass.CREDENTIAL` | Always security-sensitive → HITL |
| `REQUIRE_ELEVATED_AUTHORITY` | Model/tool/retrieved content **cannot** self-authorize |
| `permissions.credential.use` | Certified RBAC still applies |

**A model's request for a credential is itself only a proposal.** It is
classified, capability-checked, trust-checked, and escalated. It is never an
authorization input. Proven by
`test_model_cannot_self_elevate_via_credential`.

## 4. Purpose Binding

Credentials carry `scope` (`SYSTEM`, `CONNECTOR`, `WORKFLOW`, `PROJECT`,
`DEPLOYMENT`) via `SecretScope` and free-form `metadata`. Scoped issuance is
enforced; **request-time purpose binding** (asserting *why* a credential is being
used, and validating that claim against workflow/project) is **not yet
enforced** — recorded as P2 in `SECURITY_GAP_MATRIX.md` §6.

## 5. Residual Risks

| Risk | Severity | Status |
|---|---|---|
| `LocalEncryptedStore` uses a repeating-key XOR stream derived from a default master key (`"autoforge-local-default-key"`) | **P1** | **Known and pre-existing.** Not changed: altering the store contract would break persisted local credentials. Requires a Phase 20 key-management design (OS keychain / KMS). |
| No purpose-binding enforcement at retrieval | P2 | Documented |
| No credential-use rate limit or anomaly detection | P3 | Backlog |
| Secrets returned to callers who hold `credential.read` | Accepted by design | — |

The XOR store is worth flagging explicitly: it obfuscates but is **not
cryptography**. It is unchanged here because the scope rule protects the
credential store contract, and silently swapping the algorithm would render
existing on-disk credentials unreadable. It is escalated as the top Phase 20 item.

## 6. Tests

| Test | Proves |
|---|---|
| `test_expired_credential_is_refused` | expired credentials are denied (SHG-02) |
| `test_unexpired_credential_is_returned` | valid credentials still work (no false-deny) |
| `test_credential_without_expiry_is_unaffected` | `expires_at=None` unaffected |
| `test_revoked_credential_is_still_refused` | revocation precedence preserved |
| `test_model_cannot_self_elevate_via_credential` | model cannot self-authorize credentials |
| `test_missing_capability_denies` | missing `credentials.use` denies |
