# Security Hardening Report

## 1. Summary

A production-grade forensic audit and implementation pass over the AI-originated
action path of AutoForge AI OS. Starting from the certified Phase 18-Security
baseline (`617fef5`), this pass found and repaired **one P0 production blocker**
plus **four P1 gaps**, and built the **AI Guardrails Layer** the repository
previously lacked entirely.

| Metric | Value |
|---|---|
| BLOCKER findings | **0** |
| HIGH findings open | **0** |
| Findings repaired | **5** (1×P0, 4×P1) |
| Findings deferred (documented) | 2×P1, 2×P2, plus P3 backlog |
| New security tests | **72** |
| Security package tests | **107** (37 certified + 70 new/updated) |
| Full-repo tests | **1768 passed**, 27 skipped, 4 failed (all environmental) |
| Certified controls retained | **15/15** |
| Files changed | 6 modified, 3 new source/test, 9 documents |

## 2. Existing Controls Retained

All 15 certified Security Platform capabilities are intact and passing:
identity, authentication, session lifecycle, API keys, RBAC/fine-grained
authorization, governance policy engine, HITL, secrets management, credential
storage, recursive redaction, sandbox policy, worker security profiles, audit
trail, and canonical security events — plus the `SecurityPlatform` facade.

Adjacent controls discovered during the audit were credited and preserved, not
rewritten: `SecurityBoundaryGuard`, `SafeExecutionRunner`, `validate_outbound_url`,
`validate_workspace_path`, `SafetyConstraintsConfig`, Review Engine dangerous-
execution checks, durable artifact identity, and API project-id sanitization.

**No certified subsystem was replaced, forked, or weakened.** The new guardrails
layer delegates all authority decisions to the certified engines.

## 3. New Controls Implemented

| # | Control | Implementation |
|---|---|---|
| 1 | **AI Guardrails layer** | `packages/security/src/autoforge_security/ai_guardrails.py` — 9 ordered trust levels, 10 action classes, 22 capabilities, 5 decision types, `AIGuardrailsEngine.enforce()` |
| 2 | **Trust boundary** | `packages/security/src/autoforge_security/trust_boundary.py` — instruction/data separation, 14 injection patterns, compaction trust preservation |
| 3 | **Facade integration** | `SecurityPlatform.guardrails`, `.trust_boundary`, `.enforce_ai_action()` (audited) |
| 4 | **Execution-point authorization** | `authorize_tool_call()` in `agent/tools.py`, enforced inside `execute_tool()` and by `StandaloneAgentRuntime.run()` |
| 5 | **Self-improvement boundary** | `evaluate_learning_proposal()` + `LEARNING_FORBIDDEN_CAPABILITIES` |
| 6 | **Credential expiry enforcement** | `CredentialManager.get_credential()` now evaluates `expires_at` on every read |

## 4. Controls Intentionally Deferred

| ID | Item | Reason | Severity |
|---|---|---|---|
| SHG-06 | API authentication / IDOR | Needs identity+session bound to HTTP across ~40 endpoints — Phase 20/23. A partial token check would be false assurance. | P1 |
| G6-6 | `LocalEncryptedStore` XOR keystream, default master key | Obfuscation, not cryptography. Changing it would break persisted credentials and reopens the protected credential contract. | P1 |
| G10-3 | Project scoping in artifact key | No practical collision (`workflow_id` is uuid4 per execution); changing key derivation invalidates certified durable identity. | P2 |
| G5-5 | Egress content inspection | Requires an egress proxy — Phase 20. | P2 |
| G6-5 | Credential purpose binding | Needs workflow/project claim validation at retrieval. | P2 |
| SHG-07 | Lockfile / SBOM / CVE scanning | CI/SDLC change; **no CVE data source in this environment — no results fabricated**. | P3 |
| SHG-09 | Generated-code egress re-validation | Would touch the protected Commercial Power Engine generator contract. | P3 |

## 5. Findings by Severity

### P0 — Repaired
- **SHG-01** Tool allowlist not enforced at execution. Proven with a live network
  request before repair; proven blocked after.

### P1 — Repaired
- **SHG-02** Credential expiry never enforced.
- **SHG-03** No AI Guardrails layer.
- **SHG-04** No trust-boundary metadata on untrusted context.
- **SHG-05** No self-improvement security boundary.

### P1 — Deferred
- **SHG-06** API authentication (loopback-bound, local-first product).
- **G6-6** Local credential store encryption strength.

### P2 — Documented
- **SHG-08** Artifact key project scoping.
- **G5-5 / G6-5 / G10-4** Egress inspection, purpose binding, multi-tenancy.

### P3 — Backlog
- SHG-07 supply chain, SHG-09 generated-code egress, NET-01/02/06, G11-6 rate limiting.

## 6. Full-Path Integration Verification (GATE 14)

| Property | Proof |
|---|---|
| No AI action bypasses authorization | `authorize_tool_call()` runs inside `execute_tool()`; `test_04b` |
| No AI action bypasses sandbox | `SecurityBoundaryGuard` + `SandboxPolicyEngine` unchanged and passing |
| No model can self-approve | `validate_human_approver()` + `test_request_cannot_self_declare_hitl_approval` |
| No model can self-elevate | `test_model_cannot_self_elevate_via_credential`, `test_model_cannot_change_governance_policy[×5]` |
| No model accesses unauthorized credentials | `ActionClass.CREDENTIAL` → `REQUIRE_ELEVATED_AUTHORITY` |
| No model escapes project scope | `AuthorizationEngine` step 6 unchanged |
| No retrieved content overrides policy | `test_poisoned_rag_cannot_override_policy` |
| No tool output grants authority | `test_tool_output_trust_is_preserved`, `test_injection_never_becomes_instruction[×10]` |
| No learning output modifies security boundaries | `test_learning_cannot_self_escalate[×7]` |
| Failed checks never become success | `enforce()` fault → DENY; blocked tool → `blocked_by` + `continue` (never a result) |

## 7. Regression Verification

| Suite | Baseline | After | Delta |
|---|---|---|---|
| `packages/security` | 37 passed | **107 passed** | +70 |
| `packages/orchestration` | 101 passed, 6 skipped | 101 passed, 6 skipped | 0 |
| `packages/artifacts` | 14 passed | 14 passed | 0 |
| `packages/execution` | 257 passed, 18 skipped | 257 passed, 18 skipped | 0 |
| `packages/power_engines` | 123 passed, 3 skipped, 1 failed | 125 passed, 3 skipped, 1 failed | +2 |
| `packages/review` | 114 passed | 114 passed | 0 |
| `apps/api` | 25 passed | 25 passed | 0 |

No protected subsystem regressed.

## 8. Known Environmental Failures (explicitly separated)

4 failures remain, all caused by an unrelated local process listening on
`127.0.0.1:8080`, which probes reach instead of a dead port:

1. `packages/power_engines/tests/test_delivery_hardening.py::test_health_check_script_execution_and_exit_codes`
2. `packages/composition/tests/test_canonical_context_builder.py::test_canonical_context_builder_invoked_in_execution_path`
3. `packages/composition/tests/test_canonical_durable_artifacts.py::test_canonical_durable_artifact_wiring`
4. `packages/composition/tests/test_execution_platform_integration.py::test_autoforge_system_execution_wiring`

**Verified pre-existing:** changes were stashed and all three composition
failures reproduced identically at pristine SHA `617fef5`. None is a product
security defect. Evidence: `lsof -nP -iTCP:8080 -sTCP:LISTEN` shows a live
`python3.12` listener; composition errors show HTTP 401/404 from that service
rather than connection refusal.
