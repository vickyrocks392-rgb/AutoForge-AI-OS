# Security Repair Report

Implementation summary for the completion pass. Every repair below is enforced at
a runtime seam, not only documented.

---

## SHC-02 — API authentication + project authorization

**New:** `apps/api/src/autoforge_api/auth.py` (233 lines)
**Modified:** `apps/api/src/autoforge_api/server.py`

Added `ApiAuthenticator` delegating to the certified `SecurityPlatform`:
`authenticate()` (static API key with constant-time compare, or certified
session token), `authorize_project()` (object-level), `authorize_permission()`
(RBAC). `ApiAuthError` carries an HTTP status.

`server.py` gained `_extract_project_id()` and `_authenticate_request()`, called
at the top of `do_GET`, `do_POST`, and `do_DELETE`. `create_server()` now
constructs an authenticator or refuses to start. Added
`--allow-insecure-dev-auth` CLI flag that prints a warning.

**Modified:** `apps/api/tests/conftest.py` — sets the explicit dev opt-in for the
legacy Phase 16 suite.

---

## SHC-03 — AEAD credential encryption

**New:** `packages/security/src/autoforge_security/crypto.py` (275 lines)
**Modified:** `packages/security/src/autoforge_security/credentials.py`

`MasterKeyProvider` hierarchy, `EncryptedRecord` envelope, `CredentialCipher`
(AES-256-GCM, 12-byte nonce, credential-id AAD), `legacy_xor_decrypt()` isolated
for migration.

`LocalEncryptedStore` rewritten: versioned envelope detection, tamper-detecting
load, `_migrate_legacy()` one-shot path, atomic 0600 `_persist()`.

---

## SHC-04 — Credential purpose binding

**Modified:** `packages/security/src/autoforge_security/models.py`
(`CredentialPurposeBinding`), `credentials.py` (enforcement +
`_load_enforcing_lifecycle`).

`CredentialMetadata.purpose_binding` added (optional, `None` preserves
pre-existing behaviour). `get_credential()` gains `action_class`, `project_id`,
`destination`, `subject_id` parameters and enforces the binding.

---

## SHC-05 / SHC-06 — Egress destination + content control

**New:** `packages/security/src/autoforge_security/egress.py` (441 lines)
**Modified:** `packages/power_engines/.../agent/tools.py`

`validate_egress_url()` (scheme/port/loopback/private/link-local/metadata/
DNS-rebinding/allowlist), `inspect_payload()` (recursive DLP), `EgressPolicy`
(composite, fail-closed, audited).

`tool_structured_http()` gained `egress_policy` and enforces it before the first
byte; `ToolRegistry.__init__` gained `egress_policy` and passes it to the
outbound tool.

---

## SHC-07 — Project-scoped artifact access

**New:** `packages/artifacts/src/autoforge_artifacts/scoped_access.py` (129 lines)

`ProjectScopedArtifactAccess` with `get`, `update`, `list_artifacts`,
`export_payload`. Durable identity untouched.

---

## SHC-01 — Guardrail / trust-boundary runtime wiring

**Modified:** `packages/power_engines/.../agent/runtime.py`,
`packages/power_engines/.../agent/tools.py`

`StandaloneAgentRuntime.__init__` now builds a `TrustBoundary` by default;
`assemble_context()` routes the system prompt, history, and user input through
it with correct trust levels. `ToolRegistry` accepts `egress_policy`.

---

## SHC-09 — Supply chain

**New:** `scripts/generate_lock_and_sbom.py`, `requirements.lock`, `build/sbom.json`
**Modified:** `.github/workflows/ci.yml`, `packages/security/pyproject.toml`
(`cryptography>=42.0.0`), `packages/power_engines/pyproject.toml`
(`autoforge-security`).

---

## Defect found and fixed during this pass

Writing the new tests surfaced a regression I introduced: purpose binding initially
broke `rotate_credential()` and `revoke_credential()`, because they called the
enforcing `get_credential()` without an `action_class`. That would have made
bound credentials impossible to rotate or revoke — a security regression in the
opposite direction. Fixed with `_load_enforcing_lifecycle()`, which applies
revocation and expiry but not purpose binding, and is covered by
`test_purpose_binding_survives_rotation`.

## Compatibility / migration evidence

| Concern | Evidence |
|---|---|
| Existing credentials readable | `test_legacy_record_migrates_to_aead`, `test_migrated_record_is_readable_after_restart` |
| No credential loss on upgrade | migration is automatic on first load; `migrated_legacy_count` reports it |
| Restart persistence | `test_credentials_survive_restart` |
| Durable artifact identity unchanged | `test_durable_identity_semantics_unchanged`; 25/25 artifact tests pass |
| Legacy Phase 16 API suite unchanged | 25/25 pass via explicit dev opt-in |
| All certified security tests unchanged | 37/37 pass |
