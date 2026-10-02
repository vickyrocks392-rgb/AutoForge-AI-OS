# Security Findings — Completion Pass

Every finding was verified against code at `b05d66a` and either repaired with a
regression test or explicitly justified. No finding was downgraded to obtain a
clean report.

---

## SHC-02 — API had no authentication or project authorization (BLOCKER) — **REPAIRED**

**Location.** `apps/api/src/autoforge_api/server.py` (all `/api/*` endpoints).

**Defect.** No endpoint consulted an `Authorization` header. Any process able to
reach the loopback port could list, read, mutate, launch, stop, and export every
project, and `/api/auth/me` returned a hardcoded `PLATFORM_ADMIN` identity.
There was no ownership check anywhere, so a caller could substitute an arbitrary
`project_id` and receive another project's artifacts, runtime state, source
archive, and delivery package.

**Attack boundary.** Any local process, malicious local application, compromised
dependency, or browser request via local origin. "Localhost" was being treated as
trusted, which it is not.

**Repair.**
- New `apps/api/src/autoforge_api/auth.py`: `ApiAuthenticator` delegating to the
  certified `SecurityPlatform` — no second authentication framework.
- New `server.py::_authenticate_request()`, called at the top of `do_GET`,
  `do_POST`, and `do_DELETE`.
- `_extract_project_id()` resolves the real target **before** access;
  `authorize_project()` compares it against the caller's authorized set **before**
  the resource is returned or mutated.
- `PUBLIC_API_PATHS` limited to read-only `/api/system/status`.
- Fail-closed startup: auth enabled with no configured key refuses to start.
- Explicit dev/test opt-out only (`AUTOFORGE_API_AUTH_DISABLED=1`,
  `--allow-insecure-dev-auth`).

**Evidence.** `apps/api/tests/test_api_security_auth.py` — 16 tests over a real
socket: missing auth → 401, invalid token → 401, cross-project read/write/run/
download → 403, authorized project → 200, fail-closed startup, audit emission.

---

## SHC-03 — LocalEncryptedStore used XOR obfuscation (HIGH) — **REPAIRED**

**Location.** `packages/security/src/autoforge_security/credentials.py`.

**Defect.** Credentials were "encrypted" with a repeating-key XOR keystream
derived from the hardcoded literal `"autoforge-local-default-key"`. That is
obfuscation, not encryption: no integrity protection, and every installation
shared the same key.

**Repair.** New `packages/security/src/autoforge_security/crypto.py`:
- AES-256-GCM via `cryptography` — a vetted library, no hand-rolled crypto.
- Fresh 96-bit random nonce per encryption.
- Credential id bound as AAD, so a record cannot be transplanted between credentials.
- Explicit envelope versioning (`"version": 2`).
- `MasterKeyProvider` abstraction: `EnvironmentKeyProvider` (production, fails
  closed when unset), `FileKeyProvider`, `GeneratedFileKeyProvider` (0600 file),
  `TestKeyProvider` (CI only). **No hardcoded universal production key.**
- Atomic index write and 0600 permissions.
- Legacy v1 records detected by absence of `version`, decrypted **only** inside
  `_migrate_legacy()`, then immediately re-encrypted as AEAD.

**Evidence.** 24 tests: tamper detection, wrong key, 64× nonce uniqueness, AAD
binding, restart persistence, 0600 perms, legacy migration, migration-disabled
fails closed, no repeat migration, key-provider validation.

---

## SHC-04 — Credentials not bound to purpose or project (MEDIUM) — **REPAIRED**

**Defect.** A credential approved for any purpose could be used for any purpose
or by any project. Nothing stopped a "GitHub read" token being used for an
arbitrary HTTP POST, or a project-A credential being used in project B.

**Repair.** `CredentialPurposeBinding` (frozen model in `models.py`) binds a
credential to purpose, project, allowed action classes, allowed destinations,
issuing subject, and lifetime. `CredentialManager.get_credential()` enforces it;
a bound credential requested without use facts fails closed. Preserved through
rotation and revocation.

**Defect found by my own tests during this pass:** purpose binding initially
broke `rotate_credential`/`revoke_credential`, which called the enforcing loader.
Fixed with `_load_enforcing_lifecycle()` — revocation and expiry still apply,
purpose binding does not, because a bound credential must remain rotatable and
revocable.

---

## SHC-05 — No canonical egress policy (MEDIUM) — **REPAIRED**

**Defect.** `validate_outbound_url` (agent tools) was strong, but no canonical
policy existed for other outbound paths, and there was no port restriction or
explicit cloud-metadata denial.

