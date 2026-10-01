# SECURITY THREAT MODEL

**Phase:** 18-SECURITY
**Date:** 2026-02-10
**Scope:** AutoForge AI-OS as certified at baseline `61572c5`

---

## 1. Trust Model Principles

1. **Model output is never trusted.** Everything an LLM emits — code, commands,
   paths, URLs, arguments, configuration values, artifact names, review verdicts —
   is UNTRUSTED data until a deterministic control validates it.
2. **Deterministic beats advisory.** A prompt instruction is not a security
   control. Every boundary below is enforced in code, not in prose.
3. **Fail closed.** Absent, malformed, or erroring evidence is a denial, never an
   approval.
4. **Least privilege by default.** Capability is denied unless explicitly granted.

---

## 2. Trust Boundary Inventory

| # | Boundary | Classification | Enforcing control | Verified |
|---|---|---|---|---|
| TB-01 | User input → API boundary (`/api/*`) | **UNTRUSTED** | `apps/api` handler; loopback bind by default | §audit |
| TB-02 | Project configuration → orchestration | **UNTRUSTED** | `SecurityBoundaryGuard.validate_command` | SEC-03 repaired |
| TB-03 | Stage `verification_commands` | **UNTRUSTED** | `SecurityBoundaryGuard` before execution | SEC-02/03 repaired |
| TB-04 | Model-generated source code | **UNTRUSTED** | Review `SecurityReviewer`, deterministic checks | PASS |
| TB-05 | Model-generated commands | **UNTRUSTED** | `SecurityBoundaryGuard`, `SafeExecutionRunner` | PASS |
| TB-06 | Model-generated filesystem paths | **UNTRUSTED** | `PhysicalArtifactStore.resolve_*_path`, `PolicyValidator` | PASS |
| TB-07 | Model-generated URLs / SSRF | **UNTRUSTED** | `agent/tools.py` host validator (loopback/RFC1918/link-local/DNS-rebinding) | PASS |
| TB-08 | Shell / subprocess execution | **UNTRUSTED args, TRUSTED argv form** | argv-only; no `shell=True` in any production exec path | SEC-01 repaired |
| TB-09 | Sandbox image reference | **CONDITIONALLY TRUSTED** (operator config) | argv-only subprocess probe | **SEC-01 repaired** |
| TB-10 | Workspace filesystem | **TRUSTED root, UNTRUSTED content** | `resolve()` + `is_relative_to()` confinement | PASS |
| TB-11 | Artifact store / durable state | **UNTRUSTED names, TRUSTED structure** | `PhysicalArtifactStore`, UUID5 identity | PASS |
| TB-12 | Cross-project artifact namespace | **TRUSTED** (separated by workflow/project scope) | `derive_artifact_key` + `PhysicalArtifactStore` | PASS |
| TB-13 | Review Engine verdict | **UNTRUSTED as authority** | `completion.py` treats it as an input, not an override | PASS |
| TB-14 | Deterministic validation result | **AUTHORITATIVE** | `completion.py` DEF-18LR-D8 override guard | PASS |
| TB-15 | Secrets / credentials | **NEVER TRUSTED to model or logs** | `SecretManager.redact_*`, `redaction.py`, env allowlists | PASS |
| TB-16 | Local inference providers | **CONDITIONALLY TRUSTED** | loopback endpoints, structured output, AST-based parsing | PASS |
| TB-17 | Network egress (container) | **BOUNDED by policy** | `NetworkMode.DENY` → `--network none`; ALLOWLIST → bridge | PASS |
| TB-18 | Environment variables to children | **UNTRUSTED** | env allowlist; host secrets stripped | PASS |
| TB-19 | Logs / audit trail / telemetry | **UNTRUSTED sink** | `redact_structure` on audit events | PASS |
| TB-20 | Delivery / export packaging | **CONDITIONALLY TRUSTED** | hash verification, packaging boundary | PASS |
| TB-21 | Durable recovery / resume | **TRUSTED** (integrity-checked) | `validate_integrity` + hash verification | PASS |

---

## 3. Attacker Models

| Actor | Capability | Primary goals |
|---|---|---|
| **A1 Malicious project author** | Supplies project name, description, `verification_commands`, config | Obtain host command execution; escape workspace; read other projects' artifacts |
| **A2 Prompt-injected content** | Controls text inside retrieved docs, source comments, task descriptions | Elevate data into instructions; reach a shell, path, or URL sink |
| **A3 Compromised/malicious model** | Emits arbitrary code, commands, paths, URLs, verdicts | Same as A2, plus forge artifacts and approve its own output |
| **A4 Network attacker** | Controls a remote endpoint the platform calls | SSRF into loopback/RFC1918; data exfiltration |
| **A5 Local unprivileged user** | Can set env vars, create files in shared roots | Env injection; symlink escape; race on staging→publish |

---

## 4. Key Attack Paths Analysed

| Path | Chain | Boundary crossed | Status |
|---|---|---|---|
| P-1 | `verification_commands` → `bash -c "<cmd>"` → host shell | TB-03, TB-08 | **Was open (SEC-03) → closed** |
| P-2 | sandbox `image` config → `os.system` f-string → shell | TB-09, TB-08 | **Was open (SEC-01) → closed** |
| P-3 | forbidden command → `AttributeError` → wrong error class | TB-03 | **Was degraded (SEC-02) → closed** |
| P-4 | artifact name → `../` → host filesystem | TB-06, TB-11 | Closed |
| P-5 | symlink in artifact root → escape | TB-05, TB-10 | Closed |
| P-6 | model URL → loopback/metadata service | TB-07 | Closed |
| P-7 | Review APPROVED + validation FAILED → completion | TB-13/14 | Closed (deterministic wins) |
| P-8 | Review missing/exception → completion | TB-13 | Closed (fail closed) |
| P-9 | artifact of project A exported as project B | TB-12, TB-20 | Closed |

---

## 5. Out of Scope (explicitly)

- Absolute cryptographic safety.
- Host kernel / container-runtime escape (delegated to Podman/Docker).
- Physical access to the developer machine.
- Denial-of-service by an authorised local operator.

The system is **not** claimed "secure" in an absolute sense. It is certified
**with the defined scope and test coverage** documented in
`SECURITY_TEST_MATRIX.md`.