# ADR-016: Phase 15 — Security & Governance Platform Architecture

**Status:** Accepted  
**Phase:** 15 — Security & Governance Platform  
**Date:** 2026-08-28  
**Authors:** AutoForge AI Platform Team  

---

## Context

AutoForge AI OS executes autonomous engineering and legacy modernization workloads. Consequential actions (such as technology-stack finalization, architecture decisions, database/code migrations, production deployments, cutovers, and credential management) carry profound operational and business impact.

To ensure safety, stability, and zero unauthorized mutations, AutoForge requires an authoritative, 100% deterministic Security & Governance Platform.

### Core Architectural Invariants
1. **Security & Governance Sits Strictly Above Execution**:
   ```
   Human Authority
         ↓
   Security & Governance Platform (packages/security)
         ↓
   Deterministic Platform Policy
         ↓
   Workflow & Execution Engines
         ↓
   Workforce (23 Specialized Workers)
         ↓
   AI Runtime & Models
   ```
2. **AI & Workers Are NEVER Authorities**: Models and autonomous workers cannot self-authorize, self-approve consequential actions, bypass human-in-the-loop (HITL) gates, weaken security policies, or access secrets outside their granted scope.
3. **Deterministic Governance**: Policy decisions (`ALLOW`, `DENY`, `REQUIRE_HITL`, `REQUIRE_ELEVATED_ROLE`, `REQUIRE_ADDITIONAL_CONTEXT`) are computed deterministically without reliance on LLMs.
4. **Local-First & Provider-Agnostic**: Operates self-contained with local encrypted stores while providing clean adapter boundaries for future enterprise identity and secret vaults.

---

## Decision

### 1. Dedicated Subsystem: `packages/security`

We introduce `autoforge-security` under `packages/security` providing centralized identity, authentication, RBAC authorization, governance policy evaluation, HITL approval gatekeeping, scoped secrets management with automatic deep redaction, credential lifecycle adapters, sandboxing guardrails, immutable audit trails, and workforce security profiling.

### 2. Module Decomposition

| Module | Responsibility |
|--------|----------------|
| `models.py` | Domain models (`Subject`, `SubjectType`, `Session`, `Permission`, `RoleDefinition`, `AuthorizationDecision`, `ConsequentialAction`, `GovernancePolicy`, `HITLApprovalGate`, `SecretScope`, `CredentialMetadata`, `AuditRecord`, `SandboxPolicy`) |
| `permissions.py` | Fine-grained permission catalog (`project.*`, `workspace.*`, `architecture.*`, `technology.*`, `execution.*`, `deployment.*`, `migration.*`, `credential.*`, `secret.*`, `governance.*`, `audit.*`, `system.*`) |
| `roles.py` | Canonical RBAC roles (`Administrator`, `Operator`, `Engineer`, `Reviewer`, `Researcher`, `Analyst`, `ModernizationOperator`, `ReadOnlyObserver`) and permission inheritance resolver |
| `identity.py` | Identity provider abstraction (`IdentityProvider`, `LocalIdentityProvider`) for human users, worker identities, and API key management |
| `authentication.py` | Authentication boundary (`AuthenticationService`), session tokens, TTL, revocation, and brute-force mitigation |
| `authorization.py` | Centralized deterministic authorization engine (`AuthorizationEngine`) evaluating Subject + Action + Resource + Context |
| `governance.py` | Governance Policy Engine (`GovernancePolicyEngine`) evaluating consequential action matrix and enforcing non-self-approvable rules |
| `hitl.py` | Centralized Human-in-the-loop Gatekeeper (`HITLManager`) managing gate creation, human approvals/rejections, expiration, and cryptographic resume tokens |
| `secrets.py` | Centralized secrets manager (`SecretsManager`, `SecretValue`) with scoped access and deep recursive redaction from logs, errors, events, and prompts |
| `credentials.py` | Credential lifecycle and encrypted storage abstraction (`CredentialManager`, `CredentialStore`, `LocalEncryptedStore`, `InMemoryCredentialStore`) |
| `sandbox.py` | Sandboxing policy engine (`SandboxPolicyEngine`) enforcing workspace root confinement, path traversal protection, and dangerous command filtering |
| `audit.py` | Audit engine (`AuditEngine`) emitting immutable, correlated audit records capturing actor, role, action, resource, decision, and outcome |
| `events.py` | Security event publisher (`SecurityEventPublisher`) bridging security domain events to `CanonicalEventBus` |
| `worker_guard.py` | Workforce security guard (`WorkforceSecurityGuard`) enforcing strict privilege profiles on all 23 workers (including read-only legacy archaeology and propose-only architects) |
| `engine.py` | Unified platform facade (`SecurityPlatform`) and programmatic control/read models for Phase 16 Product Experience |
| `errors.py` | Typed security exception hierarchy (`SecurityError`, `AuthenticationError`, `AuthorizationError`, `GovernanceError`, `SandboxViolationError`, etc.) |

### 3. Consequential Actions Matrix & Gating
The following actions strictly require approved HITL gates:
- `TECH_STACK_FINALIZATION`
- `ARCHITECTURE_FINALIZATION`
- `MIGRATION_EXECUTION`
- `MIGRATION_CUTOVER`
- `DEPLOYMENT`
- `DESTRUCTIVE_CLEANUP`
- `CREDENTIAL_ACCESS` (for sensitive operations)
- `SECURITY_CONFIGURATION_CHANGE`
- `ARTIFACT_PUBLICATION`

AI workers attempting any of these operations receive `REQUIRE_HITL`. Upon explicit approval by an authorized human actor, a cryptographically signed resume token is issued to permit execution.

### 4. Workforce Guardrails
- **14 Greenfield Workers**: Strict scoping. `system_architect` and `tech_lead` may PROPOSE designs but cannot FINALIZE without human approval.
- **9 Legacy Modernization Workers**: Legacy intake, archaeology, and dependency analysis workers are strictly READ-ONLY. Modernization strategy and architecture reconstructors are PROPOSE-ONLY. Migration and cutover specialists are gated by HITL.

---

## Consequences

- **Positive**: Complete deterministic protection against unauthorized actions, privilege escalation, worker self-approval, and secret leakage.
- **Positive**: Clean integration into `AutoForgeSystem` via `packages/composition/src/autoforge_composition/security_wiring.py`.
- **Positive**: Rich programmatic read and control APIs ready for Phase 16 Product Experience.
- **Positive**: Preserves frozen Phases 1–14 architecture completely.