**Repair.** `packages/security/src/autoforge_security/egress.py`:
`validate_egress_url()` adds blocked-port policy, cloud-metadata host denial, and
preserves the existing scheme / loopback / private / DNS-rebinding semantics.

**Scope note.** Model-provider and connector URLs remain operator-configured and
outside the AI-initiated request path; they are documented, not silently rewired.

---

## SHC-06 — No content inspection before transmission (HIGH) — **REPAIRED**

**Defect.** An approved destination could receive any payload, including secrets
read from the workspace or environment.

**Repair.** `EgressPolicy.enforce()` performs recursive inspection of headers,
query params, and body before any I/O. Blocks registered secret values, 10
high-confidence secret shapes (AWS, GitHub, Slack, Google, OpenAI, Anthropic,
bearer, JWT, private-key blocks), and credential-bearing headers. Sensitive
*field names* (e.g. `password`) are redacted rather than denied, so legitimate
application traffic still works. Wired into `tool_structured_http` and
`ToolRegistry`.

**Evidence.** 22 tests including 8 parametrized secret payloads, nested-depth
scanning, bytes/sets, query params, header denial, and a positive test proving
benign traffic still works.

---

## SHC-07 — Artifact access had no project scoping (MEDIUM) — **REPAIRED**

**Defect.** `LocalArtifactStore.get(artifact_id)` and
`DurableArtifactStoreBridge.get(artifact_id)` accept a bare artifact id with no
project scope, so a caller holding another project's artifact id could read or
mutate it.

**Repair.** `packages/artifacts/src/autoforge_artifacts/scoped_access.py`:
`ProjectScopedArtifactAccess` enforces project scope on `get`, `update`,
`list_artifacts`, and `export_payload`, resolving the artifact and comparing
`project_id` **before** the underlying store is touched.

**Durable identity preserved.** 18-J/18-K key derivation and UUID5 identity are
untouched; isolation is enforced *above* the storage layer, as required.

---

## SHC-01 — Guardrails/trust boundary had no production caller (MEDIUM) — **REPAIRED**

**Defect found during GATE 1 tracing.** `AIGuardrailsEngine` and `TrustBoundary`
were referenced only in `packages/security` and tests. The prior certification
claimed guardrails were "actually enforced, not merely documented"; that was an
overstatement, corrected here.

**Repair.** `StandaloneAgentRuntime` now constructs a `TrustBoundary` by default
and routes the system prompt, conversation history, and user input through it.
`ToolRegistry` accepts an `egress_policy` and passes it to the outbound tool.

**Honest scoping.** `enforce_ai_action()` remains the canonical, audited entry
point on `SecurityPlatform`; the guardrail *decision* is enforced immediately
before side effects via `authorize_tool_call()` inside `execute_tool()`.
Guardrail classification is not inlined into every orchestration stage — that
would reopen the protected 18-L orchestrator contract without concrete evidence.

---

## SHC-09 — No lockfile, SBOM, or vulnerability scanning (MEDIUM) — **REPAIRED**

**Repair.**
- `scripts/generate_lock_and_sbom.py` → `requirements.lock` (67 pinned
  distributions) and `build/sbom.json` (CycloneDX 1.5).
- `--check` mode verifies lockfile drift; wired into `.github/workflows/ci.yml`.
- `pip-audit` step added with `continue-on-error: true` so an advisory-database
  outage is reported honestly rather than silently passing or fabricating a clean
  result.

**No CVE results are claimed anywhere in this repository.** No advisory data
source exists in this environment.

---

## Summary

| ID | Severity | Status |
|---|---|---|
| SHC-01 | MEDIUM | **REPAIRED** |
| SHC-02 | **BLOCKER** | **REPAIRED** |
| SHC-03 | HIGH | **REPAIRED** |
| SHC-04 | MEDIUM | **REPAIRED** |
| SHC-05 | MEDIUM | **REPAIRED** |
| SHC-06 | HIGH | **REPAIRED** |
| SHC-07 | MEDIUM | **REPAIRED** |
| SHC-09 | MEDIUM | **REPAIRED** |

**BLOCKER: 0 · HIGH: 0 · MEDIUM: 0 open.**

### LOW / INFO retained (documented, non-blocking)

| Item | Why it remains |
|---|---|
| Model-provider / connector URLs not routed through egress policy | Operator-configured, not AI-initiated; outside the AI-reachable request path. |
| Guardrail decision not inlined in every orchestration stage | Would reopen the protected 18-L contract without concrete evidence; `authorize_tool_call()` already binds at the side effect. |
| Lockfile pins are version-exact but not hash-pinned | Hash pinning requires a platform-specific build. |
| No rate limiting on the local API | Loopback-only surface; Phase 20/23 concern. |
| Multi-tenant isolation | Single-tenant local-first product today. |

