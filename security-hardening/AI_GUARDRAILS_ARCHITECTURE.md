# AI Guardrails Architecture

## 1. Position in the Execution Chain

```
AI / model
    ↓
proposal                       (TrustLevel-tagged by the PLATFORM)
    ↓
AI Guardrails                  ← AIGuardrailsEngine.enforce()   [NEW]
    ↓
identity                       SecurityPlatform.get_current_subject()
    ↓
worker capability               AIGuardrailsEngine.evaluate_capabilities()  [NEW]
    ↓
project / resource scope       AuthorizationEngine step 6 (contextual project check)
    ↓
authorization                  AuthorizationEngine / GovernancePolicyEngine
    ↓
sandbox / network / credential SandboxPolicyEngine / validate_outbound_url / CredentialManager
    ↓
HITL if required               HITLManager
    ↓
deterministic validation       AgentVerifier / Review Engine
    ↓
execution                      ToolRegistry.execute_tool(allowed_tools=...)  [REPAIRED]
    ↓
audit / event emission         AuditEngine / SecurityEventPublisher
```

The guardrails layer is a **pre-authorization gate**, not a replacement. It answers
"is this proposal admissible at all?" before the certified platform answers "is
this subject permitted?". Both must pass.

## 2. Core Invariants

| Invariant | Enforcement | Test |
|---|---|---|
| **INV-NON-AUTHORITATIVE** — model output never grants authority | `declared_trust_level` is platform-supplied; `NON_AUTHORITATIVE_TRUST` excludes model/retrieved/tool/legacy content from authority | `test_model_cannot_change_governance_policy`, `test_model_cannot_self_elevate_via_credential` |
| **INV-FAIL-CLOSED** — faults never become ALLOW | `enforce()` wraps evaluation in `try/except` → DENY; malformed input → INVALID_REQUEST; unknown action → `EXECUTE` | `test_malformed_request_is_invalid_not_allowed`, `test_unknown_actions_fail_closed_to_execute` |
| **INV-NO-SELF-AUTHORIZE** — low trust cannot satisfy escalation | `_requires_elevated_authority()` compares `trust_level.rank` to `HUMAN_AUTHORITY.rank` | `test_sensitive_actions_require_hitl` |
| **INV-NO-CLASS-SPOOFING** — payload cannot declare a benign class | `classify_action()` re-derives and compares against declared class | `test_action_class_spoofing_is_rejected` |
| **INV-TAMPER-RESISTANT** — no runtime policy mutation | No `set_`/`mutate`/`reload` API; read-only properties; frozen models | `test_engine_exposes_no_policy_mutation_api`, `test_engine_policy_attributes_are_read_only` |
| **INV-AUDITABLE** — decisions are correlatable | `correlation_id` on every decision incl. denials; `enforce_ai_action()` writes an audit record | `test_correlation_ids_are_propagated` |
| **INV-IMMEDIATE** — enforced at the side effect | `authorize_tool_call()` runs inside `execute_tool()` | `test_04b_tool_outside_allowlist_is_blocked` |

## 3. Decision Model

Evaluation order is fixed and short-circuits on the first failure:

| Step | Check | Outcome on failure |
|---|---|---|
| 1 | Structural validation | `INVALID_REQUEST` |
| 2 | Platform-derived action class == declared class | `INVALID_REQUEST` |
| 3 | Governance action from non-authoritative trust | `DENY` |
| 4 | Capability coverage | `DENY` |
| 5 | Elevated authority required, trust insufficient | `REQUIRE_ELEVATED_AUTHORITY` |
| 6 | HITL required (explicit or security-sensitive class) | `REQUIRE_HITL` |
| 7 | — | `ALLOW` |

Security-sensitive classes (`DELETE`, `EXECUTE`, `CREDENTIAL`, `PUBLISH`,
`DEPLOY`, `MIGRATE`, `GOVERNANCE`) always reach step 6 at minimum, so they
escalate rather than execute.

## 4. Trust Levels (ordered, monotonic)

| Rank | Level | Authority | May instruct? |
|---:|---|---|---|
| 100 | `SYSTEM_POLICY` | platform | **Yes** (sole INSTRUCTION source) |
| 90 | `HUMAN_AUTHORITY` | human operator | Yes, via platform |
| 70 | `CUSTOMER_INSTRUCTION` | customer | No — DATA |
| 60 | `PLATFORM_GENERATED_DATA` | platform derivation | No — DATA |
| 50 | `RETRIEVED_DATA` | RAG / documents | No — DATA |
| 45 | `LEGACY_SOURCE` | legacy codebase | No — DATA |
| 30 | `EXTERNAL_TOOL_OUTPUT` | tool results | No — DATA |
| 20 | `MODEL_OUTPUT` | model | No — DATA |
| 10 | `UNTRUSTED_GENERATED_CONTENT` | arbitrary | No — DATA |

Levels 50/45/30/10 form `DATA_ONLY_TRUST` (neutralized + DATA-only).
Levels 50/45/30/20/10 form `NON_AUTHORITATIVE_TRUST` (never authority).

## 5. Capability Matrix

| Action class | Required capability | HITL? |
|---|---|---|
| READ | `filesystem.read` | No |
| WRITE | `filesystem.write` | No |
| DELETE | `filesystem.delete` | **Yes** |
| EXECUTE | `process.execute` | **Yes** |
| NETWORK | `network.outbound` | No (policy-governed) |
| CREDENTIAL | `credentials.use` | **Yes + elevated** |
| PUBLISH | `artifacts.publish` | **Yes** |
| DEPLOY | `deployment.execute` | **Yes** |
| MIGRATE | `deployment.execute` | **Yes** |
| GOVERNANCE | `security.modify` | **Yes + elevated** |

Full taxonomy (22 capabilities across filesystem, process, network, git,
credentials, artifacts, deployment, security) is in `ai_guardrails.py` and
`ACTION_CAPABILITY_MATRIX.md`.

## 6. Integration Surface

| Component | Integration |
|---|---|
| `SecurityPlatform.guardrails` | read-only accessor to the engine |
| `SecurityPlatform.enforce_ai_action()` | enforcing + audited entry point |
| `SecurityPlatform.trust_boundary` | trust-tagged context construction |
| `ToolRegistry.execute_tool(allowed_tools=…)` | execution-point authorization |
| `StandaloneAgentRuntime.run()` | passes `spec.allowed_tools`; blocks on denial |

No certified subsystem was modified in a way that changes its semantics; the six
modified files are additive or tighten enforcement at the execution point.
